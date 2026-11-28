#!/usr/bin/env bash
# hx2-server: arcadedb-driver on httpx, httpx2 and http.client against a real ArcadeDB server (PREREG.md of the study folder has the rules).
# Started in the study folder as `bash ./run_ab.sh` with OUT=<label> in the environment. Labels:
#   smoke            lane compare1. One round with very few calls. A setup check, never a result, prints no figure.
#   main, main-r2    lane compare1. The study (main-r2: the one unchanged rerun of PREREG.md).
#   pace             CI only (HX2_CI=1). One round with the main call counts: block wall times, no figure of any arm.
# One server container of the pinned image runs on the second cpu of the lane, the client processes on the first.
# Everything is written below ./$OUT. A restarted job keeps the finished rounds. $OUT/analysis.txt is written last.
# Exit: 0 every deciding figure read (smoke, pace: passed), 2 usage, a sum, a pin or an input is wrong, or a deciding figure
# INVALID, 3 a deciding figure WEAK, 4 a run failed a check, 5 not confined to the lane's cores, 124 stopped after 2 hours,
# other: it broke.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
export PATH="$HOME/.local/bin:$PATH"
# shellcheck source=config.env
. "$HERE/config.env"

OUT="${OUT:-}"
case "$OUT" in
smoke) PHASE=smoke ;;
pace) PHASE=pace ;;
main | main-r2) PHASE=main ;;
*)
    echo "OUT must be smoke, main or main-r2 (got '$OUT')" >&2
    exit 2
    ;;
esac
# HX2_CI=1 skips the turbo and governor checks, which a CI runner cannot pass. Only on GitHub Actions, never for a result.
ci="${HX2_CI:-0}"
if [ "$ci" = 1 ]; then
    if [ "${GITHUB_ACTIONS:-}" != true ] || [ "$PHASE" = main ]; then
        echo "HX2_CI is for smoke and pace on GitHub Actions only" >&2
        exit 2
    fi
elif [ "$PHASE" = pace ]; then
    echo "pace is for CI only" >&2
    exit 2
fi
O="$HERE/$OUT"

sha256sum --quiet -c SHA256SUMS || {
    echo "the kit differs from SHA256SUMS: a partial copy or an edit" >&2
    exit 2
}

