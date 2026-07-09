"""Textual TUI for cuil-lab."""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Log, Static

from .controller import ControllerProtocol
from .modals import HelpModal, Iperf3Modal, LinkParamsModal, TcpCongModal, ToolModal
from .schema import Lab
from .shaping import LinkParams
from .terminal import NodeTerminal, render_tab_bar, shell_layout_mode


def _topology_text(
    lab: Lab,
    *,
    link_params: dict[str, dict[str, str]] | None = None,
    host_cong: dict[str, str] | None = None,
) -> str:
    """Build the topology ASCII art for a lab as plain text.

    ``link_params`` (shaper name -> bandwidth/delay/jitter/loss strings) and
    ``host_cong`` (host name -> algorithm) override the displayed values for
    live updates; when omitted the lab's own lab.yaml values are shown.
    """
    if len(lab.hosts) == 2 and len(lab.links) == 1:
        h1, h2 = lab.hosts
        link = lab.links[0]
        lp = (link_params or {}).get(link.shaper_name) or {
            "bandwidth": link.bandwidth,
            "delay": link.delay,
            "jitter": link.jitter,
            "loss": str(link.loss),
        }
        hc = host_cong or {}
        c1 = hc.get(h1.name, lab.tcp.congestion_control)
        c2 = hc.get(h2.name, lab.tcp.congestion_control)

        hw, sw, gap = 12, 14, 7

        def host_box(name: str, algo: str) -> list[str]:
            return [
                "┌" + "─" * hw + "┐",
                "│" + f"{name:^{hw}}" + "│",
                "│" + f"{algo:^{hw}}" + "│",
                "│" + " " * hw + "│",
                "│" + " " * hw + "│",
                "│" + " " * hw + "│",
                "└" + "─" * hw + "┘",
            ]

        shaper_box = [
            "╔" + "═" * sw + "╗",
            "║" + f"{link.shaper_name:^{sw}}" + "║",
            "║" + f"{lp['bandwidth']:^{sw}}" + "║",
            "║" + f"{lp['delay'] + ' delay':^{sw}}" + "║",
            "║" + f"{lp['jitter'] + ' jit':^{sw}}" + "║",
            "║" + f"{lp['loss'] + ' loss':^{sw}}" + "║",
            "╚" + "═" * sw + "╝",
        ]

        boxes = [host_box(h1.name, c1), shaper_box, host_box(h2.name, c2)]
        connector_row = 3
        rows = []
        for i in range(len(shaper_box)):
            sep = "═" * gap if i == connector_row else " " * gap
            rows.append(boxes[0][i] + sep + boxes[1][i] + sep + boxes[2][i])
        return "\n".join("  " + r for r in rows)

    hub = find_star_hub(lab)
    if hub is not None:
        return _star_topology_text(
            lab, hub, link_params=link_params, host_cong=host_cong,
        )

    lines = ["Topology:"]
    for host in lab.hosts:
        lines.append(f"  host  {host.name}")
    for link in lab.links:
        lines.append(
            f"  link  {link.shaper_name}  {link.from_} <-> {link.to}"
        )
    return "\n".join(lines)


def find_star_hub(lab: Lab) -> str | None:
    """Return the hub host if ``lab`` is a star (one host on every link, each
    other host a distinct leaf reached through exactly one link), else None.

    A star needs at least two spokes; the two-host single-link lab is handled
    by its own renderer and is not treated as a star here.
    """
    if len(lab.links) < 2:
        return None
    pairs = [(link.from_, link.to) for link in lab.links]
    host_names = {h.name for h in lab.hosts}
    for hub in host_names:
        if not all(hub in pair for pair in pairs):
            continue
        leaves = [b if a == hub else a for a, b in pairs]
        if any(leaf == hub for leaf in leaves):
            continue  # self-link
        if len(set(leaves)) != len(leaves):
            continue  # a leaf reached by more than one link
        if set(leaves) | {hub} != host_names or len(leaves) != len(host_names) - 1:
            continue  # not every host is a leaf of this hub
        return hub
    return None


