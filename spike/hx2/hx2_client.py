"""Client-only cost of one-row `query()` through arcadedb-driver, per HTTP transport.

A canned keep-alive server on 127.0.0.1 answers every request with one fixed row, so only the
client is measured. Subcommands:

  serve PORT_FILE                         the canned server
  one ARM PORT WARM TIMED OUT_JSON        one measurement process (run it with the arm's python)
  study smoke|main OUT_DIR --venvs DIR [--client-cpu N] [--server-cpu N]
  selftest                                the verdict rules on made-up values

Arms: `httpx` (driver on main), `aa` (the same again, the A/A control), `alias` (driver on main
after `httpx2.alias_httpx()`), `httpx2` (the ported driver), `http.client` (driver on main with
`transport="http.client"`). `smoke` is a setup check: it prints and writes no figure.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROUNDS = {"smoke": 1, "main": 20}
CALLS = {"smoke": (20, 50), "main": (2000, 4000)}  # warm-up, timed
ARMS = ["httpx", "aa", "alias", "httpx2", "http.client"]
VENV_OF = {"httpx": "httpx", "aa": "httpx", "alias": "alias", "httpx2": "httpx2", "http.client": "httpx"}
MIN_CLEAN = {"smoke": 0, "main": 16}
AA_LIMITS = (0.97, 1.03)
MARGIN = (0.97, 1.03)
MAX_WIDTH = 1.10  # upper end of the interval divided by its lower end
THROTTLE_SHARE = 0.01
GATE_C, GATE_MAX_S = 70, 180
POSTED = {"alias": 193 / 233, "http.client": 61 / 233}  # the figures to verify, from an earlier hand run
POSTED_TOLERANCE = 0.05
METRICS = ["wall_us", "p50_us", "cpu_us", "import_ms", "rss_import_kib", "rss_peak_kib"]

BODY = json.dumps({"result": [{"id": 1, "name": "ada"}], "limit": 20000, "returned": 1, "truncated": False}).encode()
REPLY = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(BODY), BODY)


def serve(port_file: str) -> None:
    server = socket.create_server(("127.0.0.1", 0))
    Path(port_file + ".new").write_text(str(server.getsockname()[1]))
    os.replace(port_file + ".new", port_file)

    def handle(conn: socket.socket) -> None:
        buf = b""
        while True:
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            head, buf = buf.split(b"\r\n\r\n", 1)
            length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            while len(buf) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            buf = buf[length:]
            conn.sendall(REPLY)

    while True:
        conn, _ = server.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def proc_status_kib(key: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    raise RuntimeError(f"no {key} in /proc/self/status")


def one(arm: str, port: int, warm: int, timed: int, out: str) -> None:
    started = time.perf_counter()
    if arm == "alias":
        import httpx2

        httpx2.alias_httpx()
    from arcadedb_driver import ArcadeDBServer

    import_ms = (time.perf_counter() - started) * 1e3
    rss_import = proc_status_kib("VmRSS")
    loaded = {name for name in ("httpx", "httpx2") if name in sys.modules}
    if arm == "alias":
        check(sys.modules["httpx"].__name__ == "httpx2", "alias_httpx() did not take effect")
    elif arm == "httpx2":
        check(loaded == {"httpx2"}, f"the ported driver loaded {sorted(loaded)}")
    else:
        check(loaded == {"httpx"}, f"the driver on main loaded {sorted(loaded)}")

    options = {"transport": "http.client"} if arm == "http.client" else {}
    expected = [{"id": 1, "name": "ada"}]
    with ArcadeDBServer(base_url=f"http://127.0.0.1:{port}", **options) as server:
        check((server._transport is not None) == (arm == "http.client"), "the wrong transport is in use")
        db = server.db("db")

        def call() -> list[dict[str, object]]:
            reply = db.query(language="sql", command="SELECT FROM Person WHERE id = :id", params={"id": 1})
            return reply.result

        check(call() == expected, "unexpected rows on the first call")
        for _ in range(warm):
            call()
        samples = [0] * timed
        wrong = 0
        cpu0, wall0 = time.process_time(), time.perf_counter()
        for i in range(timed):
            t0 = time.perf_counter_ns()
            rows = call()
            samples[i] = time.perf_counter_ns() - t0
            wrong += len(rows) != 1
        wall1, cpu1 = time.perf_counter(), time.process_time()
        check(wrong == 0 and call() == expected, "unexpected rows in or after the timed calls")
    result = {
        "arm": arm,
        "python": sys.version.split()[0],
        "wall_us": (wall1 - wall0) / timed * 1e6,
        "p50_us": statistics.median(samples) / 1e3,
        "cpu_us": (cpu1 - cpu0) / timed * 1e6,
        "import_ms": import_ms,
        "rss_import_kib": rss_import,
        "rss_peak_kib": proc_status_kib("VmHWM"),
    }
    Path(out).write_text(json.dumps(result))


def check(ok: bool, why: str) -> None:
    if not ok:
        print(f"CHECK FAILED: {why}", file=sys.stderr)
        raise SystemExit(4)


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
    try:
        total = 0
        for cpu in cpus:
            base = Path(f"/sys/devices/system/cpu/cpu{cpu}/thermal_throttle")
            total += int((base / "core_throttle_total_time_ms").read_text())
        package = Path(f"/sys/devices/system/cpu/cpu{cpus[0]}/thermal_throttle/package_throttle_total_time_ms")
        return total + int(package.read_text())
    except OSError:
        return None


def pinned(cpu: int | None, command: list[str]) -> list[str]:
    return command if cpu is None else ["taskset", "-c", str(cpu), *command]


def run_study(phase: str, out: Path, venvs: Path, client_cpu: int | None, server_cpu: int | None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "rounds").mkdir(exist_ok=True)
    script = str(Path(__file__).resolve())
    port_file = str(Path(tempfile.mkdtemp(prefix="hx2-port-")) / "port")
    server = subprocess.Popen(pinned(server_cpu, [sys.executable, "-I", "-B", script, "serve", port_file]))
    lane = [c for c in (client_cpu, server_cpu) if c is not None]
    warm, timed = CALLS[phase]
    try:
        deadline = time.monotonic() + 30
        while not os.path.exists(port_file):
            check(server.poll() is None and time.monotonic() < deadline, "the canned server did not start")
            time.sleep(0.05)
        port = Path(port_file).read_text()
        for number in range(ROUNDS[phase]):
            done = out / "rounds" / f"round-{number:02d}.json"
            if done.exists():
                continue
            waited = 0.0
            while phase == "main" and (temp := package_temp()) is not None and temp > GATE_C and waited < GATE_MAX_S:
                time.sleep(5)
                waited += 5
            order = ARMS[number % len(ARMS) :] + ARMS[: number % len(ARMS)]
            if (number // len(ARMS)) % 2:
                order = order[::-1]
            before, start, runs = throttle_ms(lane) if lane else None, time.monotonic(), {}
            for arm in order:
                result = out / f"run-{number:02d}-{arm}.json"
                python = str(venvs / VENV_OF[arm] / "bin" / "python")
                command = [python, "-I", "-B", script, "one", arm, port, str(warm), str(timed), str(result)]
                done_run = subprocess.run(pinned(client_cpu, command), capture_output=True, text=True, timeout=600)
                if done_run.returncode:
                    print(f"round {number} arm {arm} failed rc {done_run.returncode}", file=sys.stderr)
                    print("\n".join(done_run.stderr.splitlines()[-15:]), file=sys.stderr)
                    return 4
                runs[arm] = json.loads(result.read_text())
                result.unlink()
            after, wall = throttle_ms(lane) if lane else None, time.monotonic() - start
            throttled = None if before is None or after is None else after - before
            record = {
                "round": number,
                "order": order,
                "runs": runs,
                "throttle_ms": throttled,
                "wall_s": wall,
                "gate_wait_s": waited,
                "temp_c": package_temp(),
            }
            tmp = done.with_suffix(".new")
            tmp.write_text(json.dumps(record, indent=1))
            os.replace(tmp, done)
            print(f"round {number + 1}/{ROUNDS[phase]} done: every arm passed its checks", flush=True)
    finally:
        server.kill()
        server.wait()
    records = [json.loads(p.read_text()) for p in sorted((out / "rounds").glob("round-*.json"))]
    text, code = report(records, phase)
    if phase == "smoke":
        # The analysis runs on the smoke data so that its code is exercised; its text is thrown away.
        for path in (out / "rounds").glob("round-*.json"):
            path.unlink()
        text, code = f"SMOKE PASSED: {len(ARMS)} arms ran and passed their checks. No figure is reported.\n", 0
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


def report(records: list[dict], phase: str) -> tuple[str, int]:
    clean = records
    if phase == "main":
        clean = [
            r
            for r in records
            if r["throttle_ms"] is not None and r["throttle_ms"] <= THROTTLE_SHARE * r["wall_s"] * 1000
        ]
    lines = [f"hx2 client-only study, phase {phase}: {len(clean)} clean of {len(records)} rounds"]
    if not clean or len(clean) < MIN_CLEAN[phase]:
        return lines[0] + f"\nWEAK: fewer than {MIN_CLEAN[phase]} clean rounds, no ratio is reported\n", 3
    worst = 0
    for metric in METRICS:
        values = {arm: [r["runs"][arm][metric] for r in clean] for arm in ARMS}
        ratios = {arm: [v / base for v, base in zip(values[arm], values["httpx"], strict=True)] for arm in ARMS[1:]}
        aa = interval(ratios["aa"])
        valid = AA_LIMITS[0] <= aa[0] <= AA_LIMITS[1]
        gating = metric == "wall_us"
        lines.append(
            f"\n{metric} ({'decides' if gating else 'information only'}); httpx median of rounds "
            f"{statistics.median(values['httpx']):.1f}; A/A {aa[0]:.3f} [{aa[1]:.3f}, {aa[2]:.3f}]"
            f"{'' if valid else ' INVALID: no ratio is reported'}"
        )
        if not valid:
            worst = max(worst, 2 if gating else 0)
            continue
        for arm in ARMS[2:]:
            middle, low, high = interval(ratios[arm])
            word = verdict(low, high)
            if word == "WEAK":
                worst = max(worst, 3 if gating else 0)
                lines.append(f"  {arm:12s} WEAK: the interval is too wide, no ratio is reported")
                continue
            line = (
                f"  {arm:12s} / httpx {middle:.3f} [{low:.3f}, {high:.3f}] rounds {min(ratios[arm]):.3f} to "
                f"{max(ratios[arm]):.3f}  arm median {statistics.median(values[arm]):.1f}  {word}"
            )
            if gating and arm in POSTED:
                match = "REPRODUCED" if abs(middle - POSTED[arm]) <= POSTED_TOLERANCE else "NOT REPRODUCED"
                line += f"  earlier hand run {POSTED[arm]:.3f}: {match}"
            lines.append(line)
        if gating:
            port = [a / b for a, b in zip(values["httpx2"], values["alias"], strict=True)]
            middle, low, high = interval(port)
            lines.append(f"  httpx2 / alias {middle:.3f} [{low:.3f}, {high:.3f}]  {verdict(low, high)}")
    return "\n".join(lines) + "\n", worst


def selftest() -> None:
    def made(factors: dict[str, float], throttle: int = 0) -> list[dict]:
        rng = random.Random(2)
        return [
            {
                "throttle_ms": throttle,
                "wall_s": 10.0,
                "runs": {a: {m: 100 * factors.get(a, 1.0) * rng.uniform(0.998, 1.002) for m in METRICS} for a in ARMS},
            }
            for _ in range(20)
        ]

    text, code = report(made({"alias": 0.83, "httpx2": 0.83, "http.client": 0.26}), "main")
    assert code == 0 and text.count("REPRODUCED") == 2 and "NOT REPRODUCED" not in text and "LESS" in text, text
    text, code = report(made({"alias": 1.0, "httpx2": 1.2, "http.client": 0.5}), "main")
    assert code == 0 and text.count("NOT REPRODUCED") == 2 and "MORE" in text and "WITHIN" in text, text
    text, code = report(made({"aa": 1.1}), "main")
    assert code == 2 and "INVALID" in text, text
    text, code = report(made({}, throttle=5000), "main")
    assert code == 3 and "fewer than 16 clean rounds" in text, text
    assert verdict(0.9, 1.05) == "WEAK" and verdict(0.95, 0.99) == "AT THE EDGE"
    print("selftest passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="what", required=True)
    sub.add_parser("serve").add_argument("port_file")
    p_one = sub.add_parser("one")
    p_one.add_argument("arm", choices=ARMS)
    for name in ("port", "warm", "timed"):
        p_one.add_argument(name, type=int)
    p_one.add_argument("out")
    p_study = sub.add_parser("study")
    p_study.add_argument("phase", choices=list(ROUNDS))
    p_study.add_argument("out", type=Path)
    p_study.add_argument("--venvs", type=Path, required=True)
    p_study.add_argument("--client-cpu", type=int)
    p_study.add_argument("--server-cpu", type=int)
    sub.add_parser("selftest")
    args = parser.parse_args()
    if args.what == "serve":
        serve(args.port_file)
    elif args.what == "one":
        one(args.arm, args.port, args.warm, args.timed, args.out)
    elif args.what == "study":
        return run_study(args.phase, args.out, args.venvs.resolve(), args.client_cpu, args.server_cpu)
    else:
        selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
