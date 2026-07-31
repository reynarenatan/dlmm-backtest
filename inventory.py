"""Token inventory of a liquidity position: which token each bin holds.

A bin never holds "dollars" -- it holds actual tokens, and which token
depends on where the bin sits relative to the current price:

- bins BELOW the price hold USDC (resting bids waiting to buy SOL)
- bins ABOVE the price hold SOL (resting asks waiting to sell SOL)

When price rises through a bin, traders buy its SOL and leave USDC
behind; when price falls back through it, the reverse. So the position's
token composition changes purely because price moved.

Simplified model (all simplifications deliberate):
- sides are decided from each candle's CLOSE only; the intra-candle path
  is ignored (a close that jumps several bins flips them all at once).
- the active bin is treated as all-USDC instead of a partial mix, so the
  side rule is: bin_id <= active bin -> USDC, bin_id > active bin -> SOL.
- a flip converts the bin's whole holding at the BIN'S OWN price (its
  lower edge, UI terms), approximating real trades crossing the bin at
  its price.
- at t=0 the deposit converts the same way: USDC-side bins hold
  deposit_per_bin dollars, SOL-side bins hold deposit_per_bin / bin_price
  SOL (each bin's own price, not the market price).
- fee earnings are tracked elsewhere and are NOT part of this inventory.
"""

import sys

import pandas as pd

from bin_math import get_bin_id_from_price, get_price_from_bin_id
from candle_bins import raw_to_ui, ui_to_raw
from config import BIN_STEP
from position import Position, make_position


def bin_price_ui(bin_id: int, bin_step: int = BIN_STEP) -> float:
    """UI price of the bin's lower edge -- the price a flip converts at."""
    return raw_to_ui(get_price_from_bin_id(bin_id, bin_step))


def active_bin(close_ui: float, bin_step: int = BIN_STEP) -> int:
    """The bin the close price sits in."""
    return get_bin_id_from_price(ui_to_raw(close_ui), bin_step)


def make_inventory(position: Position, first_close: float) -> dict:
    """Initial holdings: the deposit converts to tokens at the first close.

    Returns {bin_id: (side, amount)} where side is "USDC" or "SOL" and
    amount is in that token's units.
    """
    act = active_bin(first_close)
    inv = {}
    for b in range(position.range_start, position.range_end + 1):
        if b <= act:
            inv[b] = ("USDC", position.deposit_per_bin)
        else:
            inv[b] = ("SOL", position.deposit_per_bin / bin_price_ui(b))
    return inv


def update_inventory(inv: dict, close: float) -> tuple[dict, list]:
    """Apply one candle's close; return (new inventory, flips).

    A bin whose side no longer matches the close converts its whole
    holding at its own price. flips lists
    (bin_id, old_side, old_amount, new_side, new_amount) for inspection.
    """
    act = active_bin(close)
    new_inv, flips = {}, []
    for b, (side, amount) in inv.items():
        want = "USDC" if b <= act else "SOL"
        if want == side:
            new_inv[b] = (side, amount)
        else:
            p = bin_price_ui(b)
            new_amount = amount * p if side == "SOL" else amount / p
            new_inv[b] = (want, new_amount)
            flips.append((b, side, amount, want, new_amount))
    return new_inv, flips


def inventory_totals(inv: dict) -> tuple[float, float]:
    """(total SOL held, total USDC held) across all bins."""
    sol = sum(a for s, a in inv.values() if s == "SOL")
    usdc = sum(a for s, a in inv.values() if s == "USDC")
    return sol, usdc


def position_value(inv: dict, close: float) -> float:
    """Mark the inventory to market: USDC + SOL x close."""
    sol, usdc = inventory_totals(inv)
    return usdc + sol * close


def run_inventory(df, position: Position) -> pd.DataFrame:
    """Per-candle sol_held / usdc_held / value over a close series."""
    closes = df["close"].tolist()
    inv = make_inventory(position, closes[0])
    rows = []
    for c in closes:
        inv, _ = update_inventory(inv, c)  # no-op on the first candle
        sol, usdc = inventory_totals(inv)
        rows.append((sol, usdc, usdc + sol * c))
    return pd.DataFrame(
        rows, columns=["sol_held", "usdc_held", "value"], index=df.index
    )


# ======================================================================
# Synthetic verification checks (tiny series, every number hand-checkable)
# ======================================================================

def print_inventory(inv: dict, close: float) -> None:
    for b in sorted(inv):
        side, amount = inv[b]
        p = bin_price_ui(b)
        if side == "USDC":
            print(f"    bin {b} (own price {p:.4f}): {amount:11.4f} USDC")
        else:
            print(f"    bin {b} (own price {p:.4f}): {amount:11.6f} SOL"
                  f"  (deposit 100 / {p:.4f})")
    sol, usdc = inventory_totals(inv)
    print(f"    totals: {sol:.6f} SOL + {usdc:.4f} USDC"
          f" -> value at close {close:.4f} = {position_value(inv, close):.6f}")


