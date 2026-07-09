"""A minimal embedded terminal widget for cuil-lab.

The only off-the-shelf option (``textual-terminal``) is abandoned and breaks on
modern Textual, so we drive a PTY ourselves and emulate it with ``pyte``. The
pure seams (key->bytes, colour/style conversion, screen->strips) live up top and
are unit-tested without a real PTY; ``NodeTerminal`` wires them to a
``docker exec`` shell on the Textual event loop.

Emulation is pure-Python and therefore not fast enough for heavy full-screen
TUIs (vim, htop); the intended use is shells, loggers and ``ss``, where it is
fine.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import struct
import subprocess
import termios

import pyte
from rich.segment import Segment
from rich.style import Style
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

_HEX = set("0123456789abcdefABCDEF")

_SIMPLE_KEYS: dict[str, bytes] = {
    "enter": b"\r",
    "tab": b"\t",
    "escape": b"\x1b",
    "backspace": b"\x7f",
    "space": b" ",
}

_CSI_KEYS: dict[str, bytes] = {
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "delete": b"\x1b[3~",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
}


def key_event_to_bytes(key: str, character: str | None) -> bytes | None:
    """Translate a Textual key event into the bytes a PTY expects, or None when
    the key has no terminal meaning."""
    if key in _SIMPLE_KEYS:
        return _SIMPLE_KEYS[key]
    if key in _CSI_KEYS:
        return _CSI_KEYS[key]
    if key.startswith("ctrl+") and len(key) == len("ctrl+") + 1 and key[-1].isalpha():
        return bytes([ord(key[-1].lower()) - ord("a") + 1])
    if character:
        return character.encode("utf-8")
    return None


def pyte_color_to_rich(color: str) -> str | None:
    """Map a pyte colour ('default', a name, or a bare hex triplet) to a Rich
    colour string, or None for the terminal default."""
    if not color or color == "default":
        return None
    if len(color) == 6 and all(c in _HEX for c in color):
        return "#" + color
    return color


def char_to_style(char: pyte.screens.Char) -> Style:
    """Build a Rich Style from a pyte cell's attributes."""
    return Style(
        color=pyte_color_to_rich(char.fg),
        bgcolor=pyte_color_to_rich(char.bg),
        bold=bool(char.bold),
        italic=bool(char.italics),
        underline=bool(char.underscore),
        strike=bool(char.strikethrough),
        reverse=bool(char.reverse),
    )


def screen_to_strips(
    screen: pyte.Screen, cursor: tuple[int, int] | None = None
) -> list[Strip]:
    """Render a pyte screen to one Textual Strip per line.

    ``cursor`` (x, y), when given and on screen, is drawn as a reversed cell.
    Consecutive cells sharing a style are merged into a single Segment.
    """
    strips: list[Strip] = []
    for y in range(screen.lines):
        row = screen.buffer[y]
        segments: list[Segment] = []
        run_text: list[str] = []
        run_style: Style | None = None
        for x in range(screen.columns):
            char = row[x]
            style = char_to_style(char)
            if cursor is not None and cursor == (x, y):
                style += Style(reverse=True)
            data = char.data or " "
            if run_text and style == run_style:
                run_text.append(data)
            else:
                if run_text:
                    segments.append(Segment("".join(run_text), run_style))
                run_text = [data]
                run_style = style
        if run_text:
            segments.append(Segment("".join(run_text), run_style))
        strips.append(Strip(segments))
    return strips


def shell_layout_mode(n: int, limit: int = 2) -> str:
    """Pick the shell-pane layout for ``n`` open shells: 'stacked' while it fits
    within ``limit``, 'tabbed' once it grows past that.

    The limit is two: pyte emulation of three or more live shells side by side
    is too slow, so beyond two we show one shell at a time behind tabs."""
    return "stacked" if n <= limit else "tabbed"


def render_tab_bar(names: list[str], active_idx: int) -> str:
    """Render the tab bar text for the tabbed shell layout, bracketing the
    active host (e.g. ``n1  [n2]  n3``)."""
    return "  ".join(
        f"[{name}]" if i == active_idx else name
        for i, name in enumerate(names)
    )


