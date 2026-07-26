"""Position management strategies compared over the same candle data.

A) Passive wide: one position covering every touched bin, never touched.
B) Passive concentrated: CONCENTRATED_BINS wide, set once, never touched.
C) Rebalancing concentrated: same width as B, but whenever a candle
   CLOSES outside the range, the position is closed and reopened
   centered on the bin the close sits in.

Rebalance model (deliberately simple):
- holdings are marked to market at the close -> value V.
- the new position uses the same construction as the initial deposit
  (USDC in bins at or below the active bin, SOL above, each SOL bin
  converted at its own price), scaled so it is worth exactly V at the
  close. The conversion is therefore value-neutral by construction.
- reaching the new mix means trading SOL at the close price: after a
  rise the old bins are all USDC and the new upper bins need SOL (BUY);
  after a fall the old bins are all SOL and the new lower bins need
  USDC (SELL).
- REBALANCE_COST is charged on the value that changes hands (the SOL
  bought or sold), not on the whole position, and is paid by scaling
  the new position down. The charge is computed on the pre-scaling
  trade size; scaling shifts the actual trade by ~cost x rate, which is
  far below a cent at these sizes.
"""

import pandas as pd

from config import CONCENTRATED_BINS, REBALANCE_COST, USER_DEPOSIT
from fees import accumulate_bin_fees
from inventory import (active_bin, bin_price_ui, inventory_totals,
                       make_inventory, position_value, update_inventory)
from position import make_position, user_fee_for_candle


def rebalance(inv: dict, close: float, width: int,
              cost_rate: float) -> tuple:
    """Close the position and reopen it centered on the close's bin.

    Returns (new_position, new_inventory, event) where event records
    what was traded: sol_traded > 0 means SOL was bought, < 0 sold.
    """
    value = position_value(inv, close)
    act = active_bin(close)
    half = width // 2
    start, end = act - half, act + half
    bins = range(start, end + 1)

    # Marked value of the new position per dollar allocated to each bin:
    # a USDC bin is worth its dollar; a SOL bin holds 1/bin_price SOL,
    # worth close/bin_price.
    sol_per_dollar = sum(1 / bin_price_ui(b) for b in bins if b > act)
    n_usdc = sum(1 for b in bins if b <= act)
    value_per_dollar = n_usdc + close * sol_per_dollar

    sol_old, _ = inventory_totals(inv)
    sol_target = value / value_per_dollar * sol_per_dollar
    sol_traded = sol_target - sol_old
    cost = cost_rate * abs(sol_traded) * close

    per_bin = (value - cost) / value_per_dollar
    new_pos = make_position(per_bin * len(bins), start, end)
    new_inv = make_inventory(new_pos, close)
    # Value-neutral apart from the explicit cost: no hidden jump.
    assert abs(position_value(new_inv, close) - (value - cost)) < 1e-9

    event = {
        "close": close,
        "value_before": value,
        "sol_traded": sol_traded,
        "direction": "BUY" if sol_traded > 0 else "SELL",
        "cost": cost,
        "new_range": (start, end),
    }
    return new_pos, new_inv, event


def run_strategy_c(df, per_candle_bin_fees=None, width=CONCENTRATED_BINS,
                   cost_rate=REBALANCE_COST):
    """Walk the candles managing a rebalancing concentrated position.

    Starts exactly like the passive concentrated scenario (same center,
    same deposit); each candle earns the current position's fee, then
    the inventory absorbs the close, then a close outside the range
    triggers a rebalance (which affects fees from the NEXT candle on).

    Returns (frame, events): frame has value / fee / cost per candle
    (value is marked after any rebalance, i.e. net of its cost);
    events is one dict per rebalance with the row index added.
    """
    if per_candle_bin_fees is None:
        _, per_candle_bin_fees = accumulate_bin_fees(df)

    center = active_bin(df["open"].iloc[0])
    half = width // 2
    pos = make_position(USER_DEPOSIT, center - half, center + half)
    inv = make_inventory(pos, df["close"].iloc[0])

    rows, events = [], []
    for i, close in enumerate(df["close"]):
        fee = user_fee_for_candle(pos, per_candle_bin_fees[i])
        inv, _ = update_inventory(inv, close)
        cost = 0.0
        if not pos.range_start <= active_bin(close) <= pos.range_end:
            pos, inv, event = rebalance(inv, close, width, cost_rate)
            event["index"] = i
            events.append(event)
            cost = event["cost"]
        rows.append((position_value(inv, close), fee, cost))

    frame = pd.DataFrame(rows, columns=["value", "fee", "cost"],
                         index=df.index)
    return frame, events


