#!/usr/bin/env python3
"""UDP receive-only logger."""
import argparse
import socket
import struct
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((args.bind, args.port))
    print(f"{time.time():.6f} listen port={args.port}", flush=True)
    while True:
        data, peer = s.recvfrom(65536)
        rx_ts = time.time()
        if len(data) >= 16:
            seq, send_ts = struct.unpack("!Qd", data[:16])
        else:
            seq, send_ts = -1, 0.0
        print(
            f"{rx_ts:.6f} rx peer={peer[0]}:{peer[1]} "
            f"seq={seq} bytes={len(data)} send_ts={send_ts:.6f}",
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(main() or 0)
