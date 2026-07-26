#!/bin/sh
set -eux

for algorithm in reno cubic; do
	tshark -r "tcp_${algorithm}.pcap" \
		-Y 'tcp.stream == 1 && tcp.analysis.retransmission' \
		-T fields -E header=y \
		-e tcp.time_relative \
		>"analysis/${algorithm}-retransmissions.csv"
done
