"""1 Hz sampling of stats from each host."""
from __future__ import annotations

import time
from typing import Callable

from .controller import ControllerProtocol
from .stats import (
    busiest_socket,
    compute_rate,
    format_rate,
    parse_proc_net_dev,
    parse_ss_output,
)


class StatsSampler:
    """Stateful sampler: remembers the previous tx counter per host so each
    sample reports a live send rate instead of a lifetime byte total."""

    def __init__(
        self,
        controller: ControllerProtocol,
        host_names: list[str],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.controller = controller
        self.host_names = list(host_names)
        self.clock = clock
        self._prev: dict[str, tuple[float, int]] = {}

    def sample(self) -> dict[str, str]:
        summaries: dict[str, str] = {}
        for h in self.host_names:
            ss_out = self.controller.exec_in_node(h, ["ss", "-tin"]).output
            proc = self.controller.exec_in_node(h, ["cat", "/proc/net/dev"]).output
            eth0 = parse_proc_net_dev(proc).get("eth0")
            now = self.clock()
            if eth0 is None:
                tx_str = "no eth0"
            else:
                prev = self._prev.get(h)
                self._prev[h] = (now, eth0.tx_bytes)
                if prev is None:
                    tx_str = "tx --"
                else:
                    rate = compute_rate(
                        prev[1], eth0.tx_bytes, elapsed_s=now - prev[0],
                    )
                    tx_str = f"tx {format_rate(rate)}"
            s = busiest_socket(parse_ss_output(ss_out))
            sock_str = ""
            if s is not None and s.cwnd is not None:
                sock_str = f"  cwnd {s.cwnd}"
                if s.srtt_ms is not None:
                    sock_str += f" srtt {s.srtt_ms:.1f}ms"
            summaries[h] = f"{h}  {tx_str}{sock_str}"
        return summaries
