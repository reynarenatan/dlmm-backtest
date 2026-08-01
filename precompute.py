"""Run the engine once and write the numbers the web app reads.

The app never runs a backtest: a year of minute candles takes tens of
seconds per strategy, which is not something a page load can do. So the
results are computed here, ahead of time, and committed as JSON.

Re-run this after any change to config.py or the engine, or the app will
keep showing the previous numbers:

    python precompute.py
"""

import json
from pathlib import Path

from backtest import prepare, run
from bin_math import get_bin_id_from_price, get_bin_range
from candle_bins import raw_to_ui, ui_to_raw
from config import (BIN_STEP, BIN_TVL, FEE_RATE, POOL_SHARE, POSITION_BINS,
                    USER_DEPOSIT)
from fees import accumulate_bin_fees, candle_fee
from position import make_position, user_fee_for_candle

OUT_PATH = Path("results/year_summary.json")

# What a results page quotes. Everything else stays in the run.
HEADLINE = ("total_fees", "total_il", "total_costs", "net_pnl", "net_apy",
            "gross_fee_apy", "break_even_fee_rate", "final_value",
            "rebalances", "time_in_range_pct", "max_drawdown",
            "max_drawdown_date")

# Rebalance costs the sensitivity table reports, as fractions of the value
# traded. The middle one is the configured REBALANCE_COST.
COST_RATES = (0.0, 0.001, 0.005)


def summarise(result) -> dict:
    """The headline metrics, plus what the deposit itself did.

    net_pnl is measured against holding, so on its own it cannot say
    whether the money grew: total_wealth and absolute_return answer that.
    """
    m, s, p = result["metrics"], result["series"], result["params"]
    hodl_end = float(s["hodl"].iloc[-1])
    entry_value = float(s["value"].iloc[0])
    total_wealth = m["total_fees"] + m["final_value"]

    # Both strategies open the same range on the first candle; rebalancing
    # is just the one that moves it afterwards.
    low_edge, _ = get_bin_range(int(s["range_start"].iloc[0]), p["bin_step"])
    _, high_edge = get_bin_range(int(s["range_end"].iloc[0]), p["bin_step"])

    ninety_days = min(len(s), 90 * 1440)
    fees_first_90d = float(s["cum_fees"].iloc[ninety_days - 1])

    return {
        **{key: m[key] for key in HEADLINE},
        "entry_value": entry_value,
        "hodl_end": hodl_end,
        "total_wealth": total_wealth,
        "absolute_return_pct": (total_wealth / entry_value - 1) * 100,
        "initial_range_low": raw_to_ui(low_edge),
        "initial_range_high": raw_to_ui(high_edge),
        "fees_first_90d": fees_first_90d,
        "fees_first_90d_pct": fees_first_90d / m["total_fees"] * 100,
        "phases": composition_phases(s, moves=bool(m["rebalances"])),
    }


def cost_sensitivity(df, per_candle_bin_fees) -> list:
    """Whether the rebalancing verdict survives a different trading cost."""
    rows = []
    for rate in COST_RATES:
        m = run(df, strategy="rebalancing", cost_rate=rate,
                per_candle_bin_fees=per_candle_bin_fees)["metrics"]
        rows.append({
            "cost_rate": rate,
            "net_pnl": m["net_pnl"],
            "total_costs": m["total_costs"],
            "total_fees": m["total_fees"],
            "rebalances": m["rebalances"],
        })
    return rows


def composition_phases(s, moves) -> dict:
    """When the position held only USDC, and when it went all SOL for good.

    This is what the shape of the value chart is made of. A position whose
    bins all sit below the price holds nothing but USDC, so its value
    cannot move with the price at all; one whose bins all sit above the
    price is a pure SOL bag and moves with it one for one.

    The USDC-only stretch is not contiguous -- the price dips back into
    the range and out again -- so it is reported as a count of candles and
    the value they all share, not as a date range that would imply a
    single unbroken run.

    That shared value only exists for a position whose range never moves.
    A rebalancing one is rebuilt at a different size each time, so its
    USDC-only candles are worth many different amounts and the figure is
    left out rather than averaged into something meaningless.
    """
    usdc_only = s[s["sol_held"] == 0]
    with_usdc = s.index[s["usdc_held"] > 0]
    phases = {
        "usdc_only_candles": int(len(usdc_only)),
        "usdc_only_value": None,
        "sol_only_from": None,
        "sol_only_start_value": None,
        "sol_only_start_close": None,
    }
    if len(usdc_only) and not moves:
        # A fixed position holding nothing but USDC cannot change value,
        # whatever the price does. That is the claim the flat stretch on
        # the chart makes, so it is asserted rather than assumed.
        assert usdc_only["value"].nunique() == 1
        phases["usdc_only_value"] = float(usdc_only["value"].iloc[0])
    if len(with_usdc) and with_usdc[-1] + 1 < len(s):
        after = s.loc[with_usdc[-1] + 1:]
        phases["sol_only_from"] = str(after["timestamp"].iloc[0])
        phases["sol_only_start_value"] = float(after["value"].iloc[0])
        phases["sol_only_start_close"] = float(after["close"].iloc[0])
    return phases


def pool_summary(total_bin_fees, bin_step) -> dict:
    """What the whole pool earned, and where along the price it landed."""
    busiest = max(total_bin_fees, key=total_bin_fees.get)
    low_edge, high_edge = get_bin_range(busiest, bin_step)
    return {
        "total_fees": sum(total_bin_fees.values()),
        "bins_touched": len(total_bin_fees),
        "busiest_bin_fees": total_bin_fees[busiest],
        "busiest_bin_low": raw_to_ui(low_edge),
        "busiest_bin_high": raw_to_ui(high_edge),
    }


