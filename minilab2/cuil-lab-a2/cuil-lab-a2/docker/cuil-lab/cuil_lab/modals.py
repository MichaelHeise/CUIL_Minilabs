"""Modal screens for the cuil-lab TUI: link params, TCP cong, iperf3, tools."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .schema import (
    Lab,
    Link,
    parse_duration_us,
    parse_loss_fraction,
    parse_rate_bits_per_sec,
)
from .shaping import LinkParams


HELP_TITLE = "cuil-lab, network shaping lab"

HELP_BODY = """\
Hosts talk through a shaper where Linux tc applies bandwidth,
delay, jitter and loss; change everything at runtime and watch
the dashboard update.

Keys
  l    edit link: bandwidth / delay / jitter / loss
  c    set a host's TCP congestion control
  i    run an iperf3 throughput test
  u/t  run the UDP / TCP message tools
  p    toggle a capture: one pcap per link endpoint
  s    open a split-view shell on a host (one per host)
  ^O   cycle focus dashboard <-> shells    ^W  close shell
  r    reset to lab.yaml    ?  this help    q  quit

Tool logs and pcaps (cap-<ts>-<host>.pcap) land in out/ next
to lab.yaml; a lost packet is in the sender's pcap only. Each
shell starts in /node (= nodes/<host>/ on your machine) for
your own scripts and logs. A focused shell grabs every key;
Ctrl-O returns to the dashboard. Details: README.md.

