#!/usr/bin/env bash
#
# Launch the cuil-lab TUI. Bootstraps the Python venv and builds the
# Docker images on first run, then opens the dashboard.
#
# Usage:
#   ./run-lab.sh                 # use docker/lab.yaml, project "cuil"
#   ./run-lab.sh --config my.yaml --project demo
#   ./run-lab.sh --build         # force-rebuild the images, then run
#   ./run-lab.sh --clean         # remove leftover lab containers first
#                                # (use after a crashed/killed session)
#
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
DOCKER_DIR="$SCRIPT_DIR/docker"
PKG_DIR="$DOCKER_DIR/cuil-lab"
VENV="$PKG_DIR/.venv"
CLI="$VENV/bin/cuil-lab"

force_build=0
clean=0
project="cuil"
args=()
prev=""
for a in "$@"; do
    if [[ "$a" == "--build" ]]; then
        force_build=1
    elif [[ "$a" == "--clean" ]]; then
        clean=1
    else
        args+=("$a")
        if [[ "$prev" == "--project" ]]; then
            project="$a"
        fi
    fi
    prev="$a"
done

# --- Preflight: tools that pip cannot install for us ------------------------

missing=()

# docker CLI must exist...
if ! command -v docker >/dev/null 2>&1; then
    missing+=("docker (install Docker Desktop: https://docs.docker.com/get-docker/)")
fi

# ...and we need a Python with the venv module to bootstrap the package.
if ! command -v python3 >/dev/null 2>&1; then
    missing+=("python3 (>= 3.11)")
elif ! python3 -c 'import venv' >/dev/null 2>&1; then
    missing+=("python3 venv module (e.g. apt install python3-venv)")
fi

if [[ "${#missing[@]}" -gt 0 ]]; then
    echo "error: missing required dependencies:" >&2
    for m in "${missing[@]}"; do
        echo "  - $m" >&2
    done
    exit 1
fi

# cuil-lab needs Python 3.11+ (see pyproject.toml requires-python).
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    have=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    echo "error: python3 >= 3.11 required, found $have." >&2
    exit 1
fi

# The docker daemon must also be running, not just the CLI installed.
if ! docker info >/dev/null 2>&1; then
    echo "error: Docker is installed but the daemon is not reachable." >&2
    echo "       Start Docker Desktop (or the docker service) and retry." >&2
    exit 1
fi

# --- Bootstrap the venv + editable install ---------------------------------

# Recreate the venv if it is missing or incomplete (e.g. a half-finished
# previous run that never produced a working interpreter).
if [[ ! -x "$VENV/bin/python" ]]; then
    echo ">> creating Python virtual environment in $VENV"
    rm -rf "$VENV"
    python3 -m venv "$VENV"
fi

# Install the package and its pip dependencies when the entry point is absent
# or --build is passed. Also refresh a stale venv: a leftover .venv from an
# older checkout can keep the cuil-lab entry point yet miss dependencies added
# since (an editable install does not backfill newly added deps), which
# otherwise crashes `cuil-lab run` with a ModuleNotFoundError. Importing the
# full module chain is a cheap way to detect that and trigger a reinstall.
need_install=0
if [[ ! -x "$CLI" || "$force_build" -eq 1 ]]; then
    need_install=1
elif ! "$VENV/bin/python" -c 'import cuil_lab.__main__' >/dev/null 2>&1; then
    echo ">> existing venv is missing dependencies; refreshing"
    need_install=1
fi
if [[ "$need_install" -eq 1 ]]; then
    echo ">> installing cuil-lab and dependencies"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet --upgrade -e "$PKG_DIR"
fi

# A hard-killed previous session (closed terminal, SIGKILL) leaves the old
# containers running; --clean tears them down before starting fresh.
if [[ "$clean" -eq 1 ]]; then
    echo ">> removing leftover containers of project \"$project\""
    docker ps -aq --filter "name=^${project}_" | xargs -r docker rm -f
fi

# Build the images if absent (or when --build is passed).
if [[ "$force_build" -eq 1 ]] \
   || ! docker image inspect cuil/host >/dev/null 2>&1 \
   || ! docker image inspect cuil/shaper >/dev/null 2>&1; then
    echo ">> building Docker images (cuil/host, cuil/shaper)"
    "$CLI" build
fi

# cuil-lab reads ./lab.yaml from the working directory by default.
# (${args[@]+...} guards the empty-array case under `set -u` on bash 3.2.)
cd "$DOCKER_DIR"
exec "$CLI" run ${args[@]+"${args[@]}"}
