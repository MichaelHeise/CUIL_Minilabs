#!/bin/sh
set -eux

extract_data() {
	tshark -r "$2" \
		-Y 'tcp.stream == 1 && tcp.len > 0' \
		-T fields -E header=y -E separator=, \
		-e ip.id -e tcp.time_relative \
		>"analysis/$1"
}

for alg in reno cubic; do
	# Retransmissions
	tshark -r "tcp_${alg}.pcap" \
		-Y 'tcp.stream == 1 && tcp.analysis.retransmission' \
		-T fields -E header=y -E separator=, \
		-e tcp.time_relative \
		>"analysis/${alg}-retransmissions.csv"

	# Raw data for packet loss calc
	extract_data "${alg}-sender.csv" "tcp_${alg}.pcap"
	extract_data "${alg}-receiver.csv" "tcp_${alg}_receiver.pcap"
done