def _star_topology_text(
    lab: Lab,
    hub: str,
    *,
    link_params: dict[str, dict[str, str]] | None = None,
    host_cong: dict[str, str] | None = None,
) -> str:
    """Render a star as a hub box branching to one boxed leaf per spoke, each
    annotated with its link's name and shaped parameters."""
    hc = host_cong or {}
    hub_algo = hc.get(hub, lab.tcp.congestion_control)

    w = 10              # inner box width
    pad = "  "          # left margin
    bus_col = w // 2    # tee position inside the hub's bottom edge
    bus_x = len(pad) + 1 + bus_col
    conn = 5            # dashes from the bus into each leaf box

    lines = [f"Topology (star, hub {hub}):", ""]
    lines.append(pad + "┌" + "─" * w + "┐")
    lines.append(pad + "│" + f"{hub:^{w}}" + "│")
    lines.append(pad + "│" + f"{hub_algo:^{w}}" + "│")
    lines.append(
        pad + "└" + "─" * bus_col + "┬" + "─" * (w - bus_col - 1) + "┘"
    )

    spokes = [
        (link.to if link.from_ == hub else link.from_, link)
        for link in lab.links
    ]
    sp = " " * bus_x
    for i, (leaf, link) in enumerate(spokes):
        last = i == len(spokes) - 1
        lp = (link_params or {}).get(link.shaper_name) or {
            "bandwidth": link.bandwidth,
            "delay": link.delay,
            "jitter": link.jitter,
            "loss": str(link.loss),
        }
        label = (
            f"{link.shaper_name}  {lp['bandwidth']}  "
            f"{lp['delay']}/{lp['jitter']}  {lp['loss']} loss"
        )
        lines.append(sp + "│" + " " * conn + "┌" + "─" * w + "┐")
        lines.append(
            sp + ("└" if last else "├") + "─" * conn
            + "┤" + f"{leaf:^{w}}" + "│  " + label
        )
        lines.append(
            sp + (" " if last else "│") + " " * conn + "└" + "─" * w + "┘"
        )
    return "\n".join(lines)


def _nowrap(text: str) -> Text:
    """Wrap topology art in a non-wrapping, cropping Text so long spoke labels
    never fold into the diagram when the dashboard is narrow (split view)."""
    return Text(text, no_wrap=True, overflow="crop")


class TopologyView(Static):
    """Static widget that draws the lab topology as ASCII art."""

    def __init__(self, lab: Lab) -> None:
        self.lab = lab
        super().__init__(_nowrap(_topology_text(lab)), markup=False)


class LogView(Log):
    """Rolling action log that auto-scrolls so the newest line stays visible
    (a Static crops at the bottom, hiding fresh feedback mid-session)."""

    def __init__(self) -> None:
        super().__init__(max_lines=200, auto_scroll=True)
        self.lines_history: list[str] = []

    def append(self, line: str) -> None:
        self.lines_history.append(line)
        self.lines_history = self.lines_history[-200:]
        self.write_line(line)


class StatsView(Static):
    """Static widget for live stats (placeholder until Task 13)."""

    def __init__(self) -> None:
        super().__init__("Live (1 s window)", markup=False)


@dataclass
class _Job:
    """A running traffic-generation task with an estimated duration.

    Progress is estimated from wall-clock elapsed vs. ``total`` seconds:
    iperf3 runs for its ``-t`` duration, the UDP/TCP tools for roughly
    ``count * interval`` seconds. The client runs detached in its
    container, so this is an estimate, not a measured completion.
    """

    label: str
    start: float
    total: float


class ProgressView(Static):
    """Static widget that renders a progress bar per running traffic task."""

    BAR_WIDTH = 24

    def __init__(self) -> None:
        super().__init__("", markup=False)

    @classmethod
    def _bar(cls, frac: float) -> str:
        filled = int(round(frac * cls.BAR_WIDTH))
        return "[" + "#" * filled + "." * (cls.BAR_WIDTH - filled) + "]"

    def render_jobs(self, jobs: list[_Job], now: float) -> None:
        lines = []
        for job in jobs:
            elapsed = now - job.start
            frac = 1.0 if job.total <= 0 else min(1.0, elapsed / job.total)
            shown = min(elapsed, job.total)
            done = " done" if frac >= 1.0 else ""
            lines.append(
                f"{job.label}  {self._bar(frac)} {int(frac * 100):3d}%  "
                f"({shown:.0f}s/{job.total:.0f}s){done}"
            )
        self.update("\n".join(lines))


