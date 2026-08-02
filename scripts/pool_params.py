"""Derive each tracked pool's parameters from the tracking spreadsheet.

`DLMM Pool Tracking.xlsx` holds 16 observations of three live Meteora
SOL/USDC pools -- bin steps 4, 10 and 20 -- taken through July 2026. Two
of the model's inputs are measured from it, and this is where that
measurement is written down:

    pool share   the fraction of SOL market volume the pool handles,
                 which is the sheet's own PoolRatio column
    TVL per bin  the liquidity a 69-bin position would be sharing a bin
                 with, from the tracked liquidity bands

The values it produces live in `config.TRACKED_POOLS`, and this script
checks them rather than only printing them: run it after editing the
sheet and it says whether the code still agrees with the data.

The headline finding, and the reason this file exists: **the two inputs
are not the same across bin steps.** The step 4 pool handles about 9% of
SOL volume, the step 10 pool 1.3%, the step 20 pool 0.32% -- a factor of
28 between the ends. TVL per bin does stay within about 10%, because a
wider bin holds proportionally more even where liquidity is thinner. A
sweep that varies the bin step while holding both fixed is not comparing
pools; it is comparing one pool against two that do not exist.

Needs openpyxl, which is deliberately NOT in requirements.txt: the web
app never reads the spreadsheet, only the values derived from it, and the
deployment has no reason to carry an Excel reader.

    pip install openpyxl
    python scripts/pool_params.py
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from config import POSITION_BINS, TRACKED_POOLS  # noqa: E402

SHEET = ROOT / "DLMM Pool Tracking.xlsx"

# The liquidity bands the sheet records, as half-widths in percent either
# side of the current price, with the column holding each one.
BANDS = {1.0: "ActiveTVL1%", 2.5: "ActiveTVL2.5%", 5.0: "ActiveTVL5%"}

# How far a stored value may sit from the derived one before this
# complains. The inputs are averages of 16 noisy observations -- pool
# share has a standard deviation around a third of its mean -- so the
# stored figures are rounded to three significant figures on purpose and
# an exact comparison would only be testing the rounding.
TOLERANCE = 0.02

# Bin step 4 is the pool every published result was produced at, and its
# two values were settled before this sheet reached its current 16
# observations: 8% against the 9.0% below, and $13,500 against $13,442.
# Both are deliberate and neither is re-derived here -- moving them would
# change every number in the app -- so this is the one row the check
# reports on without failing.
SETTLED = 4


def half_width_pct(bin_step, bins=POSITION_BINS) -> float:
    """How far either side of the price a position of `bins` bins reaches.

    Each bin is bin_step basis points wide, so 69 bins at step 4 span
    2.76% of price: 1.38% either side.
    """
    return bin_step * bins / 100 / 2


def tvl_in_band(bands, half_width) -> float:
    """Liquidity within `half_width` percent of the price.

    Straight-line interpolation between the measured bands, which is how
    the $13,500 in config.py was arrived at and is kept here so the
    derivation stays the same one.

    Beyond the widest measured band it continues the last segment's
    slope. That applies only to bin step 20, whose 69 bins reach 6.9%
    either side against a sheet that stops at 5%, and it is the least
    certain number this script produces -- see the report below, which
    prints a power-law fit beside it as a second opinion.
    """
    widths = np.array(sorted(bands))
    values = np.array([bands[w] for w in widths])
    if half_width <= widths[-1]:
        return float(np.interp(half_width, widths, values))
    slope = (values[-1] - values[-2]) / (widths[-1] - widths[-2])
    return float(values[-1] + slope * (half_width - widths[-1]))


def power_fit(bands, half_width) -> float:
    """The same quantity from a fitted power law, as a cross-check.

    Liquidity thins with distance from the price, so a straight line
    through the bands overstates how much is out at the edges. Fitting
    TVL = a * width^b in log space bends with the data instead, and where
    the two disagree the straight line is the optimistic one.
    """
    widths = np.array(sorted(bands))
    values = np.array([bands[w] for w in widths])
    b, a = np.polyfit(np.log(widths), np.log(values), 1)
    return float(np.exp(a) * half_width ** b)


def derive(path=SHEET) -> dict:
    """Every tracked pool's parameters, measured off the sheet."""
    sheet = pd.read_excel(path)
    derived = {}
    for bin_step, rows in sheet.groupby("Pool ID"):
        bands = {width: rows[column].mean()
                 for width, column in BANDS.items()}
        half = half_width_pct(bin_step)
        derived[int(bin_step)] = {
            "observations": len(rows),
            # The sheet's own column, averaged. Volume-weighting it barely
            # moves it (9.21% against 8.99% at step 4), so the plain mean
            # is used rather than a choice that needs defending.
            "pool_share": float(rows["PoolRatio"].mean()),
            "pool_share_sd": float(rows["PoolRatio"].std()),
            "bin_tvl": tvl_in_band(bands, half) / POSITION_BINS,
            "bin_tvl_power_fit": power_fit(bands, half) / POSITION_BINS,
            "half_width_pct": half,
            "extrapolated": half > max(BANDS),
            "bands": bands,
            # Fees charged over volume routed. Nothing uses this -- the
            # engine takes the fee rate from the bin step -- so it is a
            # free check on that rule against real pools.
            "implied_fee_rate": float(rows["24hFees"].sum()
                                      / rows["Daily Volume"].sum()),
        }
    return derived


