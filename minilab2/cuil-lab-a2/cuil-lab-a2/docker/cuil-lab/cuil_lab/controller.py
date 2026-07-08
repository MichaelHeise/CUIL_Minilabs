"""The only module that imports docker. Wraps docker-py + docker compose."""

from __future__ import annotations

import ipaddress
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

import docker
import yaml

from .compose import lab_to_compose
from .schema import Lab
from .shaping import LinkParams, link_params_to_argv_pair


@dataclass
class ExecResult:
    exit_code: int
    output: str


def ensure_work_dirs(work_dir: Path, lab: Lab) -> None:
    """Create the shared ``out/`` dir and a private ``nodes/<host>/`` dir per
    host under ``work_dir`` before ``docker compose up``.

    Creating them up front means the bind-mount targets are owned by the user
    who launched the lab. If we let Docker auto-create the missing host paths,
    it makes them root-owned, which blocks students from reading or writing
    their ``nodes/<host>/`` workspace from the host side.
    """
    (work_dir / "out").mkdir(parents=True, exist_ok=True)
    for host in lab.hosts:
        (work_dir / "nodes" / host.name).mkdir(parents=True, exist_ok=True)


def compute_routing_plan(
    networks: list[dict], host_nodes: set[str]
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Plan static routes and /etc/hosts entries for full host-to-host reach.

    ``networks`` describes the link graph: one entry per docker network, each
    with a ``subnet`` and the two endpoints it joins (a host and a shaper) as
    ``{node: ip}``. Hosts and shapers are graph nodes; a network is an edge.

    Returns ``(routes, host_entries)`` where:

    - ``routes`` is ``(node, subnet, via_ip)``: on ``node``, route ``subnet``
      via ``via_ip``. Every node gets a route to every subnet it is not directly
      attached to, via the neighbour one hop closer to that subnet, so a star's
      leaves reach each other through the hub.
    - ``host_entries`` is ``(host, peer, ip)``: in ``host``'s /etc/hosts, map
      ``peer`` to the peer IP reached along the path between them.
    """
    # adjacency: node -> list of (neighbour, my_ip_on_shared_net)
    adj: dict[str, list[tuple[str, str]]] = {}
    node_net_ip: dict[str, dict[str, str]] = {}
    for net in networks:
        items = list(net["endpoints"].items())
        for node, ip in items:
            node_net_ip.setdefault(node, {})[net["name"]] = ip
            adj.setdefault(node, [])
        for (a, ip_a), (b, ip_b) in ((items[0], items[1]), (items[1], items[0])):
            adj[a].append((b, ip_a))

    routes: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for net in networks:
        subnet = net["subnet"]
        endpoints = set(net["endpoints"])
        # BFS outward from the nodes directly on this subnet; each newly reached
        # node routes the subnet via the node it was reached from.
        visited = set(endpoints)
        queue: deque[str] = deque(endpoints)
        while queue:
            node = queue.popleft()
            for neighbour, my_ip in adj[node]:
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                key = (neighbour, subnet)
                if key not in seen:
                    seen.add(key)
                    routes.append((neighbour, subnet, my_ip))
                queue.append(neighbour)

    host_entries: list[tuple[str, str, str]] = []
    hosts = sorted(h for h in host_nodes if h in adj)
    for src in hosts:
        # BFS from src, recording which network each node is first reached on.
        arrival_net: dict[str, str] = {}
        visited = {src}
        queue = deque([src])
        # need the net name per hop; rebuild adjacency with net names locally
        while queue:
            node = queue.popleft()
            for net in networks:
                if node not in net["endpoints"]:
                    continue
                for neighbour in net["endpoints"]:
                    if neighbour in visited:
                        continue
                    visited.add(neighbour)
                    arrival_net[neighbour] = net["name"]
                    queue.append(neighbour)
        for peer in hosts:
            if peer == src:
                continue
            net_name = arrival_net.get(peer)
            if net_name is None:
                continue
            host_entries.append((src, peer, node_net_ip[peer][net_name]))
    return routes, host_entries


class ControllerProtocol(Protocol):
    def up(self, lab: Lab, *, project_name: str, work_dir: Path) -> None: ...
    def down(self) -> None: ...
    def exec_in_node(self, node: str, argv: list[str]) -> ExecResult: ...
    def stream_exec(self, node: str, argv: list[str]) -> Iterator[str]: ...
    def apply_link_params(self, shaper: str, params: LinkParams) -> ExecResult: ...
    def set_tcp_cong(self, node: str, algo: str) -> ExecResult: ...
    def is_up(self) -> bool: ...


class DockerController:
    def __init__(self) -> None:
        self.client = docker.from_env()
        self.project_name = "cuil"
        self.work_dir: Path | None = None

    def up(self, lab: Lab, *, project_name: str, work_dir: Path) -> None:
        self.project_name = project_name
        self.work_dir = work_dir
        ensure_work_dirs(work_dir, lab)
        compose = lab_to_compose(lab, project_name=project_name)
        compose_path = work_dir / ".cuil-lab" / "compose.yaml"
        compose_path.parent.mkdir(parents=True, exist_ok=True)
        compose_path.write_text(yaml.safe_dump(compose, sort_keys=False))
        # --project-directory makes the compose file's relative ./out volume
        # resolve to <work_dir>/out (next to lab.yaml) rather than the hidden
        # .cuil-lab/ dir where the compose file itself lives.
        subprocess.run(
            ["docker", "compose", "-p", project_name,
             "--project-directory", str(work_dir),
             "-f", str(compose_path), "up", "-d"],
            check=True, cwd=work_dir,
        )
        self._wire_routing(lab)
        self._disable_offloads(lab)
        self._apply_startup_shaping(lab)

    def _apply_startup_shaping(self, lab: Lab) -> None:
        """Install the lab.yaml link parameters as qdiscs at startup, so the
        topology display matches what is actually on the wire and stale
        qdiscs from a crashed session get replaced."""
        for link in lab.links:
            params = LinkParams(
                bandwidth_bps=link.bandwidth_bps,
                delay_us=link.delay_us,
                jitter_us=link.jitter_us,
                loss_frac=link.loss_frac,
                burst_bps=link.burst_bps,
            )
            res = self.apply_link_params(link.shaper_name, params)
            if res.exit_code != 0:
                raise RuntimeError(
                    f"applying lab.yaml link params on {link.shaper_name} "
                    f"failed: {res.output.strip()}"
                )

    def _disable_offloads(self, lab: Lab) -> None:
        """Turn off GRO/GSO/TSO on every lab interface: offloads make pcaps
        show multi-kilobyte "packets" and let bursts bypass the shaper's
        per-packet accounting. Best-effort: images without ethtool keep
        offloads on."""
        nodes = [h.name for h in lab.hosts] + [l.shaper_name for l in lab.links]
        for node in nodes:
            self.exec_in_node(node, [
                "sh", "-c",
                "command -v ethtool >/dev/null 2>&1 || exit 0; "
                "for i in /sys/class/net/eth*; do "
                "[ -e \"$i\" ] || continue; "
                "ethtool -K \"${i##*/}\" gro off gso off tso off "
                ">/dev/null 2>&1 || true; done",
            ])

    def _gather_networks(self, lab: Lab) -> list[dict]:
        """Inspect the running containers to build the link graph for routing:
        one entry per docker network with its subnet and the {node: ip} of the
        host and shaper it joins."""
        nodes = [h.name for h in lab.hosts] + [link.shaper_name for link in lab.links]
        endpoints: dict[str, dict[str, str]] = {}
        subnets: dict[str, str] = {}
        for node in nodes:
            container = self.client.containers.get(self._container_name(node))
            nets = container.attrs["NetworkSettings"]["Networks"]
            for net_name, info in nets.items():
                ip = info.get("IPAddress")
                plen = info.get("IPPrefixLen")
                if not ip or not plen:
                    continue
                endpoints.setdefault(net_name, {})[node] = ip
                subnets[net_name] = str(
                    ipaddress.ip_network(f"{ip}/{plen}", strict=False)
                )
        return [
            {"name": name, "subnet": subnets[name], "endpoints": eps}
            for name, eps in endpoints.items()
            if len(eps) >= 2
        ]

    def _wire_routing(self, lab: Lab) -> None:
        """Give every host a path to every other host: traffic between directly
        linked nodes flows through their shaper (where `tc` is applied), and
        traffic between non-adjacent hosts (e.g. a star's leaves) is routed
        through the intermediate hub. Also writes /etc/hosts on each host so
        name lookups (`iperf3 -c n2`, `traceroute n3`) resolve without
        inter-network DNS.
        """
        networks = self._gather_networks(lab)
        host_nodes = {h.name for h in lab.hosts}
        routes, host_entries = compute_routing_plan(networks, host_nodes)
        for node, subnet, via_ip in routes:
            res = self.exec_in_node(node, [
                "ip", "route", "replace", subnet, "via", via_ip,
            ])
            if res.exit_code != 0:
                raise RuntimeError(
                    f"routing setup failed on {node}: ip route replace "
                    f"{subnet} via {via_ip}: {res.output.strip()}"
                )
        for host, peer, ip in host_entries:
            res = self.exec_in_node(host, [
                "sh", "-c",
                f"grep -q ' {peer}$' /etc/hosts "
                f"|| echo '{ip} {peer}' >> /etc/hosts",
            ])
            if res.exit_code != 0:
                raise RuntimeError(
                    f"routing setup failed on {host}: /etc/hosts entry for "
                    f"{peer}: {res.output.strip()}"
                )

    def down(self) -> None:
        if self.work_dir is None:
            return
        compose_path = self.work_dir / ".cuil-lab" / "compose.yaml"
        if not compose_path.exists():
            return
        subprocess.run(
            ["docker", "compose", "-p", self.project_name,
             "--project-directory", str(self.work_dir),
             "-f", str(compose_path), "down"],
            check=False, cwd=self.work_dir,
        )
        # Forget the work dir so a second down() (e.g. the CLI's finally after
        # the TUI already cleaned up) is a no-op instead of a slow re-run.
        self.work_dir = None

    def _container_name(self, node: str) -> str:
        return f"{self.project_name}_{node}"

    def exec_in_node(self, node: str, argv: list[str]) -> ExecResult:
        container = self.client.containers.get(self._container_name(node))
        result = container.exec_run(argv, demux=False)
        return ExecResult(
            exit_code=result.exit_code,
            output=result.output.decode("utf-8", errors="replace"),
        )

    def stream_exec(self, node: str, argv: list[str]) -> Iterator[str]:
        container = self.client.containers.get(self._container_name(node))
        _, stream = container.exec_run(argv, stream=True, demux=False)
        for chunk in stream:
            yield chunk.decode("utf-8", errors="replace")

    def apply_link_params(self, shaper: str, params: LinkParams) -> ExecResult:
        ip_link = self.exec_in_node(
            shaper,
            ["sh", "-c",
             "ip -o link | awk -F': ' '/^[0-9]+: eth/ "
             "{split($2, a, \"@\"); print a[1]}'"],
        )
        if ip_link.exit_code != 0:
            return ip_link
        ifaces = [s.strip() for s in ip_link.output.strip().splitlines() if s.strip()]
        last = ExecResult(0, "")
        for iface in ifaces:
            for argv in link_params_to_argv_pair(params, iface):
                last = self.exec_in_node(shaper, argv)
                if last.exit_code != 0:
                    return last
        return last

    def set_tcp_cong(self, node: str, algo: str) -> ExecResult:
        return self.exec_in_node(node, [
            "sysctl", "-w", f"net.ipv4.tcp_congestion_control={algo}",
        ])

    def is_up(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False


class FakeController:
    """In-memory controller for unit/e2e tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self.link_params: dict[str, LinkParams] = {}
        self.tcp_algos: dict[str, str] = {}
        self.up_called: bool = False
        self.down_called: bool = False

    def up(self, lab: Lab, *, project_name: str, work_dir: Path) -> None:
        self.up_called = True

    def down(self) -> None:
        self.down_called = True

    def exec_in_node(self, node: str, argv: list[str]) -> ExecResult:
        self.calls.append((node, argv))
        return ExecResult(0, "")

    def stream_exec(self, node: str, argv: list[str]) -> Iterator[str]:
        self.calls.append((node, argv))
        yield ""

    def apply_link_params(self, shaper: str, params: LinkParams) -> ExecResult:
        self.link_params[shaper] = params
        return ExecResult(0, "")

    def set_tcp_cong(self, node: str, algo: str) -> ExecResult:
        self.tcp_algos[node] = algo
        return ExecResult(0, "")

    def is_up(self) -> bool:
        return True