# shellcheck disable=SC2086  # the list is split into its parts on purpose
expand() { local part a b; for part in ${1//,/ }; do a=${part%-*}; b=${part#*-}; seq "$a" "$b"; done | tr '\n' ' '; }
allowed="$(sed -n 's/^Cpus_allowed_list:[[:space:]]*//p' /proc/self/status)"
lane="${HUMEM_HOST_LANE:-}"
cpus="${HUMEM_HOST_CPUS:-}"
job="${HUMEMOPS_JOB:-}"
mkdir -p "$O"
if [ -z "$cpus" ] || [ "$(expand "$allowed")" != "$(expand "$cpus")" ] || [ "$(nproc)" != 2 ] || [ "$lane" != compare1 ] || [ -z "$job" ]; then
    printf 'refused: Cpus_allowed_list=%s HUMEM_HOST_CPUS=%s HUMEM_HOST_LANE=%s HUMEMOPS_JOB=%s nproc=%s; %s needs lane compare1 with 2 cpus and a job name\n' \
        "$allowed" "$cpus" "$lane" "$job" "$(nproc)" "$OUT" | tee "$O/REFUSED.txt" >&2
    exit 5
fi
# the first cpu of the lane runs the client, the second the server container
read -r CLIENT_CPU SERVER_CPU <<<"$(expand "$cpus")"

{
    printf 'started %s\nhost %s\nkernel %s\nlabel %s\nphase %s\nci %s\n' "$(date -Is)" "$(hostname)" "$(uname -srm)" "$OUT" "$PHASE" "$ci"
    printf 'nproc %s\nCpus_allowed_list %s\nclient cpu %s\nserver cpu %s\n' "$(nproc)" "$allowed" "$CLIENT_CPU" "$SERVER_CPU"
    printf 'HUMEM_HOST_LANE=%s HUMEM_HOST_CPUS=%s HUMEM_HOST_CELL_CLASS=%s HUMEM_HOST_MEMORY_GB=%s HUMEMOPS_JOB=%s\n' \
        "$lane" "$cpus" "${HUMEM_HOST_CELL_CLASS:-}" "${HUMEM_HOST_MEMORY_GB:-}" "$job"
    printf 'driver_main %s\ndriver_spike %s\n' "$HX2_COMMIT_MAIN" "$HX2_COMMIT_SPIKE"
    printf 'server image %s\nserver heap %s, container memory %s, database tmpfs %s\n' \
        "$HX2_IMAGE" "$HX2_SERVER_HEAP" "$HX2_SERVER_MEMORY" "$HX2_SERVER_TMPFS"
    grep -m1 'model name' /proc/cpuinfo
    printf 'uv %s\n' "$(uv --version)"
    docker version --format 'docker server {{.Server.Version}}'
    printf 'kit sums:\n'
    cat "$HERE/SHA256SUMS"
} >>"$O/env.txt"
if [ "$ci" != 1 ]; then
    no_turbo="$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)"
    governor="$(cat "/sys/devices/system/cpu/cpu$CLIENT_CPU/cpufreq/scaling_governor")"
    server_governor="$(cat "/sys/devices/system/cpu/cpu$SERVER_CPU/cpufreq/scaling_governor")"
    printf 'governor %s %s\nno_turbo %s\n' "$governor" "$server_governor" "$no_turbo" >>"$O/env.txt"
    [ "$no_turbo" = 1 ] || { echo "turbo is on: the registration says turbo off" >&2; exit 2; }
    if [ "$governor" != powersave ] || [ "$server_governor" != powersave ]; then
        echo "the governor is not powersave" >&2
        exit 2
    fi
fi

# the server image, by digest (only a setup check may pull it)
if ! docker image inspect "$HX2_IMAGE" >/dev/null 2>&1; then
    if [ "$PHASE" = main ]; then
        echo "the server image is not on this host: run smoke first (it pulls it by digest)" >&2
        exit 2
    fi
    docker pull -q "$HX2_IMAGE" >>"$O/docker.log" 2>&1 || {
        echo "docker pull failed (see $OUT/docker.log)" >&2
        exit 2
    }
fi

# one locked environment per driver (untimed); the driver is rebuilt from the kit's source tree every time
for arm in httpx httpx2; do
    UV_PROJECT_ENVIRONMENT="$O/venv/$arm" uv sync --frozen --project "$HERE/arms/$arm" --python "$HX2_PYTHON" \
        --reinstall-package arcadedb-driver --refresh-package arcadedb-driver >>"$O/sync.log" 2>&1 || {
        echo "uv sync failed for arm $arm (see $OUT/sync.log)" >&2
        exit 2
    }
    "$O/venv/$arm/bin/python" -I -B -c 'import sys, importlib.metadata as m
names = ("arcadedb-driver", "httpx", "httpcore", "httpx2", "httpcore2", "h11", "anyio")
have = {d.metadata["Name"]: d.version for d in m.distributions()}
print(sys.argv[1], sys.version.split()[0], " ".join(f"{n}={have[n]}" for n in names if n in have))' "$arm" >>"$O/env.txt"
done

NAME=hx2s-server
# shellcheck disable=SC2317,SC2329  # called by the trap
cleanup() {
    docker inspect -f 'server at the end: running={{.State.Running}} oom_killed={{.State.OOMKilled}}' "$NAME" >>"$O/env.txt" 2>&1 || true
    docker logs "$NAME" >>"$O/server.log" 2>&1 || true
    docker rm -f -v "$NAME" >/dev/null 2>&1 || true
}
docker rm -f -v "$NAME" >/dev/null 2>&1 || true
trap cleanup EXIT
trap 'exit 143' INT TERM
# a throwaway password of this run; the server is reachable on the container's bridge address only, no port is published
HX2_PASSWORD="hx2-$(tr -d - </proc/sys/kernel/random/uuid)"
export HX2_PASSWORD HX2_SERVER_VERSION
# The label and the cpuset inside the job's cpus are what make the container the job's own for the host's scheduler.
# ARCADEDB_JMX is one space: no remote JMX port.
docker run -d --name "$NAME" --label "humemops.job=$job" --cpuset-cpus "$SERVER_CPU" \
    --memory "$HX2_SERVER_MEMORY" --memory-swap "$HX2_SERVER_MEMORY" \
    --tmpfs "/home/arcadedb/databases:rw,mode=1777,size=$HX2_SERVER_TMPFS" \
    -e ARCADEDB_OPTS_MEMORY="-Xms$HX2_SERVER_HEAP -Xmx$HX2_SERVER_HEAP" -e ARCADEDB_JMX=" " \
    -e JAVA_OPTS="-Darcadedb.server.rootPassword=$HX2_PASSWORD" "$HX2_IMAGE" >>"$O/docker.log"
docker inspect -f 'server container image={{.Image}} cpuset={{.HostConfig.CpusetCpus}} memory={{.HostConfig.Memory}} network={{.HostConfig.NetworkMode}}' "$NAME" >>"$O/env.txt"
ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$NAME")"
[ -n "$ip" ] || { echo "the server container has no address (see $OUT/server.log)" >&2; exit 2; }

rc=0
timeout --kill-after=30s 2h "$O/venv/httpx/bin/python" -I -B "$HERE/hx2_server.py" study "$PHASE" "$O" \
    --url "http://$ip:2480" --venvs "$O/venv" --client-cpu "$CLIENT_CPU" --lane-cpus "$CLIENT_CPU,$SERVER_CPU" 2>&1 |
    tee -a "$O/log.txt" || rc=${PIPESTATUS[0]}
{
    printf 'server processes:\n'
    docker top "$NAME" -o pid,args | sed -E 's/rootPassword=[^ ]+/rootPassword=REDACTED/g'
} >>"$O/env.txt" 2>&1 || true
printf 'finished %s rc %s\n' "$(date -Is)" "$rc" >>"$O/env.txt"
exit "$rc"
