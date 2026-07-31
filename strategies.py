"""Position management strategies compared over the same candle data.

Both strategies hold the same POSITION_BINS-wide range (Meteora's default
position range), so the only thing separating them is whether that range
is ever moved:

- passive: set once on the first candle and never touched. A baseline,
  kept only so we can say whether rebalancing helped.
- rebalancing: whenever a candle CLOSES outside the range, the position
  is closed and reopened centered on the bin the close sits in. This is
  what users actually do, and the strategy being evaluated.

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

from config import POSITION_BINS, REBALANCE_COST, USER_DEPOSIT
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


def run_rebalancing(df, per_candle_bin_fees=None, width=POSITION_BINS,
                    cost_rate=REBALANCE_COST):
    """Walk the candles managing a rebalancing position.

    Starts exactly like the passive scenario (same center, same
    deposit); each candle earns the current position's fee, then
    the inventory absorbs the close, then a close outside the range
    triggers a rebalance (which affects fees from the NEXT candle on).

    Returns (frame, events): frame has value / fee / cost, the
    sol_held / usdc_held behind that value, and the range_start /
    range_end the position holds going forward, per candle (all recorded
    after any rebalance, i.e. net of its cost); events is one dict per
    rebalance with the row index added.

    range_start/range_end are recorded for reporting only -- nothing in
    the walk reads them back.
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
        sol, usdc = inventory_totals(inv)
        rows.append((usdc + sol * close, fee, cost, sol, usdc,
                     pos.range_start, pos.range_end))

    frame = pd.DataFrame(
        rows, columns=["value", "fee", "cost", "sol_held", "usdc_held",
                       "range_start", "range_end"],
        index=df.index)
    return frame, events


# ======================================================================
# Synthetic verification checks
# ======================================================================