def visible_pty_size(width: int, height: int) -> tuple[int, int] | None:
    """Return the (cols, rows) to size the PTY to, or None when the widget is
    hidden (zero in either dimension, e.g. a shell behind a tab).

    Resizing a hidden terminal to a 1x1 PTY would wipe its pyte buffer and
    force the shell to reflow, so a hidden terminal must keep its last size."""
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def shell_argv(container: str) -> list[str]:
    """The docker command that opens an interactive shell in the student's
    /node workspace (falling back to $HOME if the mount is absent).

    Prints /etc/motd first: docker exec shells are not login shells, so the
    image's tool overview would otherwise never reach students."""
    return [
        "docker", "exec", "-it", container,
        "sh", "-c",
        "cat /etc/motd 2>/dev/null; cd /node 2>/dev/null; exec sh",
    ]


class NodeTerminal(Widget, can_focus=True):
    """A PTY-backed shell into a container, emulated with pyte."""

    DEFAULT_CSS = """
    NodeTerminal {
        height: 1fr;
        width: 1fr;
        background: $surface;
        /* A dim titled border delineates and labels each shell, so stacked
           shells read as separate boxes rather than one run-together area. */
        border: round $panel-lighten-2;
    }
    """

    class Exited(Message):
        """Posted when the shell process ends (e.g. the student types exit)."""

        def __init__(self, terminal: "NodeTerminal") -> None:
            self.terminal = terminal
            super().__init__()

    def __init__(
        self,
        container: str,
        *,
        host: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> None:
        super().__init__()
        self.container = container
        # The lab host this shell belongs to; used for dedupe and tab labels.
        self.host = host if host is not None else container
        self.border_title = self.host
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.ByteStream(self._screen)
        self._strips: list[Strip] = screen_to_strips(self._screen)
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def on_mount(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._start()

    def _start(self) -> None:
        master, slave = pty.openpty()
        self._master_fd = master
        self._proc = subprocess.Popen(
            shell_argv(self.container),
            stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, close_fds=True,
        )
        os.close(slave)
        assert self._loop is not None
        self._loop.add_reader(master, self._on_readable)
        self._resize_pty()

    def _on_readable(self) -> None:
        assert self._master_fd is not None
        try:
            data = os.read(self._master_fd, 65536)
        except OSError:
            data = b""
        if not data:
            self.stop()
            self.post_message(self.Exited(self))
            return
        self._stream.feed(data)
        self._refresh_strips()

    def _refresh_strips(self) -> None:
        cursor = None
        if not self._screen.cursor.hidden:
            cursor = (self._screen.cursor.x, self._screen.cursor.y)
        self._strips = screen_to_strips(self._screen, cursor)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.content_size.width
        if 0 <= y < len(self._strips):
            return self._strips[y].adjust_cell_length(width)
        return Strip.blank(width)

    def on_resize(self) -> None:
        self._resize_pty()

    def _resize_pty(self) -> None:
        if self._master_fd is None:
            return
        dims = visible_pty_size(self.content_size.width, self.content_size.height)
        if dims is None:
            # Hidden behind a tab: keep the buffer, don't shrink to 1x1.
            return
        cols, rows = dims
        self._screen.resize(rows, cols)
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass
        self._refresh_strips()

    async def on_key(self, event) -> None:
        data = key_event_to_bytes(event.key, event.character)
        if data is None or self._master_fd is None:
            return
        event.stop()
        event.prevent_default()
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass

    async def on_paste(self, event) -> None:
        # Textual delivers pasted text as a single Paste event, not as a run of
        # key presses, so without this handler paste into a shell is silently
        # dropped. Forward the text to the PTY exactly as if it had been typed.
        if self._master_fd is None:
            return
        event.stop()
        try:
            os.write(self._master_fd, event.text.encode("utf-8"))
        except OSError:
            pass

    def stop(self) -> None:
        """Detach the reader, close the PTY, and terminate the shell."""
        if self._master_fd is not None and self._loop is not None:
            try:
                self._loop.remove_reader(self._master_fd)
            except (ValueError, OSError):
                pass
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
            # Reap the docker exec client; without a wait() it lingers as a
            # zombie until CPython's lazy subprocess cleanup runs.
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)
        self._proc = None

    def on_unmount(self) -> None:
        self.stop()
