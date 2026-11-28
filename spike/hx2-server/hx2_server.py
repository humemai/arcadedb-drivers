"""What a user of arcadedb-driver would feel from httpx2 against a real ArcadeDB server.

Each measurement is one client process that runs one cell with one arm against a running server.

  one CELL ARM WARM TIMED OUT_JSON --url URL     one measurement process (run it with the arm's python)
  study smoke|pace|main OUT_DIR --url URL --venvs DIR [--client-cpu N] [--lane-cpus A,B]
  selftest                                       the verdict rules on made-up values

`one` and `study` read the root password from HX2_PASSWORD. `study` also reads HX2_SERVER_VERSION: it waits for
the server, creates the databases and rows, warms the server up, and runs the rounds. `smoke` and `pace` are setup
checks: they report no figure of any arm (`pace` prints the wall time of each block of arms, to size a run).

Cells: `query1` (a one-row query()), `txcommand` (one transaction around a one-row command(): begin, command,
commit), `read100` and `read5000` (query() returning that many rows), `batch` (one batch_load() of 5,000 vertices
and 5,000 edges). Arms: `httpx` (driver on main), `aa` (the same again, the A/A control), `httpx2` (the ported
driver), `http.client` (driver on main with `transport="http.client"`, which does not carry batch_load).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

CELLS = ["query1", "txcommand", "read100", "read5000", "batch"]
ARMS = ["httpx", "aa", "httpx2", "http.client"]
# transport="http.client" carries query(), command() and the transaction calls, not batch_load().
ARMS_OF = {cell: [a for a in ARMS if not (cell == "batch" and a == "http.client")] for cell in CELLS}
VENV_OF = {"httpx": "httpx", "aa": "httpx", "httpx2": "httpx2", "http.client": "httpx"}
CALLS = {  # (warm-up, timed) calls of one process
    "query1": (2000, 4000),
    "txcommand": (500, 1500),
    "read100": (500, 1500),
    "read5000": (20, 100),
    "batch": (2, 12),
}
SMOKE_CALLS = {"query1": (10, 20), "txcommand": (3, 5), "read100": (3, 5), "read5000": (1, 2), "batch": (1, 2)}
ROUNDS = {"smoke": 1, "pace": 1, "main": 24}
MIN_CLEAN = {"smoke": 0, "pace": 0, "main": 18}
# (arm, base, whether the pair decides)
PAIRS = [("httpx2", "httpx", True), ("http.client", "httpx", True), ("http.client", "httpx2", False)]
METRICS = ["wall_us", "p50_us", "cpu_us", "rss_import_kib", "rss_peak_kib"]
DECIDING = "wall_us"
AA_LIMITS = (0.97, 1.03)
MARGIN = (0.97, 1.03)
MAX_WIDTH = 1.10  # upper end of the interval divided by its lower end
THROTTLE_SHARE = 0.01
GATE_C, GATE_MAX_S = 70, 60
READY_MAX_S = 180

DB, BATCH_DB = "hx2s", "hx2sbatch"
ROWS = {"read100": ("Row100", 100), "read5000": ("Row5000", 5000)}
BATCH_N = 5000  # vertices of one load; it carries as many edges


def check(ok: bool, why: str) -> None:
    if not ok:
        print(f"CHECK FAILED: {why}", file=sys.stderr)
        raise SystemExit(4)


def connect(url: str, **options: Any) -> Any:
    from arcadedb_driver import ArcadeDBServer, basic_auth

    return ArcadeDBServer(base_url=url, auth=basic_auth("root", os.environ["HX2_PASSWORD"]), **options)


def proc_status_kib(key: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    raise RuntimeError(f"no {key} in /proc/self/status")


def number_of(db: Any, text: str) -> int:
    return int(db.query(language="sql", command=text).result[0]["n"])


Check = Callable[[Any], bool]


def make_call(cell: str, db: Any) -> tuple[Callable[[], Any], Check, Check]:
    """The timed call of a cell, the cheap check of every answer, and the full check of the first and last one."""
    if cell == "query1":

        def call() -> Any:
            text = "SELECT FROM Person WHERE id = :id"
            return db.query(language="sql", command=text, params={"id": 1}).result

        return (
            call,
            lambda rows: len(rows) == 1,
            lambda rows: len(rows) == 1 and rows[0]["name"] == "ada",
        )
    if cell == "txcommand":

        def call() -> Any:
            text = "UPDATE Account SET balance = balance + 1 WHERE id = :id"
            with db.transaction() as tx:
                return tx.command(language="sql", command=text, params={"id": 1}).result

        def updated(rows: Any) -> bool:
            return len(rows) == 1 and rows[0]["count"] == 1

        return call, updated, updated
    if cell == "batch":
        vertices = [
            {"type": "BNode", "id": f"v{i}", "properties": {"id": i, "name": f"node-{i:06d}"}} for i in range(BATCH_N)
        ]
        edges = [{"type": "BEdge", "from_": f"v{i}", "to": f"v{(i + 1) % BATCH_N}"} for i in range(BATCH_N)]

        def call() -> Any:
            return db.batch_load(vertices=vertices, edges=edges)

        def loaded(summary: Any) -> bool:
            return summary["verticesCreated"] == BATCH_N and summary["edgesCreated"] == BATCH_N

        return call, loaded, loaded
    type_name, count = ROWS[cell]

    def call() -> Any:
        return db.query(language="sql", command=f"SELECT FROM {type_name}").result

    return (
        call,
        lambda rows: len(rows) == count,
        lambda rows: len(rows) == count and sum(row["id"] for row in rows) == count * (count - 1) // 2,
    )


def written(cell: str, db: Any) -> int | None:
    """A figure of the database that every call of a writing cell moves by a fixed step, or None."""
    if cell == "txcommand":
        return number_of(db, "SELECT balance AS n FROM Account WHERE id = 1")
    if cell == "batch":
        return number_of(db, "SELECT count(*) AS n FROM BNode")
    return None


def one(cell: str, arm: str, url: str, warm: int, timed: int, out: str) -> None:
    check(arm in ARMS_OF[cell], f"arm {arm} does not run cell {cell}")
    import arcadedb_driver  # noqa: F401  (imported first, so that the memory after the import is read here)

    rss_import = proc_status_kib("VmRSS")
    loaded = {name for name in ("httpx", "httpx2") if name in sys.modules}
    library = "httpx2" if arm == "httpx2" else "httpx"
    check(loaded == {library}, f"arm {arm} loaded {sorted(loaded)}")

    stdlib = arm == "http.client"
    options = {"transport": "http.client"} if stdlib else {}
    with connect(url, **options) as server:
        check((server._transport is not None) == stdlib, "the wrong transport is in use")
        db = server.db(BATCH_DB if cell == "batch" else DB)
        check((db._bound is not None) == stdlib, "the database handle uses the wrong transport")
        if cell == "txcommand":
            with db.transaction() as tx:
                check((tx._bound is not None) == stdlib, "the transaction handle uses the wrong transport")
        call, quick, full = make_call(cell, db)
        before = written(cell, db)
        check(full(call()), "unexpected answer on the first call")
        wrong = 0
        for _ in range(warm):
            wrong += not quick(call())
        samples = [0] * timed
        cpu0, wall0 = time.process_time(), time.perf_counter()
        for i in range(timed):
            t0 = time.perf_counter_ns()
            answer = call()
            samples[i] = time.perf_counter_ns() - t0
            wrong += not quick(answer)
            del answer
        wall1, cpu1 = time.perf_counter(), time.process_time()
        rss_peak = proc_status_kib("VmHWM")
        check(wrong == 0 and full(call()), "unexpected answer in or after the timed calls")
        if before is not None:
            step = BATCH_N if cell == "batch" else 1
            after = written(cell, db)
            check(after is not None and after - before == (warm + timed + 2) * step, "the writes did not all commit")
    result = {
        "cell": cell,
        "arm": arm,
        "python": sys.version.split()[0],
        "wall_us": (wall1 - wall0) / timed * 1e6,
        "p50_us": statistics.median(samples) / 1e3,
        "cpu_us": (cpu1 - cpu0) / timed * 1e6,
        "rss_import_kib": rss_import,
        "rss_peak_kib": rss_peak,
    }
    Path(out).write_text(json.dumps(result))


def recreate(server: Any, name: str) -> Any:
    if server.exists(name):
        server.drop_database(name)
    server.create_database(name)
    return server.db(name)


def setup(url: str) -> None:
    """Waits for the server, checks its version, and creates the rows the read and write cells use."""
    deadline = time.monotonic() + READY_MAX_S
    with connect(url) as server:
        while True:
            try:
                if server.ready():
                    break
            except Exception as error:  # the port refuses connections while the server starts
                last = type(error).__name__
            else:
                last = "not ready"
            check(time.monotonic() < deadline, f"the server was not ready in {READY_MAX_S} s ({last})")
            time.sleep(1)
        version = server.server_info().version
        check(version.startswith(os.environ["HX2_SERVER_VERSION"]), f"unexpected server version {version}")
        print(f"server version {version}", flush=True)
        db = recreate(server, DB)
        for statement in (
            "CREATE VERTEX TYPE Person",
            "CREATE PROPERTY Person.id INTEGER",
            "CREATE INDEX ON Person (id) UNIQUE",
            "INSERT INTO Person SET id = 1, name = 'ada'",
            "CREATE VERTEX TYPE Account",
            "CREATE PROPERTY Account.id INTEGER",
            "CREATE INDEX ON Account (id) UNIQUE",
            "INSERT INTO Account SET id = 1, balance = 0",
        ):
            db.command(language="sql", command=statement)
        for type_name, count in ROWS.values():
            db.command(language="sql", command=f"CREATE VERTEX TYPE {type_name}")
            db.batch_load(
                vertices=[
                    {"type": type_name, "properties": {"id": i, "name": f"row-{i:06d}", "score": i / 7}}
                    for i in range(count)
                ]
            )
            check(number_of(db, f"SELECT count(*) AS n FROM {type_name}") == count, f"{type_name} is not filled")


def reset_batch(url: str) -> None:
    """An empty database for one batch process, so that every arm loads into the same state."""
    with connect(url) as server:
        db = recreate(server, BATCH_DB)
        db.command(language="sql", command="CREATE VERTEX TYPE BNode")
        db.command(language="sql", command="CREATE EDGE TYPE BEdge")


def package_temp() -> float | None:
    for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (hwmon / "name").read_text().strip() == "coretemp":
                return int((hwmon / "temp1_input").read_text()) / 1000
        except OSError:
            return None
    return None


def throttle_ms(cpus: list[int]) -> int | None:
    """Core throttle time of the lane's cpus plus the package throttle time, or None if unreadable."""
    if not cpus:
        return None
    try:
        total = 0
        for cpu in cpus:
            base = Path(f"/sys/devices/system/cpu/cpu{cpu}/thermal_throttle")
            total += int((base / "core_throttle_total_time_ms").read_text())
        package = Path(f"/sys/devices/system/cpu/cpu{cpus[0]}/thermal_throttle/package_throttle_total_time_ms")
        return total + int(package.read_text())
    except OSError:
        return None