# ======================================================================
# Synthetic verification checks
# ======================================================================

def make_synthetic_df(bin_path: list[int],
                      volume_usd: float = 50_000) -> pd.DataFrame:
    """One candle per bin id, close in that bin's middle, flat volume."""
    from inventory import mid_price_ui

    closes = [mid_price_ui(b) for b in bin_path]
    return pd.DataFrame({
        "open": [closes[0]] + closes[:-1],
        "close": closes,
        "volume_usd": volume_usd,
        "touched_bins": [[b] for b in bin_path],
    })


def print_events(df, events) -> None:
    for e in events:
        lo, hi = e["new_range"]
        print(f"    candle {e['index']}: close {e['close']:.4f} left the "
              f"range -> {e['direction']} {abs(e['sol_traded']):.6f} SOL "
              f"at {e['close']:.4f} (${abs(e['sol_traded']) * e['close']:.2f}"
              f" changed hands, cost ${e['cost']:.4f}), new range {lo}..{hi}")


def check_equals_passive_when_inside() -> None:
    print("=" * 72)
    print("CHECK 1 -- price never leaves the range: C must equal B exactly")
    print("=" * 72)
    a = active_bin(76.0)
    width, half = 5, 2
    path = [a, a + 1, a + 2, a + 1, a - 1, a - 2, a, a + 2, a]
    df = make_synthetic_df(path)
    print(f"  range: bins {a - half}..{a + half} (width {width}); "
          f"close path (active bin): {path}")

    frame_c, events = run_strategy_c(df, width=width)

    # Passive concentrated over the same data, built the same way.
    from inventory import run_inventory
    pos_b = make_position(USER_DEPOSIT, a - half, a + half)
    _, per_candle = accumulate_bin_fees(df)
    fees_b = [user_fee_for_candle(pos_b, f) for f in per_candle]
    inv_b = run_inventory(df, pos_b)

    assert not events, "no candle left the range, so no rebalance"
    assert frame_c["fee"].tolist() == fees_b
    assert frame_c["value"].tolist() == inv_b["value"].tolist()
    assert frame_c["cost"].sum() == 0.0
    print(f"  0 rebalances; fee and value series identical to B at every "
          f"candle (total fees ${frame_c['fee'].sum():.4f}) -- PASS")


def check_zero_cost_continuity() -> None:
    print("=" * 72)
    print("CHECK 2 -- REBALANCE_COST = 0: value must never jump at a "
          "rebalance")
    print("=" * 72)
    a = active_bin(76.0)
    up = list(range(a, a + 8))
    down = list(range(a, a - 8, -1))
    for name, path in (("rise", up), ("fall", down)):
        df = make_synthetic_df(path)
        frame, events = run_strategy_c(df, width=5, cost_rate=0.0)
        assert events, "path must actually leave the range"
        for e in events:
            recorded = frame["value"].iloc[e["index"]]
            assert e["cost"] == 0.0
            assert abs(recorded - e["value_before"]) < 1e-9
            print(f"  {name}: candle {e['index']} value before "
                  f"{e['value_before']:.6f} -> after {recorded:.6f} "
                  f"(jump {recorded - e['value_before']:+.2e})")
    print("  conversion is value-neutral at every rebalance -- PASS")


def check_trade_directions() -> None:
    print("=" * 72)
    print("CHECK 3 -- trade direction: rise past the range BUYS SOL, "
          "fall SELLS")
    print("=" * 72)
    a = active_bin(76.0)

    print("  steady RISE (position turns all-USDC on the way up, so the")
    print("  new upper bins must be bought):")
    df = make_synthetic_df(list(range(a, a + 8)))
    _, events = run_strategy_c(df, width=5)
    print_events(df, events)
    assert events and all(e["direction"] == "BUY" for e in events)

    print("  steady FALL (position turns all-SOL on the way down, so the")
    print("  new lower bins' USDC must come from selling):")
    df = make_synthetic_df(list(range(a, a - 8, -1)))
    _, events = run_strategy_c(df, width=5)
    print_events(df, events)
    assert events and all(e["direction"] == "SELL" for e in events)
    print("  directions match on both paths -- PASS")


if __name__ == "__main__":
    check_equals_passive_when_inside()
    print()
    check_zero_cost_continuity()
    print()
    check_trade_directions()
