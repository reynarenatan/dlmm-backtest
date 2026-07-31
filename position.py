"""A user's liquidity position and the fees it personally earns.

Model: USER_DEPOSIT spread equally across a bin range;
every bin has fixed TVL = BIN_TVL; the user owns deposit_per_bin / BIN_TVL
of each of their bins and earns that fraction of each bin's fees.
"""

from dataclasses import dataclass

import pandas as pd

from config import BIN_TVL, MAX_BINS, USER_DEPOSIT
from fees import accumulate_bin_fees


@dataclass(frozen=True)
class Position:
    range_start: int
    range_end: int
    deposit_per_bin: float
    shares: dict[int, float]  # bin_id -> user's fraction of that bin's TVL


def make_position(total_deposit: float, range_start: int, range_end: int,
                  bin_tvl=BIN_TVL) -> Position:
    """Build a Position with the deposit spread equally over the range.

    bin_tvl is normally the single BIN_TVL constant. The reference worked
    example needs per-bin TVLs, so a dict {bin_id: tvl} is also
    accepted — the difference is absorbed HERE, into the precomputed
    shares; Position and everything downstream never know about it.

    Every position in the engine is built here, so this is where the
    MAX_BINS ceiling is enforced.
    """
    n_bins = range_end - range_start + 1
    if n_bins > MAX_BINS:
        raise ValueError(
            f"position spans {n_bins} bins ({range_start}..{range_end}), "
            f"more than MAX_BINS={MAX_BINS}. Positions are a fixed "
            f"POSITION_BINS-wide range; a wider one cannot be opened."
        )
    deposit_per_bin = total_deposit / n_bins
    shares = {}
    for bin_id in range(range_start, range_end + 1):
        tvl = bin_tvl[bin_id] if isinstance(bin_tvl, dict) else bin_tvl
        shares[bin_id] = deposit_per_bin / tvl
    return Position(range_start, range_end, deposit_per_bin, shares)


def user_fee_for_candle(position: Position,
                        candle_bin_fees: dict[int, float]) -> float:
    """The user's slice of one candle's fees.

    For every touched bin inside the user's range, the user earns their
    share of that bin's fee; touched bins outside the range pay nothing
    (shares.get -> 0).
    """
    return sum(
        fee * position.shares.get(bin_id, 0.0)
        for bin_id, fee in candle_bin_fees.items()
    )


def run_position(df, position: Position, per_candle_bin_fees=None) -> pd.Series:
    """Per-candle user fees over a dataframe that already has touched_bins.

    Pass per_candle_bin_fees if the caller already accumulated them; the
    split does not depend on the position, so recomputing it per strategy
    is a wasted pass over the whole dataset.
    """
    if per_candle_bin_fees is None:
        _, per_candle_bin_fees = accumulate_bin_fees(df)
    return pd.Series(
        [user_fee_for_candle(position, fees) for fees in per_candle_bin_fees],
        index=df.index,
        name="user_fee",
    )


if __name__ == "__main__":
    # --- Example ---------------------------------------
    # $100 in each of three bins (total $300), TVLs 10k/11k/12k, candle
    # fees $100/$110/$105 -> user earns $1 + $1 + $0.875 = $2.875.
    X = -1287
    pos = make_position(
        300, X, X + 2,
        bin_tvl={X: 10_000, X + 1: 11_000, X + 2: 12_000},
    )
    candle = {X: 100.0, X + 1: 110.0, X + 2: 105.0}

    print("--- Example ---")
    for bin_id in range(X, X + 3):
        share = pos.shares[bin_id]
        print(f"bin {bin_id}: share {share:.6%} of ${candle[bin_id]:.2f} fee"
              f" -> ${candle[bin_id] * share:.6f}")
    total = user_fee_for_candle(pos, candle)
    print(f"user fee for the candle: ${total:.6f}")
    assert abs(total - 2.875) < 1e-9

    # --- A real position on the real data ---------------------------------
    from bin_math import get_bin_id_from_price
    from candle_bins import BIN_STEP, add_bins_to_dataframe, ui_to_raw
    from config import POSITION_BINS
    from data_io import load_candles

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)
    total_bin_fees, per_candle_bin_fees = accumulate_bin_fees(df)
    total_fees = sum(total_bin_fees.values())

    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), BIN_STEP)
    half = POSITION_BINS // 2
    pos = make_position(USER_DEPOSIT, center - half, center + half)
    user_fees = pd.Series(
        [user_fee_for_candle(pos, f) for f in per_candle_bin_fees],
        index=df.index)

    # Shares are equal across the range, so the user's total must be exactly
    # their per-bin share of the fees that landed INSIDE the range. (Before
    # positions were capped this was stated against every touched bin; a
    # capped position only ever sees its own slice of the bins.)
    in_range = sum(fee for b, fee in total_bin_fees.items()
                   if pos.range_start <= b <= pos.range_end)
    expected = pos.deposit_per_bin / BIN_TVL * in_range
    print(f"\n--- {POSITION_BINS}-bin position on the first candle's bin "
          f"({pos.range_start}..{pos.range_end}) ---")
    print(f"deposit per bin: ${pos.deposit_per_bin:.2f} "
          f"-> share per bin {pos.deposit_per_bin / BIN_TVL:.6%}")
    print(f"fees landing in range: ${in_range:.2f} of ${total_fees:.2f} pool "
          f"total ({in_range / total_fees:.1%})")
    print(f"user total fees: ${user_fees.sum():.4f} (expected ${expected:.4f})")
    assert abs(user_fees.sum() - expected) < 1e-6
    assert user_fees.sum() < total_fees  # sanity bound: never out-earn the pool

    days = len(df) / 1440
    print(f"per day: ${user_fees.sum() / days:.4f} on ${USER_DEPOSIT} "
          f"deposit -> {user_fees.sum() / days / USER_DEPOSIT:.4%}/day")

    # A range the price never entered earns exactly zero.
    far = max(total_bin_fees) + 100
    pos_far = make_position(USER_DEPOSIT, far, far + 9)
    assert run_position(df, pos_far).sum() == 0.0
    print(f"\nposition at {far}..{far + 9} (never touched): $0.00 -- OK")

    # --- The MAX_BINS ceiling ---------------------------------------------
    # The wide "cover every touched bin" scenario used to live here. It is
    # gone: its range could only be known after seeing the whole price path,
    # which is lookahead the engine now refuses to express.
    try:
        make_position(USER_DEPOSIT, center - half, center + half + 1)
    except ValueError as e:
        print(f"\n{POSITION_BINS + 1}-bin position rejected -- OK\n  {e}")
    else:
        raise AssertionError("a position wider than MAX_BINS must be rejected")
