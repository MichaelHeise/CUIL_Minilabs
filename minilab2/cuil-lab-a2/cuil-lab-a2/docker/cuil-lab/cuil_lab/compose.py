"""Generate a docker-compose dict from a validated Lab."""

from __future__ import annotations

from typing import Any

from .schema import Lab


def _net_name(a: str, b: str) -> str:
    # No project prefix here: compose prepends the project name itself, so
    # embedding it too would yield cuil_cuil_net_... in `docker network ls`.
    return f"net_{a}_{b}"


def lab_to_compose(lab: Lab, *, project_name: str = "cuil") -> dict[str, Any]:
    services: dict[str, dict[str, Any]] = {}
    networks: dict[str, dict[str, Any]] = {}

    host_attachments: dict[str, list[str]] = {h.name: [] for h in lab.hosts}
    shaper_attachments: dict[str, list[str]] = {}

    for link in lab.links:
        net_a = _net_name(link.from_, link.shaper_name)
        net_b = _net_name(link.shaper_name, link.to)
        networks[net_a] = {"driver": "bridge"}
        networks[net_b] = {"driver": "bridge"}
        host_attachments[link.from_].append(net_a)
        host_attachments[link.to].append(net_b)
        shaper_attachments[link.shaper_name] = [net_a, net_b]

    for host in lab.hosts:
        services[host.name] = {
            "image": "cuil/host",
            "container_name": f"{project_name}_{host.name}",
            "hostname": host.name,
            "cap_add": ["NET_ADMIN"],
            "privileged": True,
            "sysctls": {
                "net.ipv4.tcp_congestion_control": lab.tcp.congestion_control,
            },
            # Shared /out (TUI captures + tool logs) plus a per-host private
            # /node workspace; a student drops a self-written logger into
            # nodes/<host>/ on the host and runs it from the shell on /node.
            "volumes": ["./out:/out", f"./nodes/{host.name}:/node"],
            "networks": {n: {} for n in host_attachments[host.name]},
            "tty": True,
            "stdin_open": True,
            "command": ["sleep", "infinity"],
        }

    for link in lab.links:
        services[link.shaper_name] = {
            "image": "cuil/shaper",
            "container_name": f"{project_name}_{link.shaper_name}",
            "hostname": link.shaper_name,
            "cap_add": ["NET_ADMIN"],
            "sysctls": {"net.ipv4.ip_forward": "1"},
            "volumes": ["./out:/out"],
            "networks": {n: {} for n in shaper_attachments[link.shaper_name]},
            "command": ["sleep", "infinity"],
        }

    return {"services": services, "networks": networks}
