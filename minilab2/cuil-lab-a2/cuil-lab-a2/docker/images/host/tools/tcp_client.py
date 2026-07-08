#!/usr/bin/env python3
"""TCP load generator with persistent or reconnect mode."""
import argparse
import os
import socket
import struct
import sys
import time

# Generous by default: at 30% bidirectional loss a handshake regularly needs
# several SYN retries (1s, 2s, 4s, 8s backoff) before it completes.
CONNECT_TIMEOUT_S = float(os.environ.get("CUIL_CONNECT_TIMEOUT", "20"))


def payload_size(value: str) -> int:
    n = int(value)
    if n < 16:
        raise argparse.ArgumentTypeError(
            "size must be at least 16 bytes (8-byte seq + 8-byte timestamp)"
        )
    return n


def connect(host: str, port: int) -> socket.socket:
    sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
    # Only the handshake gets a deadline; sends may legitimately stall for
    # longer under heavy loss while TCP retransmits.
    sock.settimeout(None)
    return sock


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--mode", choices=["persistent", "reconnect"],
                    default="persistent")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--size", type=payload_size, default=64)
    args = ap.parse_args()

    sock = None
    sent = 0
    try:
        for seq in range(1, args.count + 1):
            try:
                if args.mode == "reconnect" or sock is None:
                    if sock is not None:
                        sock.close()
                        sock = None
                    sock = connect(args.host, args.port)
                send_ts = time.time()
                body = struct.pack("!Qd", seq, send_ts) + b"\x00" * (args.size - 16)
                framed = struct.pack("!I", len(body)) + body
                sock.sendall(framed)
                sent += 1
                print(
                    f"{send_ts:.6f} tx peer={args.host}:{args.port} "
                    f"seq={seq} bytes={len(framed)} mode={args.mode}",
                    flush=True,
                )
            except (TimeoutError, OSError) as exc:
                if args.mode == "reconnect":
                    # One failed handshake must not abort the run; the err
                    # line keeps the gap visible in the timeline log.
                    print(
                        f"{time.time():.6f} err peer={args.host}:{args.port} "
                        f"seq={seq} {exc}",
                        flush=True,
                    )
                    sock = None
                else:
                    print(
                        f"error: {args.host}:{args.port}: {exc} "
                        f"(is tcp_server.py running on {args.host}?)",
                        file=sys.stderr,
                    )
                    return 1
            if seq < args.count:
                time.sleep(args.interval)
    finally:
        if sock is not None:
            sock.close()
    if sent == 0:
        print(
            f"error: no message reached {args.host}:{args.port} "
            f"(is tcp_server.py running on {args.host}?)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
