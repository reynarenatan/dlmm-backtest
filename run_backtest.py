"""Three example scenarios.

A) Wide: the user's range covers every bin the price ever touched.
B) Concentrated: a fixed CONCENTRATED_BINS-wide window centered on the
   first candle's active bin; earns nothing while price is outside.
C) Concentrated with rebalancing: same as B, but when price leaves the range
   the position is closed and reopened centered on the current bin, paying
   REBALANCE_COST on the SOL traded in the conversion.
"""

import os

import matplotlib.pyplot as plt
import pandas as pd

from bin_math import get_bin_id_from_price, get_price_from_bin_id
from candle_bins import BIN_STEP, add_bins_to_dataframe, raw_to_ui, ui_to_raw
from config import BIN_TVL, CONCENTRATED_BINS, REBALANCE_COST, USER_DEPOSIT
from data_io import load_candles
from fees import accumulate_bin_fees
from inventory import run_inventory
from pnl import hodl_series, pnl_frame
from position import make_position, run_position
from strategies import run_strategy_c

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

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)
    days = len(df) / 1440

    total_bin_fees, per_candle_bin_fees = accumulate_bin_fees(df)
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

    # --- Scenario C: same window as B, recentred when price leaves it ------
    # Computed here so every chart below can show all three strategies; the
    # rebalance-by-rebalance report comes further down.
    # C's HODL baseline is the same initial tokens as B (identical start).
    # il is the price effect alone (costs added back and shown separately);
    # net pnl = fees + il - costs = fees + (value - hodl).
    c_frame, c_events = run_strategy_c(df, per_candle_bin_fees)
    hodl_c = hodl_series(pos_b, df["close"])
    cum_fees_c = c_frame["fee"].cumsum()
    cum_cost_c = c_frame["cost"].cumsum()
    net_c = cum_fees_c + c_frame["value"] - hodl_c
    il_c = c_frame["value"] - hodl_c + cum_cost_c
    total_c = cum_fees_c.iloc[-1]

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

    # --- Main chart: cumulative fees, all three scenarios ------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["timestamp"], cum_a, color="#2563eb", lw=1.8,
            label=f"A: wide ({hi - lo + 1} bins) — ${total_a:.2f}")
    ax.plot(df["timestamp"], cum_b, color="#ea580c", lw=1.8,
            label=f"B: concentrated ({CONCENTRATED_BINS} bins) — ${total_b:.2f}")
    ax.plot(df["timestamp"], cum_fees_c, color="#7c3aed", lw=1.8,
            label=f"C: rebalancing ({CONCENTRATED_BINS} bins, "
                  f"{len(c_events)} rebalances) — ${total_c:.2f}")
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

    # --- Full accounting: fees vs impermanent loss -------------------------
    # IL here is position value minus the value of just HOLDING the initial
    # tokens: an opportunity cost versus holding, not a direct loss.
    scenarios = [("A wide", pos_a, fees_a), ("B concentrated", pos_b, fees_b)]
    pnls, rows = {}, []
    print("\n=== fees vs impermanent loss (both in USD, vs HODL) ===")
    print(f"{'scenario':16s} {'fees':>9s} {'IL':>9s} {'net PnL':>9s}"
          f" {'net APY':>8s}")
    for name, pos, fees in scenarios:
        p = pnl_frame(df, pos, fees)
        pnls[name] = p
        fees_total = fees.sum()
        il_end = p["il"].iloc[-1]
        net = p["net_pnl"].iloc[-1]
        apy = net / days * 365 / USER_DEPOSIT
        rows.append((name, fees_total, il_end, net, apy))
        print(f"{name:16s} {fees_total:9.2f} {il_end:9.2f} {net:9.2f}"
              f" {apy:8.1%}")

    print("\nDid fees cover impermanent loss over this period?")
    for name, fees_total, il_end, net, apy in rows:
        verdict = "YES" if net > 0 else "NO"
        print(f"  {name}: {verdict} -- ${fees_total:.2f} of fees vs "
              f"${-il_end:.2f} given up versus just holding "
              f"-> net ${net:+.2f} ({apy:+.1%} APY)")

    # --- Full accounting chart: fees, IL, net PnL over time ----------------
    # C carries a third term, so its panel gets an extra costs line and the
    # net-PnL identity in its label picks up the "- costs".
    panels = [
        ("A wide", f"bins {pos_a.range_start}..{pos_a.range_end}",
         pnls["A wide"]["cum_fees"], pnls["A wide"]["il"],
         pnls["A wide"]["net_pnl"], None),
        ("B concentrated", f"bins {pos_b.range_start}..{pos_b.range_end}",
         pnls["B concentrated"]["cum_fees"], pnls["B concentrated"]["il"],
         pnls["B concentrated"]["net_pnl"], None),
        ("C rebalancing",
         f"{CONCENTRATED_BINS} bins, {len(c_events)} rebalances",
         cum_fees_c, il_c, net_c, cum_cost_c),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)
    for ax, (name, subtitle, cum_fees, il, net, costs) in zip(axes, panels):
        ax.axhline(0, color="#b3b3bd", lw=0.8)
        ax.plot(df["timestamp"], cum_fees, color="#2563eb", lw=1.6,
                label=f"cumulative fees (${cum_fees.iloc[-1]:+.2f})")
        ax.plot(df["timestamp"], il, color="#ea580c", lw=1.6,
                label=f"IL vs HODL (${il.iloc[-1]:+.2f})")
        formula = "fees + IL"
        if costs is not None:
            ax.plot(df["timestamp"], -costs, color="#71717a", lw=1.4,
                    label=f"rebalance costs (${-costs.iloc[-1]:+.2f})")
            formula = "fees + IL - costs"
        ax.plot(df["timestamp"], net, color="#111827", lw=2.0,
                label=f"net PnL = {formula} (${net.iloc[-1]:+.2f})")
        ax.set_title(f"{name}: {subtitle}",
                     fontsize=10, color="#3f3f46", loc="left")
        ax.set_ylabel("USD", color="#52525b")
        ax.legend(loc="lower left", fontsize=9, framealpha=0.9,
                  edgecolor="none")
        ax.tick_params(colors="#52525b", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.suptitle(f"Fees, impermanent loss and net PnL "
                 f"(${USER_DEPOSIT} over {days:.0f} days)",
                 fontsize=11, color="#3f3f46")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/net_pnl.png", dpi=150)
    print(f"\nchart saved to {OUTPUT_DIR}/net_pnl.png")

    # --- Strategy comparison: passive A, passive B, rebalancing C ----------
    # C starts identical to B; when a candle closes outside its range it
    # closes the position and reopens it centered on the current bin,
    # paying REBALANCE_COST on the SOL traded in the conversion.
    print(f"\n=== strategy C: rebalancing concentrated "
          f"({CONCENTRATED_BINS} bins, cost {REBALANCE_COST:.2%} of value "
          f"traded) ===")
    print(f"rebalances: {len(c_events)}")
    for e in c_events:
        ts = df["timestamp"].iloc[e["index"]]
        lo, hi = e["new_range"]
        print(f"  {ts:%Y-%m-%d %H:%M} close {e['close']:.4f}: "
              f"{e['direction']} {abs(e['sol_traded']):.4f} SOL "
              f"(${abs(e['sol_traded']) * e['close']:.2f} changed hands, "
              f"cost ${e['cost']:.4f}), new range {lo}..{hi}")

    table = [
        ("A wide", pnls["A wide"]["cum_fees"].iloc[-1],
         pnls["A wide"]["il"].iloc[-1], 0.0,
         pnls["A wide"]["net_pnl"].iloc[-1], 0),
        ("B concentrated", pnls["B concentrated"]["cum_fees"].iloc[-1],
         pnls["B concentrated"]["il"].iloc[-1], 0.0,
         pnls["B concentrated"]["net_pnl"].iloc[-1], 0),
        ("C rebalancing", cum_fees_c.iloc[-1], il_c.iloc[-1],
         cum_cost_c.iloc[-1], net_c.iloc[-1], len(c_events)),
    ]
    print(f"\n=== strategy comparison over {days:.0f} days "
          f"(all USD, IL vs HODL) ===")
    print(f"{'strategy':16s} {'fees':>8s} {'IL':>8s} {'costs':>7s}"
          f" {'net PnL':>8s} {'net APY':>8s} {'rebal':>6s}")
    for name, f_, il_, cost_, net_, n_ in table:
        apy = net_ / days * 365 / USER_DEPOSIT
        print(f"{name:16s} {f_:8.2f} {il_:8.2f} {cost_:7.2f}"
              f" {net_:8.2f} {apy:8.1%} {n_:6d}")

    # --- Sensitivity: does the verdict on C survive higher trading costs? --
    print("\nREBALANCE_COST sensitivity (strategy C):")
    for rate in (0.0, 0.001, 0.005):
        s_frame, s_events = run_strategy_c(df, per_candle_bin_fees,
                                           cost_rate=rate)
        s_net = (s_frame["fee"].cumsum()
                 + s_frame["value"] - hodl_c).iloc[-1]
        s_cost = s_frame["cost"].sum()
        print(f"  cost {rate:.2%}: net PnL ${s_net:+8.2f} "
              f"(total costs ${s_cost:.2f}, {len(s_events)} rebalances)")

    # --- Strategy chart: net PnL over time, all three ----------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axhline(0, color="#b3b3bd", lw=0.8)
    ax.plot(df["timestamp"], pnls["A wide"]["net_pnl"], color="#2563eb",
            lw=1.8, label=f"A wide (${pnls['A wide']['net_pnl'].iloc[-1]:+.2f})")
    ax.plot(df["timestamp"], pnls["B concentrated"]["net_pnl"],
            color="#ea580c", lw=1.8,
            label=f"B concentrated "
                  f"(${pnls['B concentrated']['net_pnl'].iloc[-1]:+.2f})")
    ax.plot(df["timestamp"], net_c, color="#7c3aed", lw=1.8,
            label=f"C rebalancing (${net_c.iloc[-1]:+.2f}, "
                  f"{len(c_events)} rebalance{'s' if len(c_events) != 1 else ''})")
    if c_events:
        idx = [e["index"] for e in c_events]
        ax.scatter(df["timestamp"].iloc[idx], net_c.iloc[idx], s=28,
                   color="#7c3aed", edgecolors="white", linewidths=1.2,
                   zorder=3, label="rebalance")
    ax.set_title(f"Net PnL by strategy (${USER_DEPOSIT} over {days:.0f} days)",
                 fontsize=11, color="#3f3f46")
    ax.set_ylabel("net PnL (USD)", color="#52525b")
    ax.tick_params(colors="#52525b", labelsize=9)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9, edgecolor="none")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/strategies.png", dpi=150)
    print(f"\nchart saved to {OUTPUT_DIR}/strategies.png")

    # --- Inventory chart: SOL held by each strategy ------------------------
    # A falling price converts USDC bins to SOL, so a passive position drifts
    # into SOL; C's rebalances reset the mix, so its line saw-tooths instead.
    inventories = [
        ("A wide", run_inventory(df, pos_a), "#2563eb"),
        ("B concentrated", run_inventory(df, pos_b), "#ea580c"),
        ("C rebalancing", c_frame, "#7c3aed"),
    ]

    end_close = df["close"].iloc[-1]
    print("\n=== SOL held (inventory, fees excluded) ===")
    print(f"{'strategy':16s} {'start':>10s} {'end':>10s} {'% SOL at end':>13s}")
    for name, frame, _ in inventories:
        sol = frame["sol_held"]
        pct_sol = sol.iloc[-1] * end_close / frame["value"].iloc[-1]
        print(f"{name:16s} {sol.iloc[0]:10.4f} {sol.iloc[-1]:10.4f}"
              f" {pct_sol:12.0%}")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax1.axhspan(band_lo, band_hi, color="#ea580c", alpha=0.12,
                label="B's price range")
    ax1.plot(df["timestamp"], df["close"], color="#52525b", lw=1.0)
    ax1.set_ylabel("price (USD)", color="#52525b")
    ax1.legend(loc="best", frameon=False, fontsize=9)
    ax1.set_title("SOL held by each strategy: price falling converts "
                  "USDC bins to SOL", fontsize=11, color="#3f3f46")
    for name, frame, color in inventories:
        ax2.plot(df["timestamp"], frame["sol_held"], color=color, lw=1.5,
                 label=name)
    if c_events:
        idx = [e["index"] for e in c_events]
        ax2.scatter(df["timestamp"].iloc[idx],
                    c_frame["sol_held"].iloc[idx], s=28, color="#7c3aed",
                    edgecolors="white", linewidths=1.2, zorder=3,
                    label="rebalance")
    ax2.set_ylabel("SOL held", color="#52525b")
    ax2.legend(loc="best", frameon=False, fontsize=9)
    for ax in (ax1, ax2):
        ax.tick_params(colors="#52525b", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/inventory_sol_held.png", dpi=150)
    print(f"\nchart saved to {OUTPUT_DIR}/inventory_sol_held.png")
