"""lab.yaml schema, unit parsers, and pydantic models."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

_RATE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(bit|kbit|mbit|gbit)?\s*$", re.IGNORECASE)
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(us|ms|s)\s*$", re.IGNORECASE)
_LOSS_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(%)?\s*$")


def parse_rate_bits_per_sec(value: str) -> int:
    m = _RATE_RE.match(value)
    if not m:
        raise ValueError(f"invalid rate: {value!r}")
    n = float(m.group(1))
    unit = (m.group(2) or "bit").lower()
    factor = {"bit": 1, "kbit": 1_000, "mbit": 1_000_000, "gbit": 1_000_000_000}[unit]
    return int(n * factor)


def parse_duration_us(value: str) -> int:
    m = _DURATION_RE.match(value)
    if not m:
        raise ValueError(f"invalid duration: {value!r}")
    n = float(m.group(1))
    unit = m.group(2).lower()
    factor = {"us": 1, "ms": 1_000, "s": 1_000_000}[unit]
    return int(n * factor)


def parse_loss_fraction(value):
    """Return loss as a fraction in [0, 1].

    Accepts '3%', '0.5%', or a bare number; a bare number means percent,
    exactly like tc's own syntax (`loss: 3` is 3%, not a 300% fraction).
    """
    if isinstance(value, (int, float)):
        pct = float(value)
    else:
        m = _LOSS_RE.match(value)
        if not m:
            raise ValueError(f"invalid loss: {value!r}")
        pct = float(m.group(1))
    if pct < 0 or pct > 100:
        raise ValueError(f"loss out of range [0, 100]%: {value!r}")
    return pct / 100


_HOST_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# tc accepts absurdly low rates but the link just stalls; 8kbit is the
# lowest value that still passes a ping without minutes of queueing.
_MIN_BANDWIDTH_BPS = 8_000
# A token bucket smaller than one full-size packet passes pings but
# stalls every 1500-byte packet, so iperf/TCP hang on a "working" link.
_MIN_BURST_BPS = 12_000


class Host(BaseModel):
    name: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _HOST_NAME_RE.match(v):
            raise ValueError(f"invalid host name {v!r}: must match [a-z][a-z0-9_]*")
        return v


class Link(BaseModel):
    from_: str = Field(alias="from")
    to: str
    bandwidth: str
    delay: str
    jitter: str
    loss: str | float
    burst: str

    @property
    def bandwidth_bps(self) -> int:
        return parse_rate_bits_per_sec(self.bandwidth)

    @property
    def delay_us(self) -> int:
        return parse_duration_us(self.delay)

    @property
    def jitter_us(self) -> int:
        return parse_duration_us(self.jitter)

    @property
    def loss_frac(self) -> float:
        return parse_loss_fraction(self.loss)

    @property
    def burst_bps(self) -> int:
        return parse_rate_bits_per_sec(self.burst)

    @property
    def shaper_name(self) -> str:
        return f"link-{self.from_}-{self.to}"

    @field_validator("bandwidth")
    @classmethod
    def _validate_bandwidth(cls, v: str) -> str:
        if parse_rate_bits_per_sec(v) < _MIN_BANDWIDTH_BPS:
            raise ValueError(f"bandwidth {v!r} too low: minimum is 8kbit")
        return v

    @field_validator("burst")
    @classmethod
    def _validate_burst(cls, v: str) -> str:
        if parse_rate_bits_per_sec(v) < _MIN_BURST_BPS:
            raise ValueError(
                f"burst {v!r} too small: must cover one full-size packet "
                f"(minimum 12kbit = 1500 bytes)"
            )
        return v

    @field_validator("delay", "jitter")
    @classmethod
    def _validate_duration(cls, v: str) -> str:
        parse_duration_us(v)
        return v

    @field_validator("loss")
    @classmethod
    def _validate_loss(cls, v):
        parse_loss_fraction(v)
        return v


class TcpConfig(BaseModel):
    congestion_control: str = "reno"

    @field_validator("congestion_control")
    @classmethod
    def _validate_algo(cls, v: str) -> str:
        # Availability is kernel-dependent, so only the token shape is checked
        # here; a typo would otherwise blow up mid `docker compose up`.
        if not _HOST_NAME_RE.match(v):
            raise ValueError(
                f"invalid congestion_control {v!r}: "
                f"must be a lowercase algorithm name like reno or cubic"
            )
        return v


class Lab(BaseModel):
    hosts: list[Host]
    links: list[Link]
    tcp: TcpConfig

    @field_validator("hosts")
    @classmethod
    def _no_duplicate_hosts(cls, hosts: list[Host]) -> list[Host]:
        names = [h.name for h in hosts]
        if len(set(names)) != len(names):
            raise ValueError("duplicate host names")
        return hosts

    def model_post_init(self, _ctx):
        host_names = {h.name for h in self.hosts}
        seen_pairs: set[frozenset[str]] = set()
        for link in self.links:
            if link.from_ not in host_names:
                raise ValueError(f"link references unknown host: {link.from_}")
            if link.to not in host_names:
                raise ValueError(f"link references unknown host: {link.to}")
            if link.from_ == link.to:
                raise ValueError(f"link connects {link.from_} to itself")
            pair = frozenset((link.from_, link.to))
            if pair in seen_pairs:
                # A second link between the same pair (either direction) is a
                # parallel path that breaks the routing plan.
                raise ValueError(
                    f"duplicate link between {link.from_} and {link.to}"
                )
            seen_pairs.add(pair)
