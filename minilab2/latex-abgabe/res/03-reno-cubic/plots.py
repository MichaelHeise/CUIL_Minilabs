"""Plots for visualization and analysis"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import EngFormatter
from scipy.signal import find_peaks
from scipy.stats import binned_statistic
from lmfit import Model
from sklearn.metrics import r2_score

ALGS = (
    ("reno", "Reno", "C0"),
    ("cubic", "CUBIC", "C1"),
)

ALG_COLORS = {"reno": "C3", "cubic": "C4"}
FIT_COLORS = {"ss": "C2", "ca": "C5"}
CA_FITS = {"linear": (1, "Linear"), "kubisch": (3, "Kubisch")}


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
        color=ALG_COLORS[alg],
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


def resample(t_raw, y_raw):
    y_out, boundaries, _ = binned_statistic(
        t_raw,
        y_raw,
        statistic="max",
        bins=np.arange(
            t_raw[0], t_raw[-1] + 0.085, 0.085
        ),  # 0.085 is roughly mean of RTT in reno and CUBIC, should suffice for removing noise
    )
    valid = ~np.isnan(y_out)
    return (boundaries[:-1] + boundaries[1:])[valid] / 2, y_out[valid]


def fit_ss(ax, t_resamp, y_resamp, first_loss):
    ss_range = t_resamp < first_loss  # select only points before first loss
    # need this for filtering out reno specific first part
    if np.count_nonzero(ss_range) < 3:
        return
    fit = Model(lambda x, a, r: a * np.exp(r * x)).fit(  # Exp model fit
        y_resamp[ss_range], x=t_resamp[ss_range], a=float(y_resamp[ss_range][0]), r=1.0
    )
    t2 = np.log(2) / fit.params["r"].value * 1000
    t_smoothened = np.linspace(t_resamp[ss_range][0], t_resamp[ss_range][-1], 100)
    ax.plot(
        t_smoothened,
        fit.eval(x=t_smoothened),
        color=FIT_COLORS["ss"],
        linewidth=2,
        linestyle="dashed",
        label=f"Exp. Fit (SS, R2={fit.rsquared}, T2≈{t2}ms)",
    )


# find_peaks() can only measure additive drops so we need log to transform
# multiplicative drops to additive ones: log(1/0.7) = 0.36, log(1/0.5)≈0.69
# prominence=0.22 catches both Reno and CUBIC drops in log sopace
def detect_regimes(t_resamp, y_resamp, min_pts):
    trenches, _ = find_peaks(-np.log(y_resamp), prominence=0.22, distance=min_pts)
    starts = trenches
    ends = list(trenches[1:]) + [len(y_resamp)]
    return [
        (t_resamp[a:b], y_resamp[a:b])
        for a, b in list(zip(starts, ends))
        if b - a >= min_pts
    ]


def fit_ca(ax, t_resamp, y_resamp, ca_key):
    ca_deg, ca_name = CA_FITS[ca_key]
    regimes = detect_regimes(
        t_resamp, y_resamp, ca_deg + 1
    )  # fits need always degree + 1 points
    r2_vals = []
    for t_grow, y_grow in regimes:  # fit over all regimes
        coeffs = np.polyfit(t_grow, y_grow, ca_deg)
        t_smooth = np.linspace(t_grow[0], t_grow[-1], 100)
        ax.plot(
            t_smooth,
            np.polyval(coeffs, t_smooth),
            color=FIT_COLORS["ca"],
            linestyle="dashed",
            linewidth=1,
        )
        r2_vals.append(r2_score(y_grow, np.polyval(coeffs, t_grow)))

    r2_mean = np.mean(r2_vals) if r2_vals else 0
    ax.plot(  # legend only
        [],
        [],
        color=FIT_COLORS["ca"],
        linewidth=1,
        linestyle="dashed",
        label=f"{ca_name} Fit (CA, R2={r2_mean}, n={len(r2_vals)} Regime)",
    )


def plot_phase_fitting(windows, losses):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for idx, (alg, label, _, ca_key) in enumerate(
        [
            ("reno", "Reno", "C0", "linear"),
            ("cubic", "CUBIC", "C1", "kubisch"),
        ]
    ):
        ax = axes[idx]
        t_raw, y_raw = np.array(windows[alg]["time"]), np.array(
            windows[alg]["outstanding"]
        )
        t_resamp, y_resamp = resample(t_raw, y_raw)

        ax.plot(
            t_resamp,
            y_resamp,
            color=ALG_COLORS[alg],
            linewidth=1,
            alpha=0.5,
            label=f"TCP {label} cwnd",
        )
        loss_times = sorted(losses[alg]["time"])
        fit_ss(ax, t_resamp, y_resamp, loss_times[0])
        fit_ca(ax, t_resamp, y_resamp, ca_key)

        ax.set(xlabel="Zeit [s]", ylabel="cwnd (Outstanding)", title=f"TCP {label}")
        ax.yaxis.set_major_formatter(EngFormatter(unit="B"))
        ax.legend(loc="upper right", fontsize=7)

    plt.tight_layout()
    fig.savefig("analysis/phase-fitting.pdf", bbox_inches="tight")
    plt.close()