def print_flips(flips: list) -> None:
    for b, old_side, old_amt, _, new_amt in flips:
        p = bin_price_ui(b)
        if old_side == "SOL":
            print(f"      bin {b} SOL->USDC: {old_amt:.6f} SOL x {p:.4f}"
                  f" = {new_amt:.4f} USDC")
        else:
            print(f"      bin {b} USDC->SOL: {old_amt:.4f} USDC / {p:.4f}"
                  f" = {new_amt:.6f} SOL")


def mid_price_ui(bin_id: int) -> float:
    """A UI price safely inside bin_id (lower edge + half a bin step)."""
    return bin_price_ui(bin_id) * (1 + BIN_STEP / 20_000)


def within_bin(bin_id: int, fraction: float) -> float:
    """A UI price `fraction` of the way up bin_id (0 = lower edge)."""
    return bin_price_ui(bin_id) * (1 + fraction * BIN_STEP / 10_000)


def make_test_position() -> tuple[int, Position]:
    """5 bins, $100 each, centered on the bin containing $76."""
    a = active_bin(76.0)
    return a, make_position(500, a - 2, a + 2)


def check_no_crossing() -> None:
    print("=" * 72)
    print("CHECK 1 -- no crossing: every close stays inside ONE bin")
    print("=" * 72)
    a, pos = make_test_position()
    print(f"  position: bins {a - 2}..{a + 2}, $100 per bin, edges "
          f"{bin_price_ui(a - 2):.4f}..{bin_price_ui(a + 3):.4f}")
    wiggle = (0.1, 0.4, 0.8, 0.4, 0.1)  # fractions of a bin: never crosses

    # (a) closes wiggle inside a bin ABOVE the whole range: every bin is
    # on the USDC side, so value is constant to the cent AND the satoshi.
    closes = [within_bin(a + 4, f) for f in wiggle]
    inv = make_inventory(pos, closes[0])
    v0 = position_value(inv, closes[0])
    print(f"\n  (a) closes inside bin {a + 4} (above the range) -> all USDC")
    print_inventory(inv, closes[0])
    for i, c in enumerate(closes):
        inv, flips = update_inventory(inv, c)
        v = position_value(inv, c)
        print(f"    candle {i}: close {c:.4f}  flips {len(flips)}"
              f"  value {v:.6f}  (change {v - v0:+.10f})")
        assert not flips and v == v0
    print("    value change exactly 0 every candle -- PASS")

    # (b) closes wiggle inside the MIDDLE bin of the range: two bins hold
    # SOL. Composition is frozen (no flips), but value still moves with
    # the close -- exactly by sol_held x (close - close0), returning to
    # exactly 0 when the close returns to its start.
    closes = [within_bin(a, f) for f in wiggle]
    inv = make_inventory(pos, closes[0])
    sol0, usdc0 = inventory_totals(inv)
    v0 = position_value(inv, closes[0])
    print(f"\n  (b) closes inside bin {a} (middle of the range)")
    print_inventory(inv, closes[0])
    for i, c in enumerate(closes):
        inv, flips = update_inventory(inv, c)
        v = position_value(inv, c)
        mtm = sol0 * (c - closes[0])
        print(f"    candle {i}: close {c:.4f}  flips {len(flips)}"
              f"  value {v:.6f} = v0 {mtm:+.6f} (SOL mark-to-market)")
        assert not flips
        assert inventory_totals(inv) == (sol0, usdc0)
        assert abs((v - v0) - mtm) < 1e-9
    assert abs(v - v0) < 1e-12  # last close == first close
    print("    composition frozen; value moved ONLY by marking the held SOL")
    print("    at the close, and returned exactly to start -- PASS")


def check_round_trip() -> None:
    print("=" * 72)
    print("CHECK 2 -- round trip: price rises through the whole range, returns")
    print("=" * 72)
    a, pos = make_test_position()
    path = [a, a + 1, a + 2, a + 3, a + 2, a + 1, a]
    closes = [mid_price_ui(b) for b in path]
    print(f"  position: bins {a - 2}..{a + 2}, $100 per bin")
    print(f"  close path (active bin): {path}")

    inv0 = make_inventory(pos, closes[0])
    v0 = position_value(inv0, closes[0])
    print("\n  initial inventory (active bin = "
          f"{path[0]}, bins above it hold SOL):")
    print_inventory(inv0, closes[0])

    inv = inv0
    for i, c in enumerate(closes):
        inv, flips = update_inventory(inv, c)
        sol, usdc = inventory_totals(inv)
        print(f"    candle {i}: close {c:.4f} (active bin {path[i]})"
              f"  SOL {sol:.6f}  USDC {usdc:.4f}"
              f"  value {position_value(inv, c):.6f}")
        print_flips(flips)

    vf = position_value(inv, closes[-1])
    print(f"\n  final vs initial: value {vf:.6f} vs {v0:.6f}"
          f"  (diff {vf - v0:+.2e})")
    for b in inv:
        side0, amt0 = inv0[b]
        side, amt = inv[b]
        assert side == side0 and abs(amt - amt0) < 1e-9, (b, inv0[b], inv[b])
    assert abs(vf - v0) < 1e-9
    print("  every bin back to its initial side AND amount; value restored"
          " -- PASS")


