"""Parsers for lab files"""

import json
from pathlib import Path

import pandas as pd


def parse_iperf3_output(alg):
    data = json.loads(Path(f"iperf3_{alg}.json").read_text())
    intervals = [i["streams"][0] for i in data["intervals"]]
    return {
        "time": [i["end"] for i in intervals],
        "bitrate_bps": [i["bits_per_second"] for i in intervals],
    }


def parse_tcptrace_owin(alg):
    # color = state, dot x y = data
    # "red" = outstanding
    data = {"time": [], "outstanding": []}
    color = None
    for line in Path(f"analysis/{alg}-c2d_owin.xpl").read_text().splitlines():
        line = line.strip()
        if line in {"red", "yellow", "blue", "green"}:
            color = line
        elif color == "red" and line.startswith("dot "):
            _, time, value = line.split()
            data["time"].append(float(time))
            data["outstanding"].append(int(value))
    return data


def parse_retransmissions(alg):
    df = pd.read_csv(f"analysis/{alg}-retransmissions.csv")
    return {"time": df["tcp.time_relative"].tolist()}


def parse_packet_losses(alg):
    sender = pd.read_csv(f"analysis/{alg}-sender.csv")
    receiver = pd.read_csv(f"analysis/{alg}-receiver.csv")
    # A NOT IN B equivalent, so basically client_ids - server_ids
    lost = sender[~sender["ip.id"].isin(receiver["ip.id"])].sort_values(
        "tcp.time_relative"
    )
    return {"time": lost["tcp.time_relative"].tolist()}
