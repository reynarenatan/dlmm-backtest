"""Two strategies over the same candle data.

passive:     a POSITION_BINS-wide range set on the first candle and never
             touched. A baseline only -- it exists so we can say whether
             rebalancing helped.
rebalancing: the same width, but whenever a candle closes outside the
             range the position is closed and reopened centered on the
             current bin, paying REBALANCE_COST on the SOL traded.

The old wide scenario (one position covering every bin the price ever
touched) is gone. Its range could only be chosen after seeing the whole
price path, so it was lookahead rather than a strategy anyone could run,
and spanning thousands of bins was what made a full-year run take
45 minutes.
"""

import os

import matplotlib.pyplot as plt

from bin_math import get_bin_id_from_price, get_price_from_bin_id
from candle_bins import BIN_STEP, add_bins_to_dataframe, raw_to_ui, ui_to_raw
from config import BIN_TVL, POSITION_BINS, REBALANCE_COST, USER_DEPOSIT
from data_io import load_candles
from fees import accumulate_bin_fees
from inventory import run_inventory
from pnl import hodl_series, pnl_frame
from position import make_position, run_position
from strategies import run_rebalancing

OUTPUT_DIR = "outputs"

PASSIVE_COLOR = "#ea580c"
REBAL_COLOR = "#7c3aed"

# Past this many rebalances the per-event markers bury the line they are
# meant to annotate, so the count in the legend has to carry the story.
MAX_MARKERS = 50


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