def worked_example(df, per_candle_bin_fees) -> dict:
    """One real candle walked through all five steps of the fee chain.

    Chosen rather than invented: of the candles that touch more than one
    bin while the opening position is in range, this is the one with the
    median volume, so the numbers are typical rather than flattering.
    Every figure comes from the same functions the run uses.
    """
    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), BIN_STEP)
    half = POSITION_BINS // 2
    position = make_position(USER_DEPOSIT, center - half, center + half)
    in_position = set(range(position.range_start, position.range_end + 1))

    candidates = [
        i for i in range(len(df))
        if df["num_bins"].iloc[i] > 1
        and set(df["touched_bins"].iloc[i]) <= in_position
    ]
    volumes = df["volume_usd"].iloc[candidates]
    row_index = candidates[int((volumes - volumes.median()).abs()
                               .reset_index(drop=True).idxmin())]

    row = df.iloc[row_index]
    bin_fees = per_candle_bin_fees[row_index]
    fee = sum(bin_fees.values())
    pool_volume = row["volume_usd"] * POOL_SHARE

    # The split has to conserve the candle's fee, and the fee has to be
    # the one the fee function produces. Both are asserted rather than
    # assumed, because this page is where someone checks our arithmetic.
    assert abs(fee - candle_fee(row["volume_usd"], POOL_SHARE,
                                FEE_RATE)) < 1e-9
    user_fee = user_fee_for_candle(position, bin_fees)
    share = position.deposit_per_bin / BIN_TVL

    bins = []
    for bin_id, bin_fee in sorted(bin_fees.items()):
        low_edge, high_edge = get_bin_range(bin_id, BIN_STEP)
        bins.append({
            "bin_id": bin_id,
            "low": raw_to_ui(low_edge),
            "high": raw_to_ui(high_edge),
            "share_of_candle_fee_pct": bin_fee / fee * 100,
            "fee": bin_fee,
            "user_fee": bin_fee * position.shares.get(bin_id, 0.0),
        })

    return {
        "timestamp": str(row["timestamp"]),
        "low": float(row["low"]),
        "high": float(row["high"]),
        "close": float(row["close"]),
        "market_volume": float(row["volume_usd"]),
        "pool_share": POOL_SHARE,
        "pool_volume": float(pool_volume),
        "fee_rate": FEE_RATE,
        "candle_fee": float(fee),
        "bins": bins,
        "deposit_per_bin": position.deposit_per_bin,
        "bin_tvl": BIN_TVL,
        "share_of_bin_pct": share * 100,
        "user_fee": float(user_fee),
    }


def first_rebalance(result) -> dict:
    """The first time the range moved, with what it traded and cost."""
    events, s = result["events"], result["series"]
    if not events:
        return {}
    event = events[0]
    # Events carry no timestamp; the first candle whose range differs from
    # the opening one is the candle the first rebalance happened on.
    moved = s.index[s["range_start"] != s["range_start"].iloc[0]]
    row = s.loc[moved[0]]
    old_low, _ = get_bin_range(int(s["range_start"].iloc[0]), BIN_STEP)
    _, old_high = get_bin_range(int(s["range_end"].iloc[0]), BIN_STEP)
    new_low, _ = get_bin_range(int(event["new_range"][0]), BIN_STEP)
    _, new_high = get_bin_range(int(event["new_range"][1]), BIN_STEP)

    return {
        "timestamp": str(row["timestamp"]),
        "close": event["close"],
        "direction": event["direction"],
        "sol_traded": abs(event["sol_traded"]),
        "value_traded": abs(event["sol_traded"]) * event["close"],
        "value_before": event["value_before"],
        "cost": event["cost"],
        "old_low": raw_to_ui(old_low),
        "old_high": raw_to_ui(old_high),
        "new_low": raw_to_ui(new_low),
        "new_high": raw_to_ui(new_high),
    }


def build() -> dict:
    df = prepare()
    total_bin_fees, per_candle_bin_fees = accumulate_bin_fees(df)

    strategies, params, rebalance = {}, None, {}
    for strategy in ("passive", "rebalancing"):
        result = run(df, strategy=strategy,
                     per_candle_bin_fees=per_candle_bin_fees)
        strategies[strategy] = summarise(result)
        params = result["params"]
        if strategy == "rebalancing":
            rebalance = first_rebalance(result)

    hodl_end = strategies["passive"]["hodl_end"]
    entry_value = strategies["passive"]["entry_value"]
    first_close = float(df["close"].iloc[0])
    last_close = float(df["close"].iloc[-1])

    # How much price a position spans, which is why a 69-bin band is a
    # hairline on a year chart: 69 bins at step 4 is about 2.8%.
    span = get_bin_range(params["position_bins"], params["bin_step"])[0]
    width_pct = (span / get_bin_range(0, params["bin_step"])[0] - 1) * 100

    return {
        "params": params,
        "position_width_pct": width_pct,
        "market": {
            "start_price": first_close,
            "end_price": last_close,
            "change_pct": (last_close / first_close - 1) * 100,
        },
        "hodl": {
            "entry_value": entry_value,
            "end_value": hodl_end,
            "absolute_return_pct": (hodl_end / entry_value - 1) * 100,
        },
        "pool": pool_summary(total_bin_fees, params["bin_step"]),
        "worked_example": worked_example(df, per_candle_bin_fees),
        "first_rebalance": rebalance,
        "strategies": strategies,
        "cost_sensitivity": cost_sensitivity(df, per_candle_bin_fees),
    }


if __name__ == "__main__":
    summary = build()
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    for name, s in summary["strategies"].items():
        print(f"  {name:<13} fees ${s['total_fees']:>8,.2f}   "
              f"net ${s['net_pnl']:>+8,.2f}   "
              f"absolute {s['absolute_return_pct']:>+6.1f}%")
