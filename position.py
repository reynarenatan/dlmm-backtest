"""A user's liquidity position and the fees it personally earns.

Model: USER_DEPOSIT spread equally across a bin range;
every bin has fixed TVL = BIN_TVL; the user owns deposit_per_bin / BIN_TVL
of each of their bins and earns that fraction of each bin's fees.
"""

from dataclasses import dataclass

import pandas as pd

from config import BIN_TVL, USER_DEPOSIT
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
    """
    n_bins = range_end - range_start + 1
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


def run_position(df, position: Position) -> pd.Series:
    """Per-candle user fees over a dataframe that already has touched_bins."""
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

    # --- Full-range and never-entered positions on the real CSV ------------
    from candle_bins import BIN_STEP, add_bins_to_dataframe
    from data_io import load_candles

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)
    total_bin_fees, _ = accumulate_bin_fees(df)
    total_fees = sum(total_bin_fees.values())

    lo, hi = min(total_bin_fees), max(total_bin_fees)
    n_bins = hi - lo + 1
    pos_all = make_position(USER_DEPOSIT, lo, hi)
    user_fees = run_position(df, pos_all)

    # Equal shares everywhere, so the user's total must be exactly their
    # share of ALL fees: (deposit_per_bin / BIN_TVL) * total_fees.
    expected = pos_all.deposit_per_bin / BIN_TVL * total_fees
    print(f"\n--- position covering all touched bins ({lo}..{hi}, "
          f"{n_bins} bins) ---")
    print(f"deposit per bin: ${pos_all.deposit_per_bin:.2f} "
          f"-> share per bin {pos_all.deposit_per_bin / BIN_TVL:.6%}")
    print(f"user total fees: ${user_fees.sum():.4f} (expected ${expected:.4f})")
    assert abs(user_fees.sum() - expected) < 1e-6
    assert user_fees.sum() < total_fees  # sanity bound: never out-earn the pool

    days = len(df) / 1440
    print(f"per day: ${user_fees.sum() / days:.4f} on ${USER_DEPOSIT} "
          f"deposit -> {user_fees.sum() / days / USER_DEPOSIT:.4%}/day")

    # A range the price never entered earns exactly zero.
    pos_far = make_position(USER_DEPOSIT, hi + 100, hi + 109)
    assert run_position(df, pos_far).sum() == 0.0
    print(f"\nposition at {hi + 100}..{hi + 109} (never touched): $0.00 -- OK")
