#!/bin/sh
set -eux

apt-get update && apt-get install -y tcptrace

for algorithm in reno cubic; do
  tcptrace -n -l -r -W -zxy -G -o2 --output_dir=/analysis --output_prefix="${algorithm}-" "/data/tcp_${algorithm}.pcap" > "/analysis/${algorithm}-summary.txt"
done
