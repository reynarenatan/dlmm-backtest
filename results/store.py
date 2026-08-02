"""Every run that has been executed, appended to one CSV.

One row per STRATEGY result, so a single execution of run_backtest.py
writes two rows -- the passive one and the rebalancing one -- sharing an
execution_id. That shape is what lets the history answer both questions:
filter to one execution_id to see what one execution did, or filter to a
strategy to see how it fared across every parameter set ever tried.

The columns come in three groups. The page builds its filters from
CONFIG_COLUMNS rather than naming any column itself, so a parameter added
to a run gets a filter for free once it appears here.

Nothing in this module computes anything. Every value is copied out of the
params and metrics dicts that backtest.run() already produced, which is
why a stored row can never disagree with the report printed beside it.

Rows are appended, never rewritten: running the backtest twice with the
same settings records two executions, because that is what happened.
"""

import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RUNS_PATH = Path(__file__).parent / "runs.csv"

# Which execution this row belongs to, and when it was saved.
IDENTITY_COLUMNS = ("execution_id", "timestamp")

# What the run was configured with. Every one of these gets a filter on the
# history page, chosen from the values present rather than named there.
CONFIG_COLUMNS = ("pool", "dataset", "start_date", "end_date", "bin_step",
                  "fee_rate", "pool_share", "bin_tvl", "deposit",
                  "position_bins", "strategy", "rebalance_cost")

# What it produced. Rates and APYs are stored as fractions (0.0004, not
# 0.04) and time_in_range as a percentage, exactly as metrics.py reports
# them -- converting on the way in would make the store disagree with the
# engine, so the page converts on the way out instead.
RESULT_COLUMNS = ("fees", "il", "costs", "net_pnl", "net_apy",
                  "gross_fee_apy", "break_even_fee_rate", "time_in_range",
                  "rebalance_count", "max_drawdown")

COLUMNS = IDENTITY_COLUMNS + CONFIG_COLUMNS + RESULT_COLUMNS


def _row(result, execution_id, timestamp) -> dict:
    """One strategy's result, flattened to the stored columns."""
    p, m = result["params"], result["metrics"]
    row = {
        "execution_id": execution_id,
        "timestamp": timestamp,
        # config
        "pool": p["pool"],
        "dataset": p["dataset"],
        "start_date": p["start"][:10],
        "end_date": p["end"][:10],
        "bin_step": p["bin_step"],
        "fee_rate": p["fee_rate"],
        "pool_share": p["pool_share"],
        "bin_tvl": p["bin_tvl"],
        "deposit": p["deposit"],
        "position_bins": p["position_bins"],
        "strategy": p["strategy"],
        # Recorded for every row including the passive one, where it is the
        # configured rate that never got charged, not a measurement.
        "rebalance_cost": p["rebalance_cost"],
        # result
        "fees": m["total_fees"],
        "il": m["total_il"],
        "costs": m["total_costs"],
        "net_pnl": m["net_pnl"],
        "net_apy": m["net_apy"],
        "gross_fee_apy": m["gross_fee_apy"],
        "break_even_fee_rate": m["break_even_fee_rate"],
        "time_in_range": m["time_in_range_pct"],
        "rebalance_count": m["rebalances"],
        "max_drawdown": m["max_drawdown"],
    }
    # COLUMNS is what the file is written and read with, so it has to be
    # exactly what this builds; a column added to one and not the other
    # would otherwise show up as a silently blank cell.
    assert set(row) == set(COLUMNS), set(row) ^ set(COLUMNS)
    return row


def save_run(results, path=RUNS_PATH) -> str:
    """Append one row per result and return the id linking them.

    `results` is the list of result dicts from one execution, in whatever
    order they were run. They share an execution_id and a timestamp: the
    execution is the unit, the rows are its strategies.
    """
    execution_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [_row(result, execution_id, timestamp) for result in results]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return execution_id


def load_runs(path=RUNS_PATH):
    """The history as a DataFrame, newest execution first.

    An empty frame with the right columns when nothing has been saved yet,
    so a reader can go straight to the columns without checking first.
    """
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    runs = pd.read_csv(path)
    return runs.sort_values(["timestamp", "strategy"],
                            ascending=[False, True], kind="stable"
                            ).reset_index(drop=True)


if __name__ == "__main__":
    runs = load_runs()
    print(f"{RUNS_PATH}: {len(runs)} rows, "
          f"{runs['execution_id'].nunique() if len(runs) else 0} executions")
    if len(runs):
        print(runs[["timestamp", "strategy", "bin_step", "fee_rate",
                    "net_pnl"]].to_string(index=False))
