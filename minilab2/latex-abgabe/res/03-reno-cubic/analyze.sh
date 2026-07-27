#!/bin/sh
set -eux

mkdir -p analysis
rm -f analysis/*

docker run --rm \
	-v "$PWD:/data:ro" \
	-v "$PWD/analysis:/analysis" \
	--workdir /data \
	debian:bookworm-slim \
	bash -eux ./tcptrace-util.sh
bash -eux ./tshark-util.sh
uv run --with matplotlib --with pandas analyze.py