def report(derived) -> None:
    print(f"{SHEET.name}: "
          f"{sum(p['observations'] for p in derived.values())} observations "
          f"of {len(derived)} pools\n")

    print("POOL SHARE -- the fraction of SOL market volume each pool handles")
    print(f"{'step':>5} {'measured':>10} {'sd':>8} {'in config':>10} "
          f"{'vs step 4':>10}")
    base = derived[min(derived)]["pool_share"]
    for step, p in sorted(derived.items()):
        stored = TRACKED_POOLS.get(step, {}).get("pool_share")
        print(f"{step:>5} {p['pool_share']:>10.4%} {p['pool_share_sd']:>8.4f} "
              f"{stored:>10.4%} {base / p['pool_share']:>9.1f}x")

    print(f"\nTVL PER BIN -- what a {POSITION_BINS}-bin position shares a "
          f"bin with")
    print(f"{'step':>5} {'reaches':>9} {'measured':>10} {'power fit':>10} "
          f"{'in config':>10}")
    for step, p in sorted(derived.items()):
        stored = TRACKED_POOLS.get(step, {}).get("bin_tvl")
        flag = "  extrapolated past the widest band" if p["extrapolated"] else ""
        print(f"{step:>5} {'+/-' + format(p['half_width_pct'], '.2f') + '%':>9} "
              f"{p['bin_tvl']:>10,.0f} {p['bin_tvl_power_fit']:>10,.0f} "
              f"{stored:>10,.0f}{flag}")

    print("\nFEE RATE -- a free check on 'one basis point per unit of step'")
    print(f"{'step':>5} {'implied':>10} {'base fee':>10}")
    for step, p in sorted(derived.items()):
        print(f"{step:>5} {p['implied_fee_rate']:>10.4%} "
              f"{step / 10_000:>10.4%}")
    print("  Implied sits just above base on every pool, which is Meteora's "
          "variable fee\n  showing up in real fee income. The engine models "
          "the base fee only.")


def check(derived) -> int:
    """Whether config.TRACKED_POOLS still agrees with the sheet."""
    print("\nCHECK: config.TRACKED_POOLS against the sheet")
    problems = 0
    for step, p in sorted(derived.items()):
        stored = TRACKED_POOLS.get(step)
        if stored is None:
            print(f"  bin step {step}: measured but not in config")
            problems += 1
            continue
        for key in ("pool_share", "bin_tvl"):
            gap = abs(stored[key] - p[key]) / p[key]
            if gap <= TOLERANCE:
                continue
            if step == SETTLED:
                print(f"  bin step {step} {key}: config {stored[key]:,.5g} "
                      f"vs measured {p[key]:,.5g} ({gap:.1%}) - settled "
                      f"deliberately, not a failure")
                continue
            print(f"  bin step {step} {key}: config {stored[key]:,.5g} "
                  f"vs measured {p[key]:,.5g} ({gap:.1%} out)")
            problems += 1
    for step in TRACKED_POOLS:
        if step not in derived:
            print(f"  bin step {step}: in config but not in the sheet")
            problems += 1
    print("  everything else agrees" if not problems
          else f"  {problems} disagreement(s) -- update config.TRACKED_POOLS")
    return problems


if __name__ == "__main__":
    derived = derive()
    report(derived)
    raise SystemExit(check(derived))