def arm_order(arms: list[str], number: int) -> list[str]:
    """The arms rotated by the round number, reversed in every second block of len(arms) rounds."""
    shift = number % len(arms)
    order = arms[shift:] + arms[:shift]
    return order[::-1] if (number // len(arms)) % 2 else order


def run_one(
    url: str, venvs: Path, out: Path, cell: str, arm: str, counts: tuple[int, int], client_cpu: int | None
) -> dict[str, Any]:
    if cell == "batch":
        reset_batch(url)
    result = out / "run.json"
    command = [str(venvs / VENV_OF[arm] / "bin" / "python"), "-I", "-B", str(Path(__file__).resolve()), "one"]
    command += [cell, arm, str(counts[0]), str(counts[1]), str(result), "--url", url]
    if client_cpu is not None:
        command = ["taskset", "-c", str(client_cpu), *command]
    done = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if done.returncode:
        print(f"cell {cell} arm {arm} failed rc {done.returncode}", file=sys.stderr)
        print("\n".join(done.stderr.splitlines()[-25:]), file=sys.stderr)
        raise SystemExit(4)
    value: dict[str, Any] = json.loads(result.read_text())
    result.unlink()
    return value


def run_study(phase: str, out: Path, url: str, venvs: Path, client_cpu: int | None, lane: list[int]) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "rounds").mkdir(exist_ok=True)
    counts = SMOKE_CALLS if phase == "smoke" else CALLS
    setup(url)
    for cell in CELLS:  # one discarded process per cell, so that round 0 does not meet a cold server
        run_one(url, venvs, out, cell, "httpx", counts[cell], client_cpu)
    print("server warm-up done", flush=True)
    for number in range(ROUNDS[phase]):
        done = out / "rounds" / f"round-{number:02d}.json"
        if done.exists():
            continue
        waited = 0.0
        while phase == "main" and (temp := package_temp()) is not None and temp > GATE_C and waited < GATE_MAX_S:
            time.sleep(5)
            waited += 5
        shift = number % len(CELLS)
        cells = {}
        for cell in CELLS[shift:] + CELLS[:shift]:
            order = arm_order(ARMS_OF[cell], number)
            before, start = throttle_ms(lane), time.monotonic()
            runs = {arm: run_one(url, venvs, out, cell, arm, counts[cell], client_cpu) for arm in order}
            wall = time.monotonic() - start
            after = throttle_ms(lane)
            throttled = None if before is None or after is None else after - before
            cells[cell] = {"order": order, "runs": runs, "throttle_ms": throttled, "wall_s": wall}
        record = {"round": number, "cells": cells, "gate_wait_s": waited, "temp_c": package_temp()}
        tmp = done.with_suffix(".new")
        tmp.write_text(json.dumps(record, indent=1))
        os.replace(tmp, done)
        print(f"round {number + 1}/{ROUNDS[phase]} done: every run passed its checks", flush=True)
    paths = sorted((out / "rounds").glob("round-*.json"))
    records = [json.loads(p.read_text()) for p in paths]
    text, code = report(records, phase)
    if phase != "main":
        # The analysis ran on this data so that its code is exercised; its text and the data are thrown away.
        for path in paths:
            path.unlink()
        runs_done = sum(len(arms) for arms in ARMS_OF.values())
        if phase == "smoke":
            text = f"SMOKE PASSED: {runs_done} runs (cells times arms) passed their checks. No figure is reported.\n"
        else:
            walls = {cell: records[0]["cells"][cell]["wall_s"] for cell in CELLS}
            text = "PACE: wall seconds of each block of arms in one round (no figure of any arm)\n"
            text += "".join(f"  {cell} {wall:.1f}\n" for cell, wall in walls.items())
            text += f"  one round {sum(walls.values()):.1f}\n"
        code = 0
    (out / "analysis.txt").write_text(text)
    print(text)
    return code


