"""LAB 2 - Task 3 Reproducible Script

Inputs are the PCAPs and iperf3 JSON files.
"""

from parsers import (
    parse_iperf3_output,
    parse_packet_losses,
    parse_retransmissions,
    parse_tcptrace_owin,
)
from plots import (
    ALGS,
    plot_cwnd_comparison,
    plot_cwnd_with_losses,
    plot_phase_fitting,
    plot_retransmission_comparison,
    plot_throughput_comparison,
)


def main():
    alg_ids = [alg for alg, _, _ in ALGS]
    iperf = {alg: parse_iperf3_output(alg) for alg in alg_ids}
    windows = {alg: parse_tcptrace_owin(alg) for alg in alg_ids}
    retransmissions = {alg: parse_retransmissions(alg) for alg in alg_ids}
    losses = {alg: parse_packet_losses(alg) for alg in alg_ids}

    plot_throughput_comparison(iperf)
    plot_cwnd_comparison(windows)
    for alg, label, color in ALGS:
        plot_cwnd_with_losses(alg, label, color, windows[alg], losses[alg])
    plot_retransmission_comparison(retransmissions)
    plot_phase_fitting(windows, losses)


if __name__ == "__main__":
    main()
