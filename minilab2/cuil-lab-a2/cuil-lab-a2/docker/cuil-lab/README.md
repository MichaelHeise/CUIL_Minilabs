# cuil-lab

Terminal lab dashboard for *Computernetze und ihre Leistung* Assignment 2.

## Install

Requires Docker Desktop and Python 3.11+.

```
pip install -e .
```

## Use

```
cuil-lab build           # one-time: build cuil/host and cuil/shaper images
cuil-lab run             # opens the TUI, reads ./lab.yaml
```

The `lab.yaml` starting values (bandwidth, delay, jitter, loss, burst, TCP
congestion control) are applied to the wire at startup. Loss accepts `3%` or a
bare number meaning percent (`loss: 3` is 3%). Bandwidth is always enforced,
also at high rates like `100mbit`.

Keybindings (also shown in the footer; single letters are disabled while a
shell has focus):

| Key | Action |
| --- | --- |
| `l` | Edit link parameters (Apply writes all five fields) |
| `c` | Change TCP congestion control on a host |
| `i` | Run an iperf3 test |
| `u` | Run the UDP tools |
| `t` | Run the TCP tools |
| `p` | Toggle a packet capture: one pcap per endpoint host of a link (REC indicator in the header; labs with several links get a link picker) |
| `s` | Open a split-view shell on a host (one per host) |
| `Ctrl-O` | Cycle focus: dashboard → each open shell → back |
| `Ctrl-W` | Close the focused shell |
| `r` | Reset to `lab.yaml` defaults |
| `?` | Show the help overlay |
| `q` | Quit (Textual's built-in `Ctrl-Q` also works) |

In the modals, `Esc` cancels and `Enter` applies.

`u`/`t`/`i` write both ends' output to `out/` next to `lab.yaml`
(`udp-server-<ts>.log`, `udp-client-<ts>.log`, `iperf3-client-<ts>.json`, ...),
and captures land there as `cap-<ts>-<host>.pcap`, one per endpoint of the
captured link, each taken on the interface facing that link. Capturing at the
endpoints (not on the shaper) is what makes drops visible: netem discards
packets before the shaper's egress capture tap, so a packet lost on the link
appears in the sender's pcap and is missing from the receiver's. Re-running a
tool first stops the previous run's server, so each log pair belongs to
exactly one run.

If a session was killed hard (closed terminal) and leftover containers
misbehave on the next start, run `./run-lab.sh --clean`.

## Logging your own data

The split-view shell (`s`) keeps the dashboard, including live rate/cwnd/srtt
stats, visible next to an interactive shell, so you can run a logger and watch
the link at the same time. Press `s` once per host to open several shells at
once, each shown as a box labelled with its host: up to two stack on top of
each other, and a third switches the pane to a tabbed layout. `Ctrl-O` cycles
focus through the dashboard and each open shell (in tabbed mode the focused
shell becomes the visible tab); `Ctrl-W` closes the focused shell, and typing
`exit` closes it too. Whichever side holds keyboard focus shows a highlighted
border (`lab` for the dashboard, the host name for a shell).

Each host has a private workspace at `/node`, bind-mounted from `nodes/<host>/`
beside `lab.yaml`; shells start there:

- drop a script into `nodes/n1/` on the host and it appears at `/node` in `n1`;
- write your logs to `/node` and read them back from `nodes/n1/` on the host.

No logger ships with the lab; write your own. For the congestion window in MSS
segments, sample `ss -tin` (the `cwnd:` field is already in segments). While a
shell has focus it captures every key; press `Ctrl-O` to return focus to the
dashboard and reach the single-letter actions again.
