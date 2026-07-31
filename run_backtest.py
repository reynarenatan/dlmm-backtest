"""Run both strategies, print their reports, write the charts to outputs/.

Thin on purpose. The run is backtest.run(), the numbers are metrics.py,
the words are report.py and the pictures are charts.py; this file only
decides what to run and where the files land. A web front end skips it
and calls the same three modules.

    python run_backtest.py            # both strategies
    python run_backtest.py passive    # just one
"""

import os
import sys

import matplotlib.pyplot as plt

import charts
from backtest import prepare, run
from config import BIN_STEP
from fees import accumulate_bin_fees
from report import print_report

OUTPUT_DIR = "outputs"
DPI = 150

# Chart per strategy: (filename stem, chart function).
PER_RUN = [
    ("price_with_range_band", charts.price_with_range_band),
    ("pnl_decomposition", charts.pnl_decomposition),
    ("position_vs_hodl", charts.position_vs_hodl),
    ("drawdown", charts.drawdown_curve),
    ("position_value", charts.position_value_over_time),
]

# Chart across strategies, drawn only when there is more than one run.
COMPARISON = [
    ("cumulative_fees", charts.cumulative_fees),
    ("net_pnl_comparison", charts.net_pnl_comparison),
]


def save(fig, name):
    path = f"{OUTPUT_DIR}/{name}.png"
    fig.savefig(path, dpi=DPI, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  {path}")
    return path


def cost_sensitivity(df, per_candle_bin_fees, rates=(0.0, 0.001, 0.005)):
    """Does the rebalancing verdict survive a different trading cost?"""
    print("\nREBALANCE_COST sensitivity (rebalancing):")
    for rate in rates:
        m = run(df, strategy="rebalancing", cost_rate=rate,
                per_candle_bin_fees=per_candle_bin_fees)["metrics"]
        print(f"  cost {rate:.2%}: net PnL ${m['net_pnl']:+8.2f} "
              f"(total costs ${m['total_costs']:.2f}, "
              f"{m['rebalances']} rebalances, "
              f"ends ${m['final_value']:,.2f})")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    strategies = sys.argv[1:] or ["passive", "rebalancing"]

    df = prepare()
    total_bin_fees, per_candle_bin_fees = accumulate_bin_fees(df)

    results = []
    for strategy in strategies:
        result = run(df, strategy=strategy,
                     per_candle_bin_fees=per_candle_bin_fees)
        print_report(result)
        results.append(result)

    if "rebalancing" in strategies:
        cost_sensitivity(df, per_candle_bin_fees)

    print(f"\ncharts -> {OUTPUT_DIR}/")
    for result in results:
        for stem, draw in PER_RUN:
            save(draw(result), f"{stem}_{result['params']['strategy']}")

    save(charts.fee_per_bin(total_bin_fees, BIN_STEP), "fee_per_bin")

    if len(results) > 1:
        for stem, draw in COMPARISON:
            save(draw(results), stem)
