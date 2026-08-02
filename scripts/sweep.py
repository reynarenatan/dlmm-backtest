"""Seed the run history with a spread of scenarios, run locally.

A run saved from the hosted site lives on that container's disk and goes
when the container is rebuilt. The rows that last are the ones committed
to the repository, which means they have to be produced here and checked
in -- this script is how.

It runs the four preset windows crossed with three bin steps, twelve
configurations, two strategies each: 24 rows covering a peak, a crash, a
flat month and the full year at a tight, a middling and a wide grid.

Everything is reused from `runner`, deliberately. The configurations it
builds are the ones the Run it yourself page builds for the same
settings, so a saved row is found by `find_saved` when someone picks
those settings on the site -- the page answers from the CSV instead of
spending half a minute on the engine. Writing the parameters out again
here would look identical and match nothing the day the two drift.

A bin step is not a dial on one pool: it names a different pool, so the
fee rate, the pool share and the TVL per bin all move with it, straight
out of the tracking spreadsheet by way of config.TRACKED_POOLS. Only the
deposit and the position width are held fixed.

The pool share is what makes this matter. The tracked pools handle 8%,
1.30% and 0.315% of SOL market volume at bin steps 4, 10 and 20 -- a
factor of 28 across the range, because trading concentrates in the
tightest grid. An earlier version of this sweep held it at 8% for all
three and produced a bin step 20 pool earning $19,189 a year on a $1,000
deposit. Nothing was wrong with the engine; it was pricing a pool that
does not exist.

Configurations already in the file are skipped, so running this twice
does not record the same work twice, and a sweep interrupted half way
picks up where it left off.

    python scripts/sweep.py
"""

import os
import sys
import time
from pathlib import Path

# Run from anywhere: the project root has to be importable, and
# config.DATA_FILE is a path relative to it.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import runner                                          # noqa: E402
from results.store import RUNS_PATH, load_runs, save_run  # noqa: E402
from webdata import money, signed_money                 # noqa: E402

# Tight, middling and wide. Step 4 is what every published result uses;
# 10 and 20 widen each bin to 0.10% and 0.20% of price, so the same 69
# bins cover a range five times as wide at a fifth of the fee share.
BIN_STEPS = (4, 10, 20)


def configurations():
    """Every preset window crossed with every bin step.

    The window is sliced once per preset and the dates are taken from the
    candles it actually contains, not from the dates asked for -- that is
    what the store records, and so what a later lookup compares against.
    """
    for name, preset in runner.PRESETS.items():
        candles = runner.window(preset["start"], preset["end"])
        first = str(candles["timestamp"].iloc[0].date())
        last = str(candles["timestamp"].iloc[-1].date())
        for bin_step in BIN_STEPS:
            yield name, len(candles), runner.make_config(
                start_date=first, end_date=last, bin_step=bin_step)


def already_saved(config, runs) -> bool:
    """Whether every strategy of this configuration is already on file."""
    return all(runner.find_saved(config, strategy, runs) is not None
               for strategy in runner.STRATEGIES)


def execute(config) -> list:
    """Both strategies over one configuration.

    The window is binned and its fees split once and handed to both, which
    is the whole reason run_strategy takes them: the two strategies differ
    only in how the position moves, not in what the candles did.
    """
    df = runner.prepared(config)
    fees = runner.fee_split(config, df)
    return [runner.run_strategy(config, strategy, df=df, fees=fees)
            for strategy in runner.STRATEGIES]


def describe(result) -> str:
    m, p = result["metrics"], result["params"]
    return (f"    {p['strategy']:<12} fees {money(m['total_fees']):>10}  "
            f"IL {signed_money(m['total_il']):>11}  "
            f"costs {money(m['total_costs']):>9}  "
            f"net {signed_money(m['net_pnl']):>11}  "
            f"in range {m['time_in_range_pct']:5.1f}%  "
            f"{m['rebalances']:,} rebalances")


def main() -> None:
    runs = load_runs()
    print(f"{RUNS_PATH}: {len(runs)} rows before the sweep")

    saved = skipped = 0
    started = time.perf_counter()
    for name, candles, config in configurations():
        header = f"{name} at bin step {config['bin_step']}"
        if already_saved(config, runs):
            print(f"\n{header}: already saved, skipping")
            skipped += 1
            continue

        print(f"\n{header}: {candles:,} candles, fee rate "
              f"{config['fee_rate'] * 100:.2f}%")
        clock = time.perf_counter()
        results = execute(config)
        run_id = save_run(results)
        for result in results:
            print(describe(result))
        print(f"    saved as {run_id} in {time.perf_counter() - clock:.1f}s")
        saved += 1
        # Re-read so a configuration cannot be written twice in one sweep.
        runs = load_runs()

    print(f"\n{saved} executions saved, {skipped} already on file, "
          f"{len(runs)} rows total, {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()
