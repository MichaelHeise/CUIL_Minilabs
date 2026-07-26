#!/bin/sh
set -eux

mkdir -p analysis
docker run --rm \
  -v "$PWD:/data:ro" \
  -v "$PWD/analysis:/analysis" \
  --workdir /data \
  debian:bookworm-slim \
  bash -eux ./tcptrace-util.sh
uv run analyze.py
