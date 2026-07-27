"""Plots for visualization and analysis"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import EngFormatter

ALGS = (
    ("reno", "Reno", "C0"),
    ("cubic", "CUBIC", "C1"),
)

LOSS_COLORS = {"reno": "C3", "cubic": "C4"}


def save_plot(name, title, ylabel, unit=None):
    plt.title(title)
    plt.xlabel("Zeit in s")
    plt.ylabel(ylabel)
    # Convert to readable format
    if unit:
        plt.gca().yaxis.set_major_formatter(EngFormatter(unit=unit))
    plt.legend()
    plt.tight_layout()
    plt.savefig(f"analysis/{name}.pdf")
    plt.close()


def plot_throughput_comparison(data):
    for alg, label, color in ALGS:
        plt.plot(
            data[alg]["time"],
            data[alg]["bitrate_bps"],
            color=color,
            label=f"TCP {label}",
        )
    save_plot("throughput-comparison", "Durchsatz", "Durchsatz", "bit/s")


def plot_cwnd_comparison(windows):
    for alg, label, color in ALGS:
        w = windows[alg]
        plt.plot(
            w["time"],
            w["outstanding"],
            color=color,
            linewidth=0.5,  # default too thick
            label=f"TCP {label}",
        )
    save_plot("cwnd-comparison", "Staukontrollfenster", "Outstanding Data", "B")


def plot_cwnd_with_losses(alg, label, color, window, losses):
    plt.plot(
        window["time"],
        window["outstanding"],
        zorder=2,
        color=color,
        linewidth=0.5,  # default is too thick
        label=f"TCP {label} cwnd",
    )
    # interpolate cwnd at each loss for correct y
    loss_y = np.interp(losses["time"], window["time"], window["outstanding"])
    plt.scatter(
        losses["time"],
        loss_y,
        marker="x",
        s=22,  # default is too big
        color=LOSS_COLORS[alg],
        zorder=3,
        label=f"Paketverluste (n={len(losses['time'])})",
    )
    save_plot(
        f"cwnd-losses-{alg}",
        f"cwnd und Paketverluste: TCP {label}",
        "Outstanding Data",
        "B",
    )


def plot_retransmission_comparison(data):
    for alg, label, color in ALGS:
        # prepend 0 so step function starts at y=0
        time = [0, *data[alg]["time"]]
        plt.step(
            time,
            range(len(time)),
            where="post",
            label=f"TCP {label} (n={len(data[alg]['time'])})",
        )
    save_plot("retransmissions-comparison", "Kumulierte Retransmissionen", "Anzahl")