def check_one_way() -> None:
    print("=" * 72)
    print("CHECK 3 -- one way: price rises through the whole range and stays")
    print("=" * 72)
    a, pos = make_test_position()
    path = [a - 3, a - 2, a - 1, a, a + 1, a + 2, a + 3, a + 3]
    closes = [mid_price_ui(b) for b in path]
    print(f"  position: bins {a - 2}..{a + 2}, $100 per bin")
    print(f"  close path (active bin): {path}")

    inv = make_inventory(pos, closes[0])
    sol0, usdc0 = inventory_totals(inv)
    v0 = position_value(inv, closes[0])
    print(f"\n  initial inventory (close below the whole range -> all SOL):")
    print_inventory(inv, closes[0])

    sol_sold, usdc_received = 0.0, 0.0
    for i, c in enumerate(closes):
        inv, flips = update_inventory(inv, c)
        for _, old_side, old_amt, _, new_amt in flips:
            if old_side == "SOL":
                sol_sold += old_amt
                usdc_received += new_amt
        sol, usdc = inventory_totals(inv)
        print(f"    candle {i}: close {c:.4f} (active bin {path[i]})"
              f"  SOL {sol:.6f}  USDC {usdc:.4f}"
              f"  value {position_value(inv, c):.6f}")
        print_flips(flips)

    sol_end, usdc_end = inventory_totals(inv)
    vf = position_value(inv, closes[-1])
    assert sol_end == 0.0, "must end holding only USDC"
    assert abs(usdc_end - 500.0) < 1e-9  # each bin sold at its buy-in price
    assert abs(sol_sold - sol0) < 1e-12

    avg_sale = usdc_received / sol_sold
    hodl = sol0 * closes[-1] + usdc0  # never LP: just keep the t=0 tokens
    print(f"\n  ended with 0 SOL + {usdc_end:.4f} USDC (value {vf:.4f},"
          f" started marked at {v0:.4f})")
    print(f"  sold {sol_sold:.6f} SOL for {usdc_received:.4f} USDC"
          f" -> average sale price {avg_sale:.4f}")
    print(f"  final close: {closes[-1]:.4f}"
          f"  (sold {closes[-1] - avg_sale:.4f} below the final price)")
    print(f"  HODL comparison: keeping the initial {sol0:.6f} SOL would be"
          f" worth {hodl:.4f} now -> LP is {hodl - vf:.4f} behind -- PASS")


def run_real() -> None:
    """Inventory of the passive position over the configured dataset.

    Printed tables only; run_backtest.py draws the SOL-held chart, with
    the rebalancing strategy alongside this one.
    """
    from candle_bins import add_bins_to_dataframe
    from config import POSITION_BINS, USER_DEPOSIT
    from data_io import load_candles

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)

    center = active_bin(df["open"].iloc[0])
    half = POSITION_BINS // 2
    pos = make_position(USER_DEPOSIT, center - half, center + half)

    print(f"close: first {df['close'].iloc[0]:.4f}, "
          f"last {df['close'].iloc[-1]:.4f}")

    inv_df = run_inventory(df, pos)
    n_bins = pos.range_end - pos.range_start + 1
    print(f"\n--- passive: bins {pos.range_start}..{pos.range_end} "
          f"({n_bins} bins, ${pos.deposit_per_bin:.2f}/bin, UI "
          f"{bin_price_ui(pos.range_start):.2f}-"
          f"{bin_price_ui(pos.range_end + 1):.2f}) ---")
    for label, row, close in (
        ("start", inv_df.iloc[0], df["close"].iloc[0]),
        ("end  ", inv_df.iloc[-1], df["close"].iloc[-1]),
    ):
        pct_sol = row["sol_held"] * close / row["value"] * 100
        print(f"  {label}: {row['sol_held']:9.4f} SOL + "
              f"{row['usdc_held']:8.2f} USDC = ${row['value']:.2f} "
              f"({pct_sol:.0f}% in SOL)")
    print(f"  value range over the period: "
          f"${inv_df['value'].min():.2f} .. ${inv_df['value'].max():.2f}")


if __name__ == "__main__":
    checks = {"1": check_no_crossing, "2": check_round_trip,
              "3": check_one_way, "real": run_real}
    for key in sys.argv[1:] or ["1", "2", "3"]:
        checks[key]()
        print()
