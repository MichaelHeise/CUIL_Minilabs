#!/usr/bin/env python3
"""UDP load generator."""
import argparse
import socket
import struct
import sys
import time


def payload_size(value: str) -> int:
    n = int(value)
    if n < 16:
        raise argparse.ArgumentTypeError(
            "size must be at least 16 bytes (8-byte seq + 8-byte timestamp)"
        )
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--size", type=payload_size, default=64)
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pad = args.size - 16
    for seq in range(1, args.count + 1):
        send_ts = time.time()
        payload = struct.pack("!Qd", seq, send_ts) + b"\x00" * pad
        s.sendto(payload, (args.host, args.port))
        print(
            f"{send_ts:.6f} tx peer={args.host}:{args.port} "
            f"seq={seq} bytes={len(payload)}",
            flush=True,
        )
        if seq < args.count:
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
