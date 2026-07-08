"""Pure functions that turn LinkParams into `tc` argv lists."""

from __future__ import annotations

import math
from dataclasses import dataclass

# tbf refills its bucket on the scheduler tick; the burst must hold a few ms
# worth of the rate or the bucket runs dry between ticks and tbf caps
# throughput well below the configured bandwidth.
_MIN_BURST_S = 0.004
# Bound on how long a packet may wait in the queue. tbf's own `latency`
# argument is dead once netem is attached as its child (netem replaces tbf's
# queue), so the same bound is enforced via netem's packet limit instead.
_QUEUE_LATENCY_S = 0.4
_AVG_PKT_BYTES = 1500


@dataclass(frozen=True)
class LinkParams:
    bandwidth_bps: int
    delay_us: int
    jitter_us: int
    loss_frac: float
    burst_bps: int


def _format_duration(us: int) -> str:
    if us == 0:
        return "0ms"
    if us % 1_000_000 == 0:
        return f"{us // 1_000_000}s"
    if us % 1_000 == 0:
        return f"{us // 1_000}ms"
    return f"{us}us"


def _format_rate(bps: int) -> str:
    if bps % 1_000_000 == 0:
        return f"{bps // 1_000_000}mbit"
    if bps % 1_000 == 0:
        return f"{bps // 1_000}kbit"
    return f"{bps}bit"


def tbf_burst_bytes(bandwidth_bps: int, burst_bps: int) -> int:
    """The configured burst, floored so the bucket covers _MIN_BURST_S of the
    rate; without the floor tbf cannot sustain high rates at all."""
    return max(burst_bps // 8, int(bandwidth_bps * _MIN_BURST_S / 8))


def netem_limit_packets(p: LinkParams) -> int:
    """Size netem's packet limit for the delay line plus a bounded queue.

    netem's limit counts packets waiting out their delay/jitter as well as
    queued ones, so it must cover the delay line (delay + 4 sigma of jitter at
    line rate) plus _QUEUE_LATENCY_S of queueing; netem's default of 1000
    packets would otherwise act as a multi-second bufferbloat queue at low
    rates.
    """
    hold_s = _QUEUE_LATENCY_S + (p.delay_us + 4 * p.jitter_us) / 1e6
    return max(10, math.ceil(p.bandwidth_bps * hold_s / (8 * _AVG_PKT_BYTES)))


def _netem_tail(p: LinkParams) -> list[str]:
    out: list[str] = ["limit", str(netem_limit_packets(p))]
    if p.delay_us or p.jitter_us:
        out += ["delay", _format_duration(p.delay_us)]
        if p.jitter_us:
            out += [_format_duration(p.jitter_us), "distribution", "normal"]
    if p.loss_frac > 0:
        pct = round(p.loss_frac * 100, 4)
        out += ["loss", f"{pct:g}%"]
    return out


def link_params_to_argv_pair(p: LinkParams, iface: str) -> list[list[str]]:
    """Return the two `tc` argv lists that shape one interface: a tbf root
    enforcing the bandwidth and a netem child carrying delay/jitter/loss."""
    tbf = [
        "tc", "qdisc", "replace", "dev", iface, "root",
        "handle", "1:", "tbf", "rate", _format_rate(p.bandwidth_bps),
        "burst", str(tbf_burst_bytes(p.bandwidth_bps, p.burst_bps)),
        "latency", "400ms",
    ]
    netem = [
        "tc", "qdisc", "replace", "dev", iface, "parent", "1:",
        "handle", "10:", "netem", *_netem_tail(p),
    ]
    return [tbf, netem]
