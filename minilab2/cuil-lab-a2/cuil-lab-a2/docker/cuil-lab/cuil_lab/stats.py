"""Parsers for `ss -tin` and /proc/net/dev. Pure, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SocketStats:
    local_addr: str
    local_port: int
    peer_addr: str
    peer_port: int
    cwnd: int | None
    retx: int | None
    srtt_ms: float | None
    bytes_sent: int | None


@dataclass(frozen=True)
class IfaceCounters:
    rx_bytes: int
    rx_packets: int
    tx_bytes: int
    tx_packets: int


@dataclass(frozen=True)
class HostStats:
    sockets: list[SocketStats] = field(default_factory=list)
    interfaces: dict[str, IfaceCounters] = field(default_factory=dict)


# `ss -tin` suppresses the Netid column (single protocol selected), so data
# lines start with the State column; `ss -atin` keeps the `tcp` prefix.
# Accept both.
_SS_ENDPOINT_RE = re.compile(
    r"^(?:tcp\s+)?ESTAB\s+\S+\s+\S+\s+(\S+):(\d+)\s+(\S+):(\d+)"
)
_CWND_RE = re.compile(r"\bcwnd:(\d+)")
_RETX_RE = re.compile(r"\bretrans:\d+/(\d+)")
_RTT_RE = re.compile(r"\brtt:(\d+(?:\.\d+)?)/")
_BYTES_SENT_RE = re.compile(r"\bbytes_sent:(\d+)")


def parse_ss_output(text: str) -> list[SocketStats]:
    out: list[SocketStats] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _SS_ENDPOINT_RE.match(lines[i])
        if not m:
            i += 1
            continue
        local_addr, local_port, peer_addr, peer_port = m.groups()
        detail = ""
        if i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
            detail = lines[i + 1]
            i += 2
        else:
            i += 1
        cwnd_m = _CWND_RE.search(detail)
        retx_m = _RETX_RE.search(detail)
        rtt_m = _RTT_RE.search(detail)
        sent_m = _BYTES_SENT_RE.search(detail)
        out.append(SocketStats(
            local_addr=local_addr,
            local_port=int(local_port),
            peer_addr=peer_addr,
            peer_port=int(peer_port),
            cwnd=int(cwnd_m.group(1)) if cwnd_m else None,
            retx=int(retx_m.group(1)) if retx_m else None,
            srtt_ms=float(rtt_m.group(1)) if rtt_m else None,
            bytes_sent=int(sent_m.group(1)) if sent_m else None,
        ))
    return out


def busiest_socket(sockets: list[SocketStats]) -> SocketStats | None:
    """The socket that has sent the most bytes; during an iperf3 run the
    first listed socket is typically the idle control connection."""
    if not sockets:
        return None
    return max(sockets, key=lambda s: s.bytes_sent or 0)


def parse_proc_net_dev(text: str) -> dict[str, IfaceCounters]:
    out: dict[str, IfaceCounters] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        head, rest = line.split(":", 1)
        name = head.strip()
        parts = rest.split()
        if len(parts) < 16:
            continue
        out[name] = IfaceCounters(
            rx_bytes=int(parts[0]),
            rx_packets=int(parts[1]),
            tx_bytes=int(parts[8]),
            tx_packets=int(parts[9]),
        )
    return out


def compute_rate(prev: int, cur: int, *, elapsed_s: float) -> int:
    """Return bits per second between two byte counters; clamps to 0 on reset."""
    if cur < prev or elapsed_s <= 0:
        return 0
    return int((cur - prev) * 8 / elapsed_s)


def format_rate(bps: int) -> str:
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbit/s"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} kbit/s"
    return f"{bps} bit/s"
