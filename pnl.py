"""Position profit and loss versus simply holding the initial tokens.

Definitions:
- hodl: the value of the position's INITIAL token composition (fixed at
  the first candle) marked at each close, with no LPing.
- il (impermanent loss): position_value - hodl. This is an OPPORTUNITY
  COST versus holding, not a direct loss: ~0 while price is near entry,
  <= 0 once price has moved away in either direction, and it closes
  again if price returns (hence "impermanent").
- net_pnl: cumulative fees + il -- what LPing earned versus holding.
"""

import pandas as pd

from inventory import inventory_totals, make_inventory, run_inventory
from position import Position


def hodl_series(position: Position, closes: pd.Series) -> pd.Series:
    """Value at each close of the t=0 token composition, held untouched."""
    sol0, usdc0 = inventory_totals(make_inventory(position, closes.iloc[0]))
    return usdc0 + sol0 * closes


def pnl_frame(df, position: Position, user_fees: pd.Series) -> pd.DataFrame:
    """Per-candle PnL accounting.

    df needs a close column; user_fees is the per-candle fee series
    aligned to df (pass zeros for a fee-free run).

    Columns: value, hodl, il, cum_fees, net_pnl.
    """
    inv = run_inventory(df, position)
    hodl = hodl_series(position, df["close"])
    il = inv["value"] - hodl
    cum_fees = user_fees.cumsum()
    return pd.DataFrame({
        "value": inv["value"],
        "hodl": hodl,
        "il": il,
        "cum_fees": cum_fees,
        "net_pnl": cum_fees + il,
    })


if __name__ == "__main__":
    from inventory import make_test_position, mid_price_ui

    FAKE_FEE = 0.50  # pretend fee per candle, to exercise the fees+il join

    a, pos = make_test_position()
    n_bins = pos.range_end - pos.range_start + 1
    total_deposit = pos.deposit_per_bin * n_bins

    # --- round trip: IL closes to ~0, so net pnl ends = total fees ---------
    path = [a, a + 1, a + 2, a + 3, a + 2, a + 1, a]
    df = pd.DataFrame({"close": [mid_price_ui(b) for b in path]})
    fees = pd.Series(FAKE_FEE, index=df.index)
    out = pnl_frame(df, pos, fees)
    print("--- round trip (pretend fees $0.50/candle) ---")
    print(out.round(6).to_string())
    assert abs(out["il"].iloc[-1]) < 1e-9
    assert abs(out["net_pnl"].iloc[-1] - fees.sum()) < 1e-9
    assert (out["il"] <= 1e-9).all()  # never a gain vs holding, only a cost
    print(f"end: IL {out['il'].iloc[-1]:+.9f} -> net pnl "
          f"{out['net_pnl'].iloc[-1]:.4f} = total fees {fees.sum():.4f}\n")

    # --- one way up: IL = -(sol sold) x (final price - avg sale price) -----
    path = [a - 3, a - 2, a - 1, a, a + 1, a + 2, a + 3, a + 3]
    df = pd.DataFrame({"close": [mid_price_ui(b) for b in path]})
    fees = pd.Series(FAKE_FEE, index=df.index)
    out = pnl_frame(df, pos, fees)
    print("--- one way up (pretend fees $0.50/candle) ---")
    print(out.round(6).to_string())

    sol0, usdc0 = inventory_totals(make_inventory(pos, df["close"].iloc[0]))
    assert usdc0 == 0.0  # starts below the range: all SOL
    end_close = df["close"].iloc[-1]
    avg_sale = total_deposit / sol0  # every bin sold at its buy-in price
    sold_too_early_gap = sol0 * (end_close - avg_sale)
    il_end = out["il"].iloc[-1]
    print(f"end: IL {il_end:+.6f}")
    print(f"hand check: sold {sol0:.6f} SOL at avg {avg_sale:.4f}, price "
          f"ended {end_close:.4f} -> gave up {sol0:.6f} x "
          f"{end_close - avg_sale:.4f} = {sold_too_early_gap:.6f}")
    assert abs(il_end + sold_too_early_gap) < 1e-9
    assert abs(out["net_pnl"].iloc[-1] - (fees.sum() + il_end)) < 1e-12
    print(f"net pnl {out['net_pnl'].iloc[-1]:+.6f} = fees {fees.sum():.2f} "
          f"+ IL {il_end:+.6f}")