def interval(values: list[float]) -> tuple[float, float, float]:
    """Median with a 95 percent percentile bootstrap interval (10,000 resamples, seed 1)."""
    rng = random.Random(1)
    medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(10000))
    return statistics.median(values), medians[249], medians[9749]


def verdict(low: float, high: float) -> str:
    if high / low > MAX_WIDTH:
        return "WEAK"
    if high < MARGIN[0]:
        return "LESS"
    if low > MARGIN[1]:
        return "MORE"
    if low >= MARGIN[0] and high <= MARGIN[1]:
        return "WITHIN"
    return "AT THE EDGE"


def report(records: list[dict[str, Any]], phase: str) -> tuple[str, int]:
    lines = [f"hx2 server study, phase {phase}: {len(records)} rounds"]
    worst = 0
    for cell in CELLS:
        blocks = [r["cells"][cell] for r in records]
        if phase == "main":
            blocks = [
                b
                for b in blocks
                if b["throttle_ms"] is not None and b["throttle_ms"] <= THROTTLE_SHARE * b["wall_s"] * 1000
            ]
        lines.append(f"\n== {cell}: {len(blocks)} clean of {len(records)} rounds")
        if not blocks or len(blocks) < MIN_CLEAN[phase]:
            lines.append(f"WEAK: fewer than {MIN_CLEAN[phase]} clean rounds, nothing is reported for this cell")
            worst = max(worst, 3)
            continue
        for metric in METRICS:
            decides = metric == DECIDING
            values = {arm: [b["runs"][arm][metric] for b in blocks] for arm in ARMS_OF[cell]}
            middle, low, high = interval([a / b for a, b in zip(values["aa"], values["httpx"], strict=True)])
            valid = AA_LIMITS[0] <= middle <= AA_LIMITS[1]
            lines.append(
                f"{metric} ({'decides' if decides else 'information only'}); httpx median of rounds "
                f"{statistics.median(values['httpx']):.1f}; A/A {middle:.3f} [{low:.3f}, {high:.3f}]"
                f"{'' if valid else ' INVALID: no ratio is reported'}"
            )
            if not valid:
                if decides:
                    worst = max(worst, 2)
                continue
            for arm, base, pair_decides in PAIRS:
                if arm not in values or base not in values:
                    continue
                label = f"  {arm} / {base}" + ("" if pair_decides else " (information only)")
                ratios = [a / b for a, b in zip(values[arm], values[base], strict=True)]
                middle, low, high = interval(ratios)
                word = verdict(low, high)
                if word == "WEAK":
                    if decides and pair_decides:
                        worst = max(worst, 3)
                    lines.append(f"{label}: WEAK, the interval is too wide, no ratio is reported")
                    continue
                gap, gap_low, gap_high = interval([a - b for a, b in zip(values[arm], values[base], strict=True)])
                lines.append(
                    f"{label} {middle:.3f} [{low:.3f}, {high:.3f}] rounds {min(ratios):.3f} to {max(ratios):.3f}  "
                    f"{word}  difference {gap:+.1f} [{gap_low:+.1f}, {gap_high:+.1f}]  "
                    f"medians {statistics.median(values[arm]):.1f} and {statistics.median(values[base]):.1f}"
                )
    return "\n".join(lines) + "\n", worst


