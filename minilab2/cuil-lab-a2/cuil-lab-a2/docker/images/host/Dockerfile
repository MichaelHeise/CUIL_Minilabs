FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iperf3 tcpdump iproute2 iputils-ping traceroute python3 ca-certificates \
        less procps net-tools ethtool \
    && rm -rf /var/lib/apt/lists/*

COPY tools/*.py /usr/local/bin/
RUN chmod +x /usr/local/bin/udp_server.py /usr/local/bin/udp_client.py \
             /usr/local/bin/tcp_server.py /usr/local/bin/tcp_client.py

RUN printf '%s\n' \
  'cuil-lab host' \
  'UDP/TCP utilities and standard tools for CUIL Assignment 2.' \
  '' \
  'Tools in /usr/local/bin: udp_server.py udp_client.py tcp_server.py tcp_client.py' \
  'Also installed: iperf3, tcpdump, iproute2, traceroute, ethtool.' \
  'PCAPs and logs written to /out/ are visible on the host.' \
  > /etc/motd

WORKDIR /out
CMD ["sleep", "infinity"]
