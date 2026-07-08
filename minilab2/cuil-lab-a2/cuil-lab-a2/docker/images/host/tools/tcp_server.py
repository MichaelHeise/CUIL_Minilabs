#!/usr/bin/env python3
"""TCP server reading length-prefixed frames."""
import argparse
import socket
import struct
import sys
import threading
import time

# Frames larger than this are garbage (a foreign client); drop the connection
# rather than trying to buffer gigabytes from a bogus length prefix.
MAX_FRAME = 1 << 20


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def handle(conn, peer):
    try:
        while True:
            hdr = recv_exact(conn, 4)
            if not hdr:
                return
            (length,) = struct.unpack("!I", hdr)
            if length < 16 or length > MAX_FRAME:
                return  # not one of our frames; drop the connection
            body = recv_exact(conn, length)
            if body is None:
                return
            rx_ts = time.time()
            seq, send_ts = struct.unpack("!Qd", body[:16])
            print(
                f"{rx_ts:.6f} rx peer={peer[0]}:{peer[1]} "
                f"seq={seq} bytes={length + 4} send_ts={send_ts:.6f}",
                flush=True,
            )
    except OSError:
        return
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9001)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # A just-killed previous instance can still hold the port for a moment.
    # SO_REUSEADDR covers TIME_WAIT but not a lingering LISTEN socket, so
    # retry the bind for a few seconds before giving up.
    deadline = time.time() + 5.0
    while True:
        try:
            s.bind((args.bind, args.port))
            break
        except OSError:
            if time.time() >= deadline:
                raise
            time.sleep(0.25)
    s.listen(8)
    print(f"{time.time():.6f} listen port={args.port}", flush=True)
    # One thread per connection: an idle or stray connection must never delay
    # rx logging of real traffic (rx timestamps feed the latency analysis).
    while True:
        conn, peer = s.accept()
        threading.Thread(target=handle, args=(conn, peer), daemon=True).start()


if __name__ == "__main__":
    sys.exit(main() or 0)