def selftest() -> None:
    def made(factors: dict[str, float], throttle: int = 0) -> list[dict[str, Any]]:
        rng = random.Random(2)

        def run(arm: str) -> dict[str, float]:
            return {m: 100 * factors.get(arm, 1.0) * rng.uniform(0.998, 1.002) for m in METRICS}

        return [
            {
                "cells": {
                    cell: {"throttle_ms": throttle, "wall_s": 10.0, "runs": {a: run(a) for a in ARMS_OF[cell]}}
                    for cell in CELLS
                }
            }
            for _ in range(ROUNDS["main"])
        ]

    text, code = report(made({"httpx2": 0.83, "http.client": 0.26}), "main")
    assert code == 0 and "LESS" in text and "MORE" not in text and "INVALID" not in text, text
    assert "http.client" in text.split("== read5000")[1] and "http.client" not in text.split("== batch")[1], text
    text, code = report(made({"httpx2": 1.2}), "main")
    assert code == 0 and "MORE" in text and "WITHIN" in text, text
    text, code = report(made({"aa": 1.1}), "main")
    assert code == 2 and "INVALID" in text, text
    text, code = report(made({}, throttle=5000), "main")
    assert code == 3 and "fewer than 18 clean rounds" in text, text
    assert verdict(0.9, 1.05) == "WEAK" and verdict(0.95, 0.99) == "AT THE EDGE"
    for arms in (ARMS, ARMS_OF["batch"]):
        orders = [arm_order(arms, n) for n in range(ROUNDS["main"])]
        for position in range(len(arms)):
            assert len({sum(o[position] == a for o in orders) for a in arms}) == 1, f"unbalanced {arms}"
    print("selftest passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="what", required=True)
    p_one = sub.add_parser("one")
    p_one.add_argument("cell", choices=CELLS)
    p_one.add_argument("arm", choices=ARMS)
    p_one.add_argument("warm", type=int)
    p_one.add_argument("timed", type=int)
    p_one.add_argument("out")
    p_one.add_argument("--url", required=True)
    p_study = sub.add_parser("study")
    p_study.add_argument("phase", choices=list(ROUNDS))
    p_study.add_argument("out", type=Path)
    p_study.add_argument("--url", required=True)
    p_study.add_argument("--venvs", type=Path, required=True)
    p_study.add_argument("--client-cpu", type=int)
    p_study.add_argument("--lane-cpus", default="")
    sub.add_parser("selftest")
    args = parser.parse_args()
    if args.what == "one":
        one(args.cell, args.arm, args.url, args.warm, args.timed, args.out)
    elif args.what == "study":
        lane = [int(c) for c in args.lane_cpus.split(",") if c]
        return run_study(args.phase, args.out, args.url, args.venvs.resolve(), args.client_cpu, lane)
    else:
        selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