def mark_rebalances(ax, df, events, y_series, label="rebalance"):
    """Scatter one marker per rebalance, unless there are too many to read."""
    if not events or len(events) > MAX_MARKERS:
        return
    idx = [e["index"] for e in events]
    ax.scatter(df["timestamp"].iloc[idx], y_series.iloc[idx], s=28,
               color=REBAL_COLOR, edgecolors="white", linewidths=1.2,
               zorder=3, label=label)


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)
    days = len(df) / 1440

    total_bin_fees, per_candle_bin_fees = accumulate_bin_fees(df)
    total_pool_fees = sum(total_bin_fees.values())

    # --- The passive position: POSITION_BINS around the first active bin ---
    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), BIN_STEP)
    half = POSITION_BINS // 2
    pos_p = make_position(USER_DEPOSIT, center - half, center + half)
    fees_p = run_position(df, pos_p, per_candle_bin_fees)
    total_p = describe(
        f"passive ({POSITION_BINS} bins on start bin {center})",
        pos_p, fees_p, days)

    # --- The rebalancing position: same start, recentred on every exit -----
    # Computed here so every chart below can show both strategies; the
    # rebalance-by-rebalance report comes further down. Its HODL baseline is
    # the same initial tokens as the passive position (identical start).
    # il is the price effect alone (costs added back and shown separately);
    # net pnl = fees + il - costs = fees + (value - hodl).
    reb_frame, reb_events = run_rebalancing(df, per_candle_bin_fees)
    hodl_reb = hodl_series(pos_p, df["close"])
    cum_fees_reb = reb_frame["fee"].cumsum()
    cum_cost_reb = reb_frame["cost"].cumsum()
    net_reb = cum_fees_reb + reb_frame["value"] - hodl_reb
    il_reb = reb_frame["value"] - hodl_reb + cum_cost_reb
    total_reb = cum_fees_reb.iloc[-1]

    cum_p = fees_p.cumsum()

    # --- Verify 1: passive monotone, final value = analytic total ----------
    # Shares are equal across the range, so the passive total must be exactly
    # its per-bin share of the fees that landed inside the range.
    assert (fees_p >= 0).all()  # per-candle fees never negative => cum non-decreasing
    assert (cum_p.diff().dropna() >= 0).all()
    fees_in_range = sum(fee for b, fee in total_bin_fees.items()
                        if pos_p.range_start <= b <= pos_p.range_end)
    expected_p = pos_p.deposit_per_bin / BIN_TVL * fees_in_range
    assert abs(cum_p.iloc[-1] - expected_p) < 1e-6
    print(f"\nverify 1 OK: passive monotone, final ${cum_p.iloc[-1]:.4f} "
          f"= analytic total ${expected_p:.4f} "
          f"({fees_in_range / total_pool_fees:.1%} of pool fees landed "
          f"in range)")

    # --- Verify 2: passive flat exactly when price is outside the range ----
    in_range = df["touched_bins"].map(
        lambda bins: any(pos_p.range_start <= b <= pos_p.range_end for b in bins)
    )
    assert ((fees_p > 0) == in_range).all()
    print(f"verify 2 OK: passive earns > 0 on exactly the {in_range.sum()} "
          "candles whose candle touched the range")

    # --- Main chart: cumulative fees, both strategies ----------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df["timestamp"], cum_p, color=PASSIVE_COLOR, lw=1.8,
            label=f"passive ({POSITION_BINS} bins) — ${total_p:.2f}")
    ax.plot(df["timestamp"], cum_fees_reb, color=REBAL_COLOR, lw=1.8,
            label=f"rebalancing ({POSITION_BINS} bins, "
                  f"{len(reb_events)} rebalances) — ${total_reb:.2f}")
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

    band_lo = raw_to_ui(get_price_from_bin_id(pos_p.range_start, BIN_STEP))
    band_hi = raw_to_ui(get_price_from_bin_id(pos_p.range_end + 1, BIN_STEP))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    ax1.axhspan(band_lo, band_hi, color=PASSIVE_COLOR, alpha=0.12,
                label="passive price range")
    ax1.plot(zoom["timestamp"], zoom["close"], color="#2563eb", lw=1.5)
    ax1.set_ylabel("price (USD)", color="#52525b")
    ax1.legend(loc="best", frameon=False, fontsize=9)
    ax1.set_title(
        f"Longest flat segment of the passive position ({len(seg)} min "
        f"starting {df['timestamp'].iloc[seg[0]]:%Y-%m-%d %H:%M} UTC): "
        "price left the range, fees stopped",
        fontsize=11, color="#3f3f46")
    ax2.plot(zoom["timestamp"], cum_p.loc[zoom.index], color=PASSIVE_COLOR,
             lw=1.8)
    ax2.set_ylabel("passive cumulative fees (USD)", color="#52525b")
    for ax in (ax1, ax2):
        ax.tick_params(colors="#52525b", labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(f"{OUTPUT_DIR}/flat_segment_zoom.png", dpi=150)
    print(f"zoom chart saved to {OUTPUT_DIR}/flat_segment_zoom.png")

    # --- Plain-text summary ------------------------------------------------
    print(f"\n=== SUMMARY ===")
    print(f"passive:     ${total_p:.2f}")
    print(f"rebalancing: ${total_reb:.2f}")
    print(f"Both hold {POSITION_BINS} bins, so the fee difference is entirely "
          f"about being in range: the passive position earned nothing on the "
          f"{(~in_range).mean():.0%} of candles where price sat outside its "
          f"window, while rebalancing moved the window {len(reb_events)} "
          f"times to follow it.")

    # --- Full accounting: fees vs impermanent loss -------------------------
    # IL here is position value minus the value of just HOLDING the initial
    # tokens: an opportunity cost versus holding, not a direct loss.
    inv_p = run_inventory(df, pos_p)
    pnl_p = pnl_frame(df, pos_p, fees_p, inventory=inv_p)
    print("\n=== fees vs impermanent loss (both in USD, vs HODL) ===")
    print(f"{'strategy':16s} {'fees':>9s} {'IL':>9s} {'net PnL':>9s}"
          f" {'net APY':>8s}")
    rows = [
        ("passive", total_p, pnl_p["il"].iloc[-1], pnl_p["net_pnl"].iloc[-1]),
        ("rebalancing", total_reb, il_reb.iloc[-1], net_reb.iloc[-1]),
    ]
    for name, fees_total, il_end, net in rows:
        apy = net / days * 365 / USER_DEPOSIT
        print(f"{name:16s} {fees_total:9.2f} {il_end:9.2f} {net:9.2f}"
              f" {apy:8.1%}")

    print("\nDid fees cover impermanent loss over this period?")
    for name, fees_total, il_end, net in rows:
        verdict = "YES" if net > 0 else "NO"
        apy = net / days * 365 / USER_DEPOSIT
        print(f"  {name}: {verdict} -- ${fees_total:.2f} of fees vs "
              f"${-il_end:.2f} given up versus just holding "
              f"-> net ${net:+.2f} ({apy:+.1%} APY)")

    # --- Full accounting chart: fees, IL, net PnL over time ----------------
    # Rebalancing carries a third term, so its panel gets an extra costs line
    # and the net-PnL identity in its label picks up the "- costs".
    panels = [
        ("passive", f"bins {pos_p.range_start}..{pos_p.range_end}",
         pnl_p["cum_fees"], pnl_p["il"], pnl_p["net_pnl"], None),
        ("rebalancing",
         f"{POSITION_BINS} bins, {len(reb_events)} rebalances",
         cum_fees_reb, il_reb, net_reb, cum_cost_reb),
    ]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for ax, (name, subtitle, cum_fees, il, net, costs) in zip(axes, panels):
        ax.axhline(0, color="#b3b3bd", lw=0.8)
        ax.plot(df["timestamp"], cum_fees, color="#2563eb", lw=1.6,
                label=f"cumulative fees (${cum_fees.iloc[-1]:+.2f})")
        ax.plot(df["timestamp"], il, color=PASSIVE_COLOR, lw=1.6,
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

    # --- The rebalancing log ----------------------------------------------
    print(f"\n=== rebalancing ({POSITION_BINS} bins, cost "
          f"{REBALANCE_COST:.2%} of value traded) ===")
    print(f"rebalances: {len(reb_events)}")
    for e in reb_events:
        ts = df["timestamp"].iloc[e["index"]]
        lo, hi = e["new_range"]
        print(f"  {ts:%Y-%m-%d %H:%M} close {e['close']:.4f}: "
              f"{e['direction']} {abs(e['sol_traded']):.4f} SOL "
              f"(${abs(e['sol_traded']) * e['close']:.2f} changed hands, "
              f"cost ${e['cost']:.4f}), new range {lo}..{hi}")

    table = [
        ("passive", pnl_p["cum_fees"].iloc[-1], pnl_p["il"].iloc[-1], 0.0,
         pnl_p["net_pnl"].iloc[-1], 0),
        ("rebalancing", cum_fees_reb.iloc[-1], il_reb.iloc[-1],
         cum_cost_reb.iloc[-1], net_reb.iloc[-1], len(reb_events)),
    ]
    print(f"\n=== strategy comparison over {days:.0f} days "
          f"(all USD, IL vs HODL) ===")
    print(f"{'strategy':16s} {'fees':>8s} {'IL':>8s} {'costs':>7s}"
          f" {'net PnL':>8s} {'net APY':>8s} {'rebal':>6s}")
    for name, f_, il_, cost_, net_, n_ in table:
        apy = net_ / days * 365 / USER_DEPOSIT
        print(f"{name:16s} {f_:8.2f} {il_:8.2f} {cost_:7.2f}"
              f" {net_:8.2f} {apy:8.1%} {n_:6d}")

    # --- Sensitivity: does the verdict survive higher trading costs? -------
    print("\nREBALANCE_COST sensitivity (rebalancing):")
    for rate in (0.0, 0.001, 0.005):
        s_frame, s_events = run_rebalancing(df, per_candle_bin_fees,
                                            cost_rate=rate)
        s_net = (s_frame["fee"].cumsum()
                 + s_frame["value"] - hodl_reb).iloc[-1]
        s_cost = s_frame["cost"].sum()
        print(f"  cost {rate:.2%}: net PnL ${s_net:+8.2f} "
              f"(total costs ${s_cost:.2f}, {len(s_events)} rebalances)")

    # --- Strategy chart: net PnL over time ---------------------------------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axhline(0, color="#b3b3bd", lw=0.8)
    ax.plot(df["timestamp"], pnl_p["net_pnl"], color=PASSIVE_COLOR, lw=1.8,
            label=f"passive (${pnl_p['net_pnl'].iloc[-1]:+.2f})")
    ax.plot(df["timestamp"], net_reb, color=REBAL_COLOR, lw=1.8,
            label=f"rebalancing (${net_reb.iloc[-1]:+.2f}, "
                  f"{len(reb_events)} rebalance"
                  f"{'s' if len(reb_events) != 1 else ''})")
    mark_rebalances(ax, df, reb_events, net_reb)
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
    # A falling price converts USDC bins to SOL, so the passive position
    # drifts into SOL; rebalancing resets the mix, so its line saw-tooths.
    inventories = [
        ("passive", inv_p, PASSIVE_COLOR),
        ("rebalancing", reb_frame, REBAL_COLOR),
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
    ax1.axhspan(band_lo, band_hi, color=PASSIVE_COLOR, alpha=0.12,
                label="passive price range")
    ax1.plot(df["timestamp"], df["close"], color="#52525b", lw=1.0)
    ax1.set_ylabel("price (USD)", color="#52525b")
    ax1.legend(loc="best", frameon=False, fontsize=9)
    ax1.set_title("SOL held by each strategy: price falling converts "
                  "USDC bins to SOL", fontsize=11, color="#3f3f46")
    for name, frame, color in inventories:
        ax2.plot(df["timestamp"], frame["sol_held"], color=color, lw=1.5,
                 label=name)
    mark_rebalances(ax2, df, reb_events, reb_frame["sol_held"])
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