Press Esc or Enter to close."""


class HelpModal(ModalScreen):
    """Explanatory overlay shown on launch and via the '?' key."""

    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("enter", "close", "close"),
        Binding("q", "close", "close"),
        Binding("question_mark", "close", "close"),
    ]

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    HelpModal > VerticalScroll {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    HelpModal #help-title {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }
    HelpModal #help-buttons {
        height: auto;
        align-horizontal: center;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(HELP_TITLE, id="help-title", markup=False)
            yield Static(HELP_BODY, id="help-body", markup=False)
            with Horizontal(id="help-buttons"):
                yield Button("Close", id="close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class FormModal(ModalScreen):
    """Shared form-modal behavior: Esc cancels, Enter in an input submits,
    and validation problems show up in a visible error line instead of
    being silently swallowed."""

    BINDINGS = [Binding("escape", "cancel", "cancel")]

    DEFAULT_CSS = """
    FormModal Label#error {
        column-span: 2;
        width: 100%;
        height: auto;
        color: $error;
    }
    """

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        raise NotImplementedError

    def show_error(self, message: str) -> None:
        self.query_one("#error", Label).update(message)


class LinkParamsModal(FormModal):
    """Modal that lets the user edit a link's shaping parameters."""

    DEFAULT_CSS = """
    LinkParamsModal {
        align: center middle;
    }
    LinkParamsModal > Grid {
        grid-size: 2;
        grid-columns: 16 32;
        grid-rows: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
        width: 60;
        height: auto;
    }
    LinkParamsModal Input { width: 100%; }
    LinkParamsModal #buttons {
        column-span: 2;
        height: auto;
        align-horizontal: right;
    }
    LinkParamsModal Label#title {
        column-span: 2;
        content-align: center middle;
    }
    """

    def __init__(self, link: Link, current: dict[str, str] | None = None) -> None:
        super().__init__()
        self.link = link
        # Prefill with the currently applied values: Apply always writes all
        # five fields, so showing lab.yaml defaults here would silently
        # revert earlier changes.
        self.current = current or {}

    def _value(self, field: str, fallback: str) -> str:
        return str(self.current.get(field, fallback))

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(f"Link {self.link.from_} ── {self.link.to}", id="title")
            yield Label("bandwidth")
            yield Input(value=self._value("bandwidth", self.link.bandwidth),
                        id="bandwidth")
            yield Label("delay")
            yield Input(value=self._value("delay", self.link.delay), id="delay")
            yield Label("jitter")
            yield Input(value=self._value("jitter", self.link.jitter), id="jitter")
            yield Label("loss")
            yield Input(value=self._value("loss", str(self.link.loss)), id="loss")
            yield Label("burst")
            yield Input(value=self._value("burst", self.link.burst), id="burst")
            yield Label("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        bw = self.query_one("#bandwidth", Input).value
        delay = self.query_one("#delay", Input).value
        jitter = self.query_one("#jitter", Input).value
        loss = self.query_one("#loss", Input).value
        burst = self.query_one("#burst", Input).value
        try:
            params = LinkParams(
                bandwidth_bps=parse_rate_bits_per_sec(bw),
                delay_us=parse_duration_us(delay),
                jitter_us=parse_duration_us(jitter),
                loss_frac=parse_loss_fraction(loss),
                burst_bps=parse_rate_bits_per_sec(burst),
            )
        except (ValueError, KeyError) as exc:
            self.show_error(str(exc))
            return
        self.dismiss({
            "params": params,
            "display": {
                "bandwidth": bw,
                "delay": delay,
                "jitter": jitter,
                "loss": loss,
                "burst": burst,
            },
        })


class TcpCongModal(FormModal):
    """Modal that lets the user pick a TCP congestion control algorithm."""

    AVAILABLE_ALGOS = ["reno", "cubic"]

    DEFAULT_CSS = """
    TcpCongModal {
        align: center middle;
    }
    TcpCongModal > Grid {
        grid-size: 2;
        grid-columns: 16 32;
        grid-rows: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
        width: 60;
        height: auto;
    }
    TcpCongModal Select { width: 100%; }
    TcpCongModal #buttons {
        column-span: 2;
        height: auto;
        align-horizontal: right;
    }
    TcpCongModal Label#title {
        column-span: 2;
        content-align: center middle;
    }
    """

    def __init__(self, lab: Lab, current: dict[str, str] | None = None) -> None:
        super().__init__()
        self.lab = lab
        # host -> currently applied algorithm; the algo select follows the
        # picked host so the modal reflects reality instead of a hardcoded
        # default.
        self.current = current or {}

    def _algo_for(self, host: str) -> str:
        algo = self.current.get(host, self.lab.tcp.congestion_control)
        return algo if algo in self.AVAILABLE_ALGOS else self.AVAILABLE_ALGOS[0]

    def compose(self) -> ComposeResult:
        host_options = [(h.name, h.name) for h in self.lab.hosts]
        algo_options = [(a, a) for a in self.AVAILABLE_ALGOS]
        first = self.lab.hosts[0].name
        with Grid():
            yield Label("TCP congestion control", id="title")
            yield Label("host")
            yield Select(host_options, id="host", value=first, allow_blank=False)
            yield Label("algo")
            yield Select(algo_options, id="algo", value=self._algo_for(first),
                         allow_blank=False)
            yield Label("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Apply", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "host":
            self.query_one("#algo", Select).value = self._algo_for(event.value)

    def _submit(self) -> None:
        host = self.query_one("#host", Select).value
        algo = self.query_one("#algo", Select).value
        self.dismiss((host, algo))


class Iperf3Modal(FormModal):
    """Modal to launch an iperf3 server + client run."""

    DEFAULT_CSS = """
    Iperf3Modal {
        align: center middle;
    }
    Iperf3Modal > Grid {
        grid-size: 2;
        grid-columns: 16 32;
        grid-rows: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
        width: 60;
        height: auto;
    }
    Iperf3Modal Select, Iperf3Modal Input { width: 100%; }
    Iperf3Modal #buttons {
        column-span: 2;
        height: auto;
        align-horizontal: right;
    }
    Iperf3Modal Label#title {
        column-span: 2;
        content-align: center middle;
    }
    """

    def __init__(self, lab: Lab) -> None:
        super().__init__()
        self.lab = lab

    def compose(self) -> ComposeResult:
        hosts = [h.name for h in self.lab.hosts]
        host_options = [(h, h) for h in hosts]
        default_server = hosts[-1]
        default_client = hosts[0]
        with Grid():
            yield Label("iperf3", id="title")
            yield Label("server")
            yield Select(host_options, id="server", value=default_server, allow_blank=False)
            yield Label("client")
            yield Select(host_options, id="client", value=default_client, allow_blank=False)
            yield Label("duration (s)")
            yield Input(value="10", id="duration")
            yield Label("interval (s)")
            yield Input(value="1", id="interval")
            yield Label("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Run", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        try:
            duration = int(self.query_one("#duration", Input).value)
            interval = int(self.query_one("#interval", Input).value)
        except ValueError:
            self.show_error("duration and interval must be whole seconds")
            return
        server = self.query_one("#server", Select).value
        client = self.query_one("#client", Select).value
        if server == client:
            # A same-host run goes over loopback, bypassing the shaper, and
            # produces confusingly perfect numbers.
            self.show_error("server and client must differ")
            return
        self.dismiss({
            "server": server,
            "client": client,
            "duration": duration,
            "interval": interval,
        })


class ToolModal(FormModal):
    """Modal to launch a UDP or TCP test-tool run (custom client/server scripts)."""

    DEFAULT_CSS = """
    ToolModal {
        align: center middle;
    }
    ToolModal > Grid {
        grid-size: 2;
        grid-columns: 16 32;
        grid-rows: auto;
        padding: 1 2;
        border: round $primary;
        background: $surface;
        width: 60;
        height: auto;
    }
    ToolModal Select, ToolModal Input { width: 100%; }
    ToolModal #buttons {
        column-span: 2;
        height: auto;
        align-horizontal: right;
    }
    ToolModal Label#title {
        column-span: 2;
        content-align: center middle;
    }
    """

    def __init__(self, lab: Lab, tool: str) -> None:
        super().__init__()
        self.lab = lab
        self.tool = tool

    def compose(self) -> ComposeResult:
        hosts = [h.name for h in self.lab.hosts]
        host_options = [(h, h) for h in hosts]
        default_server = hosts[-1]
        default_client = hosts[0]
        with Grid():
            yield Label(f"{self.tool.upper()} tools", id="title")
            yield Label("server")
            yield Select(host_options, id="server", value=default_server, allow_blank=False)
            yield Label("client")
            yield Select(host_options, id="client", value=default_client, allow_blank=False)
            yield Label("count")
            yield Input(value="10", id="count")
            yield Label("interval (s)")
            yield Input(value="0.1", id="interval")
            yield Label("size (B)")
            yield Input(value="64", id="size")
            if self.tool == "tcp":
                yield Label("mode")
                yield Select(
                    [("persistent", "persistent"), ("reconnect", "reconnect")],
                    id="mode",
                    value="persistent",
                    allow_blank=False,
                )
            yield Label("", id="error")
            with Horizontal(id="buttons"):
                yield Button("Run", id="apply", variant="primary")
                yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        try:
            count = int(self.query_one("#count", Input).value)
            interval = float(self.query_one("#interval", Input).value)
            size = int(self.query_one("#size", Input).value)
        except ValueError:
            self.show_error("count/size must be integers, interval a number")
            return
        server = self.query_one("#server", Select).value
        client = self.query_one("#client", Select).value
        if server == client:
            self.show_error("server and client must differ")
            return
        result: dict[str, Any] = {
            "tool": self.tool,
            "server": server,
            "client": client,
            "count": count,
            "interval": interval,
            "size": size,
        }
        if self.tool == "tcp":
            result["mode"] = self.query_one("#mode", Select).value
        self.dismiss(result)


class LinkPickerModal(FormModal):
    """Pick which link to toggle a capture on (labs with several links)."""

    DEFAULT_CSS = """
    LinkPickerModal { align: center middle; }
    LinkPickerModal > Grid {
        grid-size: 2;
        grid-columns: 12 32;
        padding: 2;
        background: $panel;
        border: round $primary;
        width: 50;
        height: auto;
    }
    """

    def __init__(self, lab: Lab) -> None:
        super().__init__()
        self.lab = lab

    def compose(self) -> ComposeResult:
        options = [
            (f"{link.from_} ── {link.to}", link.shaper_name)
            for link in self.lab.links
        ]
        with Grid():
            yield Label("Capture on link")
            yield Select(
                options, id="link", allow_blank=False, value=options[0][1],
            )
            yield Button("Toggle", id="apply", variant="primary")
            yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        self.dismiss(str(self.query_one("#link", Select).value))


class ShellModal(FormModal):
    DEFAULT_CSS = """
    ShellModal { align: center middle; }
    ShellModal > Grid {
        grid-size: 2;
        grid-columns: 12 32;
        padding: 2;
        background: $panel;
        border: round $primary;
        width: 50;
        height: auto;
    }
    """

    def __init__(self, host_names: list[str]) -> None:
        super().__init__()
        self.host_names = host_names

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label("Open shell on")
            yield Select(
                [(n, n) for n in self.host_names],
                id="host", allow_blank=False, value=self.host_names[0],
            )
            yield Button("Open", id="apply", variant="primary")
            yield Button("Cancel", id="cancel")

    def _submit(self) -> None:
        self.dismiss(str(self.query_one("#host", Select).value))
