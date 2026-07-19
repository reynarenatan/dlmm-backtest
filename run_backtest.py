"""Two example scenarios.

A) Wide: the user's range covers every bin the price ever touched.
B) Concentrated: a fixed CONCENTRATED_BINS-wide window centered on the
   first candle's active bin; earns nothing while price is outside.
Same USER_DEPOSIT in both -> an apples-to-apples range-width comparison.
"""

import os

import matplotlib.pyplot as plt
import pandas as pd

from bin_math import get_bin_id_from_price, get_price_from_bin_id
from candle_bins import BIN_STEP, add_bins_to_dataframe, raw_to_ui, ui_to_raw
from config import BIN_TVL, CONCENTRATED_BINS, USER_DEPOSIT
from fees import accumulate_bin_fees
from position import make_position, run_position

OUTPUT_DIR = "outputs"


def describe(name, position, user_fees, days):
    total = user_fees.sum()
    per_day = total / days
    apy = per_day * 365 / USER_DEPOSIT  # simple APY (no compounding)
    pct_earning = (user_fees > 0).mean() * 100
    lo_ui = raw_to_ui(get_price_from_bin_id(position.range_start, BIN_STEP))
    hi_ui = raw_to_ui(get_price_from_bin_id(position.range_end + 1, BIN_STEP))
    print(f"\n--- {name} ---")
    print(f"range: bins {position.range_start}..{position.range_end} "
          f"({position.range_end - position.range_start + 1} bins, "
          f"UI ${lo_ui:.2f}-{hi_ui:.2f})")
    print(f"total fees earned: ${total:.2f}")
    print(f"fee per day:       ${per_day:.4f}")
    print(f"simple APY:        {apy:.1%}")
    print(f"candles earning:   {pct_earning:.1f}%")
    return total


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = pd.read_csv("data/sol_1m.csv", parse_dates=["timestamp"])
    df = add_bins_to_dataframe(df, BIN_STEP)
    days = len(df) / 1440

    total_bin_fees, _ = accumulate_bin_fees(df)
    total_pool_fees = sum(total_bin_fees.values())

    # --- Scenario A: wide, computed from the data --------------------------
    lo, hi = min(total_bin_fees), max(total_bin_fees)
    pos_a = make_position(USER_DEPOSIT, lo, hi)
    fees_a = run_position(df, pos_a)
    total_a = describe("Scenario A: wide (every touched bin)", pos_a, fees_a, days)

    # --- Scenario B: concentrated around the first candle's active bin -----
    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), BIN_STEP)
    half = CONCENTRATED_BINS // 2
    pos_b = make_position(USER_DEPOSIT, center - half, center + half)
    fees_b = run_position(df, pos_b)
    total_b = describe(
        f"Scenario B: concentrated ({CONCENTRATED_BINS} bins on start bin "
        f"{center})", pos_b, fees_b, days)

    cum_a = fees_a.cumsum()
    cum_b = fees_b.cumsum()

    # --- Verify 1: A monotone, final value = analytic expected total -------
    assert (fees_a >= 0).all()  # per-candle fees never negative => cum non-decreasing
    assert (cum_a.diff().dropna() >= 0).all()
    expected_a = pos_a.deposit_per_bin / BIN_TVL * total_pool_fees
    assert abs(cum_a.iloc[-1] - expected_a) < 1e-6
    print(f"\nverify 1 OK: A monotone, final ${cum_a.iloc[-1]:.4f} "
          f"= analytic total ${expected_a:.4f}")

    # --- Verify 2: B flat exactly when price is outside the range ----------
    in_range = df["touched_bins"].map(
        lambda bins: any(pos_b.range_start <= b <= pos_b.range_end for b in bins)
    )
    assert ((fees_b > 0) == in_range).all()
    print(f"verify 2 OK: B earns > 0 on exactly the {in_range.sum()} candles "
          "whose candle touched the range")

    # --- Main chart: cumulative fees, both scenarios -----------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["timestamp"], cum_a, color="#2563eb", lw=1.8,
            label=f"A: wide ({hi - lo + 1} bins) — ${total_a:.2f}")
    ax.plot(df["timestamp"], cum_b, color="#ea580c", lw=1.8,
            label=f"B: concentrated ({CONCENTRATED_BINS} bins) — ${total_b:.2f}")
    ax.set_title(f"Cumulative user fees on ${USER_DEPOSIT} over {days:.0f} days",
                 fontsize=11, color="#3f3f46")
    ax.set_ylabel("cumulative fees (USD)", color="#52525b")
    ax.tick_params(colors="#52525b", labelsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/cumulative_fees.png", dpi=150)
    print(f"\nchart saved to {OUTPUT_DIR}/cumulative_fees.png")

    # --- Verify 2 zoom: longest flat segment + the price excursion ---------
    out = ~in_range
    run_id = (out != out.shift()).cumsum()
    flat_runs = out.groupby(run_id).agg(["all", "size"])
    longest = flat_runs[flat_runs["all"]]["size"].idxmax()
    seg = df.index[run_id == longest]
    pad = 360  # 6 hours of context on each side
    zoom = df.iloc[max(seg[0] - pad, 0):min(seg[-1] + pad, len(df) - 1)]

    band_lo = raw_to_ui(get_price_from_bin_id(pos_b.range_start, BIN_STEP))
    band_hi = raw_to_ui(get_price_from_bin_id(pos_b.range_end + 1, BIN_STEP))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax1.axhspan(band_lo, band_hi, color="#ea580c", alpha=0.12,
                label="B's price range")
    ax1.plot(zoom["timestamp"], zoom["close"], color="#2563eb", lw=1.5)
    ax1.set_ylabel("price (USD)", color="#52525b")
    ax1.legend(loc="best", frameon=False, fontsize=9)
    ax1.set_title(
        f"Longest flat segment of B ({len(seg)} min starting "
        f"{df['timestamp'].iloc[seg[0]]:%Y-%m-%d %H:%M} UTC): "
        "price left the range, fees stopped",
        fontsize=11, color="#3f3f46")
    ax2.plot(zoom["timestamp"], cum_b.loc[zoom.index], color="#ea580c", lw=1.8)
    ax2.set_ylabel("B cumulative fees (USD)", color="#52525b")
    for ax in (ax1, ax2):
        ax.tick_params(colors="#52525b", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/flat_segment_zoom.png", dpi=150)
    print(f"zoom chart saved to {OUTPUT_DIR}/flat_segment_zoom.png")

    # --- Plain-text summary ------------------------------------------------
    winner = "A (wide)" if total_a > total_b else "B (concentrated)"
    print(f"\n=== SUMMARY ===")
    print(f"Scenario A (wide):         ${total_a:.2f}")
    print(f"Scenario B (concentrated): ${total_b:.2f}")
    print(f"{winner} earned more. B holds a larger share of each bin "
          f"({pos_b.deposit_per_bin / BIN_TVL:.3%} vs "
          f"{pos_a.deposit_per_bin / BIN_TVL:.3%}) but earned nothing on the "
          f"{(~in_range).mean():.0%} of candles where price was outside its "
          "window; A earned on every candle.")