class CuilLabScreen(Screen):
    """Default screen whose ``render`` exposes the live topology text.

    Textual's screen ``render`` returns the *background* renderable, not the
    composited widget output. Surfacing the topology text here lets callers
    (and the e2e pilot tests) introspect the topology via
    ``pilot.app.screen.render()`` without having to walk the widget tree. It
    reads the app's current link/cong state so updates from ``l``/``c``/``r``
    are reflected.
    """

    def __init__(self) -> None:
        super().__init__(id="_default")

    def render(self) -> str:  # type: ignore[override]
        app = self.app
        return _topology_text(
            app.lab,
            link_params=app.link_display,
            host_cong=app.host_cong,
        )


class CuilLabApp(App):
    BINDINGS = [
        Binding("q", "quit_app", "quit"),
        Binding("question_mark", "help", "help"),
        Binding("l", "edit_link", "link"),
        Binding("c", "edit_tcp_cong", "cong"),
        Binding("i", "run_iperf3", "iperf3"),
        Binding("u", "run_udp", "udp"),
        Binding("t", "run_tcp", "tcp"),
        Binding("p", "capture", "capture"),
        Binding("s", "open_shell", "shell"),
        # Priority so focus cycling and shell-close always work even while an
        # embedded shell has focus and is otherwise swallowing keystrokes.
        Binding("ctrl+o", "cycle_focus", "focus", priority=True),
        Binding("ctrl+w", "close_shell", "close", priority=True),
        Binding("r", "reset", "reset"),
    ]

    CSS = """
    #body         { height: 1fr; }
    /* A round border whose colour signals which side has keyboard focus:
       accent when focused, dim otherwise. */
    #dashboard    { width: 1fr; border: round $surface; overflow-x: hidden; }
    #dashboard.lab-focused { border: round $accent; }
    #shell-pane   { width: 0; display: none; border: round $surface; }
    #shell-pane.open { width: 1fr; display: block; }
    #shell-pane.shell-focused { border: round $accent; }
    #shell-tabs   { height: 1; display: none; padding: 0 1; background: $panel; }
    #shell-pane.tabbed #shell-tabs { display: block; }
    NodeTerminal.hidden { display: none; }
    /* width:auto so long spoke labels set the widget width and get clipped by
       the dashboard's overflow-x instead of wrapping into the diagram. */
    TopologyView { height: auto; width: auto; max-height: 60%; padding: 1; }
    /* auto height so star labs with more than two hosts are not clipped */
    StatsView    { height: auto; max-height: 10; padding: 1; }
    ProgressView { height: auto; padding: 0 1; }
    LogView      { height: 1fr; padding: 0 1; }
    """

    def __init__(
        self,
        *,
        lab: Lab,
        controller: ControllerProtocol,
        show_help: bool = True,
    ) -> None:
        super().__init__()
        self.lab = lab
        self.controller = controller
        self.show_help = show_help
        self.link_display: dict[str, dict[str, str]] = {
            link.shaper_name: self._link_defaults(link) for link in lab.links
        }
        self.host_cong: dict[str, str] = {
            h.name: lab.tcp.congestion_control for h in lab.hosts
        }
        # Links with a running capture (keyed by shaper name), mapped to the
        # per-endpoint (host, pcap path) pairs recording that link.
        self.capturing: dict[str, list[tuple[str, str]]] = {}
        self._capture_busy = False
        # Running traffic-generation tasks shown in the progress panel.
        self.jobs: list[_Job] = []
        # Lazily created stateful sampler feeding the stats bar, plus a busy
        # flag so a slow docker daemon skips ticks instead of stacking them.
        self._stats_sampler = None
        self._stats_busy = False
        # Open split-view shells, in the order they were opened.
        self._terminals: list[NodeTerminal] = []
        # The shell shown in tabbed mode / last focused.
        self._active_terminal: NodeTerminal | None = None
        self.topology = TopologyView(lab)
        self.stats = StatsView()
        self.progress = ProgressView()
        self.log_view = LogView()

    @staticmethod
    def _link_defaults(link) -> dict[str, str]:
        return {
            "bandwidth": link.bandwidth,
            "delay": link.delay,
            "jitter": link.jitter,
            "loss": str(link.loss),
            "burst": link.burst,
        }

    def _refresh_topology(self) -> None:
        self.topology.update(_nowrap(_topology_text(
            self.lab, link_params=self.link_display, host_cong=self.host_cong,
        )))

    def get_default_screen(self) -> Screen:
        return CuilLabScreen()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="dashboard"):
                yield self.topology
                yield self.stats
                yield self.progress
                yield self.log_view
            # Collapsed pane; split-view shells mount here on 's'. The tab bar
            # stays first and is shown by CSS only in tabbed mode.
            with Vertical(id="shell-pane"):
                yield Static("", id="shell-tabs", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cuil-lab"
        dashboard = self.query_one("#dashboard", Vertical)
        dashboard.border_title = "lab"
        self.query_one("#shell-pane", Vertical).border_title = "shell"
        self._update_focus_style()
        self.set_interval(1.0, self._tick_stats)
        self.set_interval(0.5, self._tick_progress)
        if self.show_help:
            self.push_screen(HelpModal())

    def _update_focus_style(self) -> None:
        """Highlight whichever side holds keyboard focus: the dashboard ('lab')
        when no shell is focused, otherwise the shell pane."""
        lab_focused = not any(t is self.focused for t in self._terminals)
        self.query_one("#dashboard", Vertical).set_class(lab_focused, "lab-focused")
        self.query_one("#shell-pane", Vertical).set_class(
            bool(self._terminals) and not lab_focused, "shell-focused"
        )

    def on_descendant_focus(self, event) -> None:
        # Mouse clicks and Tab land here too, so the active-terminal
        # bookkeeping (pane title, visible tab) follows every focus change,
        # not just Ctrl-O cycling.
        widget = getattr(event, "widget", None)
        if isinstance(widget, NodeTerminal) and widget is not self._active_terminal:
            self._active_terminal = widget
            self._relayout_shells()
        self._update_focus_style()

    def on_descendant_blur(self, event) -> None:
        self._update_focus_style()

    # Single-letter actions type into a focused shell instead of firing, so
    # show them disabled in the footer there. Ctrl-O/Ctrl-W stay live.
    _SHELL_BLOCKED_ACTIONS = frozenset({
        "quit_app", "help", "edit_link", "edit_tcp_cong", "run_iperf3",
        "run_udp", "run_tcp", "capture", "open_shell", "reset",
    })

    def check_action(self, action: str, parameters) -> bool | None:
        if action in self._SHELL_BLOCKED_ACTIONS and any(
            t is self.focused for t in self._terminals
        ):
            return None
        return True

    def _tick_stats(self) -> None:
        # The two docker execs per host are slow (50-150ms each on Docker
        # Desktop) and may raise once a container dies; both must stay off
        # the event loop or the UI stutters and a dead container kills the
        # whole TUI within a second.
        if self._stats_busy:
            return
        self._stats_busy = True
        self.run_worker(
            self._sample_stats, thread=True, group="stats",
            exit_on_error=False,
        )

    def _sample_stats(self) -> None:
        from .stats_loop import StatsSampler
        try:
            if self._stats_sampler is None:
                self._stats_sampler = StatsSampler(
                    self.controller, [h.name for h in self.lab.hosts],
                )
            try:
                summaries = self._stats_sampler.sample()
                text = "\n".join(summaries.values())
            except Exception as exc:
                text = (
                    f"stats unavailable ({type(exc).__name__}): "
                    f"is a container down?"
                )
            self.call_from_thread(self.stats.update, text)
        finally:
            self._stats_busy = False

    # Keep a finished bar visible briefly before it disappears.
    _JOB_GRACE_S = 2.0

    def _start_job(self, label: str, total_s: float) -> None:
        self.jobs.append(_Job(label=label, start=time.time(), total=max(total_s, 0.0)))
        self._tick_progress()

    def _tick_progress(self) -> None:
        if not self.jobs:
            return
        now = time.time()
        self.jobs = [
            j for j in self.jobs if now - j.start < j.total + self._JOB_GRACE_S
        ]
        self.progress.render_jobs(self.jobs, now)

    def action_quit_app(self) -> None:
        # Teardown (docker compose down) is cmd_run's job after the TUI has
        # closed; doing it here would freeze the UI for seconds.
        for term in self._terminals:
            term.stop()
        self.exit()

    def action_help(self) -> None:
        self.push_screen(HelpModal())

    def action_edit_link(self) -> None:
        if not self.lab.links:
            return
        link = self.lab.links[0]

        def _after(result: dict | None) -> None:
            if result is None:
                return
            params = result["params"]
            exec_res = self.controller.apply_link_params(link.shaper_name, params)
            if exec_res.exit_code == 0:
                self.link_display[link.shaper_name] = result["display"]
                self._refresh_topology()
                self.log_view.append(
                    f"link {link.shaper_name} updated: "
                    f"bw={params.bandwidth_bps} delay_us={params.delay_us} "
                    f"jitter_us={params.jitter_us} loss={params.loss_frac}"
                )
            else:
                self.log_view.append(
                    f"link {link.shaper_name} update failed: {exec_res.output.strip()}"
                )

        self.push_screen(
            LinkParamsModal(link, current=self.link_display.get(link.shaper_name)),
            _after,
        )

    def action_edit_tcp_cong(self) -> None:
        def _after(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            host, algo = result
            exec_res = self.controller.set_tcp_cong(host, algo)
            if exec_res.exit_code == 0:
                self.host_cong[host] = algo
                self._refresh_topology()
                self.log_view.append(f"tcp cong {host} -> {algo}")
            else:
                self.log_view.append(
                    f"tcp cong {host} failed: {exec_res.output.strip()}"
                )

        self.push_screen(TcpCongModal(self.lab, current=self.host_cong), _after)

    @staticmethod
    def _wait_listen_cmd(proto: str, port: int) -> str:
        """POSIX-sh loop that waits (up to ~3s) until something listens on
        ``port``; starting the client against a not-yet-bound server would
        read as packet loss or connection refused in the results."""
        flag = "-lun" if proto == "udp" else "-ltn"
        return (
            f"i=0; while [ $i -lt 30 ]; do "
            f"ss -H {flag} 'sport = :{port}' 2>/dev/null | grep -q . && exit 0; "
            f"i=$((i+1)); sleep 0.1; done; exit 1"
        )

    def _log_from_worker(self, line: str) -> None:
        self.call_from_thread(self.log_view.append, line)

    def action_run_iperf3(self) -> None:
        def _after(args: dict | None) -> None:
            if args is None:
                return
            self.run_worker(
                lambda: self._launch_iperf3(args), thread=True,
                group="launch", exit_on_error=False,
            )

        self.push_screen(Iperf3Modal(self.lab), _after)

    def _launch_iperf3(self, args: dict) -> None:
        ts = int(time.time())
        server = args["server"]
        client = args["client"]
        srv_log = f"/out/iperf3-server-{ts}.log"
        cli_out = f"/out/iperf3-client-{ts}.json"
        # A stale server (e.g. from a run whose client never connected)
        # would hold port 5201 and swallow this run's connection.
        self.controller.exec_in_node(server, ["pkill", "-x", "iperf3"])
        self.controller.exec_in_node(client, ["pkill", "-x", "iperf3"])
        self.controller.exec_in_node(
            server,
            ["sh", "-c", f"nohup iperf3 -s -1 -p 5201 >{srv_log} 2>&1 &"],
        )
        ready = self.controller.exec_in_node(
            server, ["sh", "-c", self._wait_listen_cmd("tcp", 5201)],
        )
        if ready.exit_code != 0:
            self._log_from_worker(
                f"iperf3 server failed to start on {server} "
                f"(see out/iperf3-server-{ts}.log)"
            )
            return
        self._log_from_worker(
            f"iperf3 {client} -> {server} t={args['duration']} "
            f"-> out/iperf3-client-{ts}.json"
        )
        self.controller.exec_in_node(
            client,
            ["sh", "-c",
             f"nohup iperf3 -c {server} -t {args['duration']} "
             f"-i {args['interval']} -J > {cli_out} 2>&1 &"],
        )
        self.call_from_thread(
            self._start_job,
            f"iperf3 {client}->{server}", float(args["duration"]),
        )

    def _run_tool(self, tool: str) -> None:
        def _after(args: dict | None) -> None:
            if args is None:
                return
            self.run_worker(
                lambda: self._launch_tool(tool, args), thread=True,
                group="launch", exit_on_error=False,
            )

        self.push_screen(ToolModal(self.lab, tool), _after)

    def _launch_tool(self, tool: str, args: dict) -> None:
        ts = int(time.time())
        server = args["server"]
        client = args["client"]
        port = 9000 if tool == "udp" else 9001
        srv_log = f"/out/{tool}-server-{ts}.log"
        cli_log = f"/out/{tool}-client-{ts}.log"
        mode_arg = f"--mode {args['mode']} " if tool == "tcp" else ""
        srv_cmd = (
            f"nohup python3 /usr/local/bin/{tool}_server.py "
            f">{srv_log} 2>&1 &"
        )
        cli_cmd = (
            f"python3 /usr/local/bin/{tool}_client.py "
            f"--host {server} --port {port} "
            f"{mode_arg}"
            f"--count {args['count']} "
            f"--interval {args['interval']} "
            f"--size {args['size']} > {cli_log}"
        )
        # The servers run forever; without this, run 2's server dies with
        # EADDRINUSE and run 2's packets land in run 1's log file.
        self.controller.exec_in_node(server, ["pkill", "-f", f"{tool}_server.py"])
        self.controller.exec_in_node(client, ["pkill", "-f", f"{tool}_client.py"])
        self.controller.exec_in_node(server, ["sh", "-c", srv_cmd])
        ready = self.controller.exec_in_node(
            server, ["sh", "-c", self._wait_listen_cmd(tool, port)],
        )
        if ready.exit_code != 0:
            self._log_from_worker(
                f"{tool} server failed to start on {server} "
                f"(see out/{tool}-server-{ts}.log)"
            )
            return
        self._log_from_worker(
            f"{tool} {client} -> {server} count={args['count']} "
            f"-> out/{tool}-client-{ts}.log"
        )
        self.controller.exec_in_node(
            client, ["sh", "-c", f"nohup {cli_cmd} 2>&1 &"],
        )
        # count sends spaced by interval finish after (count-1) gaps.
        self.call_from_thread(
            self._start_job,
            f"{tool} {client}->{server}",
            max(args["count"] - 1, 0) * args["interval"],
        )

    def action_run_udp(self) -> None:
        self._run_tool("udp")

    def action_run_tcp(self) -> None:
        self._run_tool("tcp")

    def action_capture(self) -> None:
        # Captures run on the link's two endpoint hosts, not on the shaper:
        # netem drops packets before the egress capture tap, so a shaper-side
        # pcap can never show a drop. Endpoint pcaps make a drop visible as
        # "in the sender's capture, missing from the receiver's".
        if not self.lab.links:
            return
        if len(self.lab.links) == 1:
            self._toggle_capture(self.lab.links[0])
            return

        from .modals import LinkPickerModal

        def _after(shaper: str | None) -> None:
            if shaper is None:
                return
            link = next(
                (l for l in self.lab.links if l.shaper_name == shaper), None,
            )
            if link is not None:
                self._toggle_capture(link)

        self.push_screen(LinkPickerModal(self.lab), _after)

    def _toggle_capture(self, link) -> None:
        if self._capture_busy:
            return
        self._capture_busy = True
        if link.shaper_name in self.capturing:
            work = lambda: self._stop_capture(link)  # noqa: E731
        else:
            work = lambda: self._start_capture(link)  # noqa: E731
        self.run_worker(work, thread=True, group="capture", exit_on_error=False)

    @staticmethod
    def _capture_cmd(peer: str, out_path: str) -> str:
        """Start tcpdump on the interface that routes toward ``peer``: on a
        star hub every link has its own interface, so eth0 would be wrong."""
        return (
            f"peer_ip=$(getent hosts {peer} | awk '{{print $1}}'); "
            f"dev=$(ip -o route get \"$peer_ip\" 2>/dev/null "
            f"| sed -n 's/.*dev \\([^ ]*\\).*/\\1/p'); "
            f"nohup tcpdump -i \"${{dev:-eth0}}\" -U -w {out_path} "
            f">/dev/null 2>&1 &"
        )

    def _start_capture(self, link) -> None:
        try:
            ts = int(time.time())
            started: list[tuple[str, str]] = []
            for host, peer in ((link.from_, link.to), (link.to, link.from_)):
                path = f"/out/cap-{ts}-{host}.pcap"
                self.controller.exec_in_node(
                    host, ["sh", "-c", self._capture_cmd(peer, path)],
                )
                started.append((host, path))
            # The nohup wrapper exits 0 even when tcpdump dies instantly, so
            # confirm both processes are up before claiming success. The
            # ^tcpdump anchor keeps pgrep from matching its own sh wrapper.
            ok = True
            for host, path in started:
                check = self.controller.exec_in_node(
                    host,
                    ["sh", "-c",
                     f"sleep 0.3; pgrep -f '^tcpdump.*{path}' >/dev/null"],
                )
                ok = ok and check.exit_code == 0
            if not ok:
                for host, path in started:
                    self.controller.exec_in_node(
                        host,
                        ["sh", "-c", f"pkill -INT -f '^tcpdump.*{path}'; true"],
                    )
                self._log_from_worker(
                    f"capture failed to start on {link.from_}/{link.to}"
                )
                return

            def _apply() -> None:
                self.capturing[link.shaper_name] = started
                self._update_capture_indicator()
                names = " + ".join(p.split("/")[-1] for _, p in started)
                self.log_view.append(
                    f"capture started on {link.from_}/{link.to} -> out/: {names}"
                )

            self.call_from_thread(_apply)
        finally:
            self._capture_busy = False

    def _stop_capture(self, link) -> None:
        try:
            started = self.capturing.get(link.shaper_name, [])
            for host, path in started:
                # SIGINT lets tcpdump flush and close the pcap cleanly; the
                # file-name pattern spares any tcpdump a student runs in a
                # shell on the same host.
                self.controller.exec_in_node(
                    host,
                    ["sh", "-c", f"pkill -INT -f '^tcpdump.*{path}'; true"],
                )

            def _apply() -> None:
                self.capturing.pop(link.shaper_name, None)
                self._update_capture_indicator()
                names = " + ".join(p.split("/")[-1] for _, p in started) or "?"
                self.log_view.append(
                    f"capture stopped on {link.from_}/{link.to} -> out/: {names}"
                )

            self.call_from_thread(_apply)
        finally:
            self._capture_busy = False

    def _update_capture_indicator(self) -> None:
        # Persistent indicator in the header; the log line alone scrolls away.
        if not self.capturing:
            self.sub_title = ""
        elif len(self.capturing) == 1:
            (started,) = self.capturing.values()
            first = started[0][1].split("/")[-1]     # cap-<ts>-<host>.pcap
            base = first.rsplit("-", 1)[0]           # cap-<ts>
            self.sub_title = f"REC {base}-*.pcap"
        else:
            self.sub_title = f"REC {len(self.capturing)} links"

    def action_open_shell(self) -> None:
        # 's' always *adds* a shell on a host that doesn't have one yet.
        open_hosts = {t.host for t in self._terminals}
        available = [h.name for h in self.lab.hosts if h.name not in open_hosts]
        if not available:
            self.log_view.append("all hosts already have a shell")
            return

        from .modals import ShellModal

        def _apply(host):
            if host is None:
                return
            self._open_shell(host)

        self.push_screen(ShellModal(available), _apply)

    def _open_shell(self, host: str) -> None:
        container = f"{getattr(self.controller, 'project_name', 'cuil')}_{host}"
        pane = self.query_one("#shell-pane", Vertical)
        term = NodeTerminal(container, host=host)
        self._terminals.append(term)
        self._active_terminal = term
        pane.mount(term)
        self._relayout_shells()
        # Focus once the widget is actually mounted.
        self.call_after_refresh(self.set_focus, term)
        self.log_view.append(f"shell opened on {host} ({container})")

    def _relayout_shells(self) -> None:
        """Lay out the shell pane from the current shell count: stack up to
        three, switch to tabs beyond that."""
        pane = self.query_one("#shell-pane", Vertical)
        tabs = self.query_one("#shell-tabs", Static)
        if not self._terminals:
            pane.remove_class("open")
            pane.remove_class("tabbed")
            return
        pane.add_class("open")
        if not any(t is self._active_terminal for t in self._terminals):
            self._active_terminal = self._terminals[-1]
        pane.border_title = f"shell: {self._active_terminal.host}"
        if shell_layout_mode(len(self._terminals)) == "stacked":
            pane.remove_class("tabbed")
            for term in self._terminals:
                term.remove_class("hidden")
        else:
            pane.add_class("tabbed")
            for term in self._terminals:
                term.set_class(term is not self._active_terminal, "hidden")
            names = [t.host for t in self._terminals]
            active_idx = self._terminals.index(self._active_terminal)
            tabs.update(render_tab_bar(names, active_idx))

    def _close_terminal(self, term: NodeTerminal) -> None:
        term.stop()
        self._terminals = [t for t in self._terminals if t is not term]
        if not any(t is self._active_terminal for t in self._terminals):
            self._active_terminal = self._terminals[-1] if self._terminals else None
        term.remove()
        self._relayout_shells()
        self.set_focus(self._active_terminal if self._terminals else None)
        self.log_view.append(f"shell closed on {term.host}")

    def action_cycle_focus(self) -> None:
        # Cycle dashboard -> shell1 -> shell2 -> ... -> dashboard. Landing on a
        # shell makes it the active tab so the visible shell follows focus.
        if not self._terminals:
            return
        cycle: list[NodeTerminal | None] = [None, *self._terminals]
        current = next((t for t in self._terminals if t is self.focused), None)
        nxt = cycle[(cycle.index(current) + 1) % len(cycle)]
        if nxt is None:
            self.set_focus(None)
        else:
            self._active_terminal = nxt
            self._relayout_shells()
            self.set_focus(nxt)

    def action_close_shell(self) -> None:
        term = next((t for t in self._terminals if t is self.focused), None)
        if term is None:
            return
        self._close_terminal(term)

    def on_node_terminal_exited(self, message: NodeTerminal.Exited) -> None:
        # A shell process ended (e.g. the student typed `exit`); close just it.
        self._close_terminal(message.terminal)

    def action_reset(self) -> None:
        for link in self.lab.links:
            defaults = LinkParams(
                bandwidth_bps=link.bandwidth_bps,
                delay_us=link.delay_us,
                jitter_us=link.jitter_us,
                loss_frac=link.loss_frac,
                burst_bps=link.burst_bps,
            )
            self.controller.apply_link_params(link.shaper_name, defaults)
            self.link_display[link.shaper_name] = self._link_defaults(link)
        for host in self.lab.hosts:
            self.controller.set_tcp_cong(host.name, self.lab.tcp.congestion_control)
            self.host_cong[host.name] = self.lab.tcp.congestion_control
        self._refresh_topology()
        self.log_view.append("reset to lab.yaml defaults")
