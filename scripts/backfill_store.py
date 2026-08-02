"""Widen results/runs.csv to columns the store did not used to keep.

`save_run` appends, and it only writes a header when the file is empty, so
a row with new columns cannot simply be appended to a file whose header
does not have them. The file has to be rewritten, and the values for runs
that happened before the column existed have to come from somewhere.

They come from re-running them. A run is a pure function of its stored
configuration, so replaying a stored row reproduces it -- and that is the
safety net here: **every column that already had a value is checked
against the replay before anything is written**. If a replay disagrees,
the run was not reproducible and the file is left alone rather than being
rewritten from a source that cannot be trusted.

What is not re-derived is a row's identity. execution_id, timestamp and
row order are carried across untouched, so the history keeps saying when
each run happened rather than when this script was run.

Re-runnable: a row that already has every column is left exactly as it is,
so this costs nothing on a file that has already been widened.

    python scripts/backfill_store.py
"""

import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import runner                                    # noqa: E402
from results.store import COLUMNS, RUNS_PATH     # noqa: E402

# Stored column -> the metrics key it was copied from, for the replay to
# compare against. This is store._row's mapping read backwards; it is
# written out rather than derived so that a column whose meaning changes
# shows up here as a decision rather than passing silently.
FROM_METRICS = {
    "fees": "total_fees", "il": "total_il", "costs": "total_costs",
    "net_pnl": "net_pnl", "net_apy": "net_apy",
    "gross_fee_apy": "gross_fee_apy",
    "break_even_fee_rate": "break_even_fee_rate",
    "time_in_range": "time_in_range_pct", "rebalance_count": "rebalances",
    "max_drawdown": "max_drawdown", "entry_value": "entry_value",
    "final_value": "final_value", "hodl_final_value": "hodl_final_value",
}

TOLERANCE = 1e-9


def config_of(row) -> dict:
    """A stored row's configuration, in the shape runner runs.

    Built through runner.make_config for the same reason the history page
    builds it that way: it has to come out identical to the configuration
    that produced the row, or the replay is of something else.
    """
    return runner.make_config(
        start_date=row["start_date"], end_date=row["end_date"],
        bin_step=int(row["bin_step"]), fee_rate=float(row["fee_rate"]),
        pool_share=float(row["pool_share"]), bin_tvl=float(row["bin_tvl"]),
        deposit=float(row["deposit"]),
        position_bins=int(row["position_bins"]),
        rebalance_cost=float(row["rebalance_cost"]), pool=row["pool"],
        dataset=row["dataset"])


def replay(rows) -> dict:
    """Every row of one execution, re-run; keyed by strategy.

    The rows of an execution share a window and a pool and differ only in
    the strategy, so the candles are binned and the fees split once for
    all of them.
    """
    config = config_of(rows[0])
    df = runner.prepared(config)
    fees = runner.fee_split(config, df)
    return {row["strategy"]:
            runner.run_strategy(config, row["strategy"], df=df, fees=fees)
            for row in rows}


def disagreements(row, metrics) -> list:
    """Where a replay does not reproduce what was stored."""
    out = []
    for column, key in FROM_METRICS.items():
        stored = row.get(column, "")
        if stored in (None, ""):
            continue  # nothing to contradict: this is a column being filled
        fresh = metrics[key]
        if fresh is None:
            out.append(f"{column}: stored {stored}, replay blank")
        elif abs(float(fresh) - float(stored)) > TOLERANCE:
            out.append(f"{column}: stored {stored}, replay {fresh!r}")
    return out


def needs_filling(row) -> bool:
    return any(row.get(column, "") in (None, "") for column in COLUMNS)


def main() -> int:
    if not RUNS_PATH.exists():
        print(f"{RUNS_PATH} does not exist; nothing to widen")
        return 0

    with RUNS_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    missing = [c for c in COLUMNS if c not in (rows[0] if rows else {})]
    print(f"{RUNS_PATH}: {len(rows)} rows, "
          f"{len(missing)} column(s) to add: {', '.join(missing) or 'none'}")

    todo = [row for row in rows if needs_filling(row)]
    if not todo:
        print("every row already has every column; nothing to do")
        return 0

    executions, order = {}, []
    for row in todo:
        executions.setdefault(row["execution_id"], []).append(row)
        if row["execution_id"] not in order:
            order.append(row["execution_id"])

    started, problems = time.perf_counter(), []
    for execution_id in order:
        group = executions[execution_id]
        first = group[0]
        clock = time.perf_counter()
        results = replay(group)
        for row in group:
            metrics = results[row["strategy"]]["metrics"]
            bad = disagreements(row, metrics)
            if bad:
                problems += [f"{execution_id} {row['strategy']}: {b}"
                             for b in bad]
                continue
            for column, key in FROM_METRICS.items():
                if row.get(column, "") in (None, ""):
                    row[column] = metrics[key]
        print(f"  {execution_id}  {first['start_date']}..{first['end_date']} "
              f"step {first['bin_step']:>2}  {len(group)} row(s)  "
              f"{time.perf_counter() - clock:.1f}s"
              f"{'  MISMATCH' if bad else ''}")

    if problems:
        print(f"\n{len(problems)} disagreement(s) between the file and a "
              f"replay -- nothing written:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    with RUNS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in COLUMNS}
                         for row in rows)
    print(f"\n{len(todo)} row(s) filled, {len(rows)} written with "
          f"{len(COLUMNS)} columns, {time.perf_counter() - started:.0f}s")
    print("every value that was already there reproduced to within "
          f"{TOLERANCE:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