def make_synthetic_df(bin_path: list[int],
                      volume_usd: float = 50_000) -> pd.DataFrame:
    """One candle per bin id, close in that bin's middle, flat volume.

    low/high span exactly the candle's one touched bin, so the weighted
    fee split hands that bin the whole fee and matches the equal split.
    """
    from inventory import mid_price_ui

    closes = [mid_price_ui(b) for b in bin_path]
    return pd.DataFrame({
        "open": [closes[0]] + closes[:-1],
        "close": closes,
        "low": [bin_price_ui(b) for b in bin_path],
        "high": [bin_price_ui(b + 1) for b in bin_path],
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
    print("CHECK 1 -- price never leaves the range: rebalancing must equal "
          "passive exactly")
    print("=" * 72)
    a = active_bin(76.0)
    width, half = 5, 2
    path = [a, a + 1, a + 2, a + 1, a - 1, a - 2, a, a + 2, a]
    df = make_synthetic_df(path)
    print(f"  range: bins {a - half}..{a + half} (width {width}); "
          f"close path (active bin): {path}")

    frame_reb, events = run_rebalancing(df, width=width)

    # The passive position over the same data, built the same way.
    from inventory import run_inventory
    pos_p = make_position(USER_DEPOSIT, a - half, a + half)
    _, per_candle = accumulate_bin_fees(df)
    fees_p = [user_fee_for_candle(pos_p, f) for f in per_candle]
    inv_p = run_inventory(df, pos_p)

    assert not events, "no candle left the range, so no rebalance"
    assert frame_reb["fee"].tolist() == fees_p
    assert frame_reb["value"].tolist() == inv_p["value"].tolist()
    assert frame_reb["cost"].sum() == 0.0
    print(f"  0 rebalances; fee and value series identical to passive at "
          f"every candle (total fees ${frame_reb['fee'].sum():.4f}) -- PASS")


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
        frame, events = run_rebalancing(df, width=5, cost_rate=0.0)
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
    _, events = run_rebalancing(df, width=5)
    print_events(df, events)
    assert events and all(e["direction"] == "BUY" for e in events)

    print("  steady FALL (position turns all-SOL on the way down, so the")
    print("  new lower bins' USDC must come from selling):")
    df = make_synthetic_df(list(range(a, a - 8, -1)))
    _, events = run_rebalancing(df, width=5)
    print_events(df, events)
    assert events and all(e["direction"] == "SELL" for e in events)
    print("  directions match on both paths -- PASS")


def check_long_oscillation() -> None:
    """A closed price loop, repeated: recentring alone must bleed value.

    The other checks here are 8 candles with one or two rebalances, which
    is far too short to see a slow per-rebalance loss -- that is how a
    position decaying $1,000 -> $0.02 over 2,236 rebalances went unnoticed.

    The path is a sawtooth that returns to its exact starting price, run
    with REBALANCE_COST = 0, so fees and explicit costs cannot explain
    anything: whatever the position loses is the buy-high/sell-low cost of
    moving the range. The passive position over the same path must come
    back to exactly where it started.
    """
    print("=" * 72)
    print("CHECK 4 -- repeated closed loop: recentring bleeds value")
    print("=" * 72)
    a = active_bin(76.0)
    width = POSITION_BINS
    half = width // 2
    amplitude = half + 6  # must exceed half, or the price never exits
    cycles = 30

    offsets = []
    for _ in range(cycles):
        offsets += list(range(0, amplitude)) + list(range(amplitude, 0, -1))
    offsets.append(0)  # close the loop on the starting bin
    path = [a + o for o in offsets]
    df = make_synthetic_df(path)
    assert df["close"].iloc[-1] == df["close"].iloc[0]

    from inventory import run_inventory
    pos = make_position(USER_DEPOSIT, a - half, a + half)
    passive = run_inventory(df, pos)
    frame, events = run_rebalancing(df, width=width, cost_rate=0.0)

    v0 = frame["value"].iloc[0]
    v1 = frame["value"].iloc[-1]
    print(f"  {len(df)} candles, {cycles} identical price cycles of "
          f"+/-{amplitude} bins, width {width}, cost 0")
    print(f"  passive:     {passive['value'].iloc[0]:.6f} -> "
          f"{passive['value'].iloc[-1]:.6f}")
    print(f"  rebalancing: {v0:.6f} -> {v1:.6f}  "
          f"({(v1 / v0 - 1) * 100:+.4f}% over {len(events)} rebalances)")

    assert len(events) >= 50, f"expected 50+ rebalances, got {len(events)}"
    assert frame["cost"].sum() == 0.0
    assert passive["value"].iloc[-1] == passive["value"].iloc[0], (
        "passive must return to exactly its starting value on a closed loop")
    assert v1 < v0, (
        "rebalancing on a closed loop at zero cost must LOSE value; if this "
        "ever passes, the recentring conversion has stopped being lossy")

    # Each cycle ends on the same price, so once the position has settled
    # into the sawtooth every cycle costs the same fraction. That makes the
    # decay a plain geometric series: predict the end from one cycle's ratio.
    per_cycle = len(offsets) // cycles
    ends = [frame["value"].iloc[min((k + 1) * per_cycle, len(df) - 1)]
            for k in range(cycles)]
    ratios = [ends[k + 1] / ends[k] for k in range(len(ends) - 1)]
    steady = ratios[-1]
    print(f"  per-cycle value ratio: first {ratios[0]:.6f}, "
          f"last {steady:.6f}  ({(steady - 1) * 100:+.4f}% per cycle)")

    spread = max(ratios[1:]) - min(ratios[1:])
    assert spread < 1e-6, (
        f"after the first cycle every cycle should cost the same fraction; "
        f"ratios spread by {spread:.2e}")
    predicted = ends[0] * steady ** (cycles - 1)
    print(f"  predicted end from one cycle: {predicted:.6f} vs actual "
          f"{ends[-1]:.6f}")
    assert abs(predicted - ends[-1]) < 1e-6 * ends[0]

    per_rebalance = (v1 / v0) ** (1 / len(events)) - 1
    print(f"  isolated cost of recentring: {per_rebalance * 100:+.4f}% "
          f"per rebalance -- PASS")


if __name__ == "__main__":
    check_equals_passive_when_inside()
    print()
    check_zero_cost_continuity()
    print()
    check_trade_directions()
    print()
    check_long_oscillation()
