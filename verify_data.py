"""Sanity-check a fetched candle file: does the price path look real?

An API can return a full year of rows and still be degraded for older ranges —
interpolated, forward-filled, or stitched from a coarser interval. Three checks
catch that:

1. Daily closes plotted over the whole span, to eyeball against known history.
2. Min / max / mean price per month, to spot ranges that are implausibly tight.
3. Candles where open == high == low == close ("flat" candles). A real 1-minute
   SOL candle almost never has zero range, so a month full of them means the
   data was padded rather than observed.

Usage:  python verify_data.py [path-to-csv]
"""

import sys

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_FILE = "data/sol_1m_1y.csv"
CHART_FILE = "data/sol_1y_daily.png"


def load(path):
    df = pd.read_csv(path, parse_dates=["timestamp"])
    # to_period() drops the tz anyway; convert explicitly to silence the warning.
    df["month"] = df["timestamp"].dt.tz_convert(None).dt.to_period("M")
    return df


def monthly_stats(df):
    """Min / max / mean close per month, plus flat-candle counts."""
    flat = (
        (df["open"] == df["high"])
        & (df["high"] == df["low"])
        & (df["low"] == df["close"])
    )
    stats = df.groupby("month")["close"].agg(["min", "max", "mean", "size"])
    stats["flat"] = flat.groupby(df["month"]).sum()
    stats["flat_pct"] = stats["flat"] / stats["size"] * 100
    return stats


def print_stats(stats):
    print(f"{'month':<9}{'candles':>9}{'min':>10}{'max':>10}{'mean':>10}"
          f"{'flat':>8}{'flat %':>9}")
    for month, r in stats.iterrows():
        print(f"{str(month):<9}{int(r['size']):>9}{r['min']:>10.2f}"
              f"{r['max']:>10.2f}{r['mean']:>10.2f}{int(r['flat']):>8}"
              f"{r['flat_pct']:>8.2f}%")

    print(f"\ntotal flat candles: {int(stats['flat'].sum())} "
          f"({stats['flat'].sum() / stats['size'].sum() * 100:.3f}% of all rows)")


def plot_daily_closes(df):
    """Last close of each UTC day."""
    daily = df.set_index("timestamp")["close"].resample("D").last().dropna()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(daily.index, daily.values, color="#2563eb", lw=1.8)
    ax.set_title(
        f"SOL daily close, {daily.index[0]:%Y-%m-%d} to {daily.index[-1]:%Y-%m-%d} "
        f"(from 1-minute candles)",
        fontsize=11, color="#3f3f46")
    ax.set_ylabel("price (USD)", color="#52525b")
    ax.tick_params(colors="#52525b", labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#e4e4e7", lw=0.8)
    ax.set_axisbelow(True)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(CHART_FILE, dpi=150)
    return daily


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    df = load(path)
    print(f"{path}: {len(df)} rows, "
          f"{df['timestamp'].iloc[0]} .. {df['timestamp'].iloc[-1]}\n")

    print_stats(monthly_stats(df))

    daily = plot_daily_closes(df)
    print(f"\nchart saved to {CHART_FILE} ({len(daily)} daily closes)")
