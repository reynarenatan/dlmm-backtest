"""One backtest run, returned as data.

`run()` computes a strategy over a candle dataset and hands back a result
dict. It prints nothing and draws nothing: reporting lives in report.py,
charts in charts.py, and both take the dict this produces. The website
will call `run()` the same way the command line does.

The result dict has four keys:

    params   flat, JSON-serialisable: what the run was configured with
    series   per-candle DataFrame: everything a chart needs
    events   one dict per rebalance (empty for the passive strategy)
    metrics  flat, JSON-serialisable: the numbers a report quotes

params and metrics are the halves worth persisting; series and events are
the raw material they were derived from.
"""

import pandas as pd

from bin_math import get_bin_id_from_price
from candle_bins import BIN_STEP, add_bins_to_dataframe, ui_to_raw
from config import (BIN_TVL, DATA_FILE, FEE_DISTRIBUTION, FEE_RATE,
                    POOL_SHARE, POSITION_BINS, REBALANCE_COST, USER_DEPOSIT)
from data_io import load_candles
from fees import accumulate_bin_fees
from inventory import active_bin, run_inventory
from metrics import compute_metrics
from pnl import hodl_series
from position import make_position, run_position
from strategies import run_rebalancing

STRATEGIES = ("passive", "rebalancing")


def prepare(df=None, path=None):
    """Load candles and attach touched_bins -- the input every run shares."""
    if df is None:
        df = load_candles(path)
    if "touched_bins" not in df.columns:
        df = add_bins_to_dataframe(df, BIN_STEP)
    return df


def run(df=None, strategy="rebalancing", path=None, fee_rate=None,
        cost_rate=None, per_candle_bin_fees=None) -> dict:
    """Run one strategy over one dataset and return its result dict.

    fee_rate / cost_rate override the config for this run only; that is
    what lets the break-even fee rate be checked by re-running rather
    than by re-deriving the formula that produced it.

    per_candle_bin_fees can be passed in when several runs share a
    dataset AND a fee rate, to skip repeating the split.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}; "
                         f"expected one of {STRATEGIES}")
    fee_rate = FEE_RATE if fee_rate is None else fee_rate
    cost_rate = REBALANCE_COST if cost_rate is None else cost_rate

    df = prepare(df, path)
    if per_candle_bin_fees is None:
        _, per_candle_bin_fees = accumulate_bin_fees(df, fee_rate=fee_rate)

    # Both strategies open the same range on the first candle, so they
    # share a HODL baseline: the same initial tokens, held untouched.
    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), BIN_STEP)
    half = POSITION_BINS // 2
    pos = make_position(USER_DEPOSIT, center - half, center + half)

    if strategy == "passive":
        inv = run_inventory(df, pos)
        frame = pd.DataFrame({
            "value": inv["value"],
            "fee": run_position(df, pos, per_candle_bin_fees),
            "cost": 0.0,
            "sol_held": inv["sol_held"],
            "usdc_held": inv["usdc_held"],
            "range_start": pos.range_start,
            "range_end": pos.range_end,
        })
        events = []
    else:
        frame, events = run_rebalancing(df, per_candle_bin_fees,
                                        cost_rate=cost_rate)

    hodl = hodl_series(pos, df["close"])
    cum_fees = frame["fee"].cumsum()
    cum_costs = frame["cost"].cumsum()

    series = pd.DataFrame({
        "timestamp": df["timestamp"].values,
        "close": df["close"].values,
        "value": frame["value"].values,
        "hodl": hodl.values,
        "fee": frame["fee"].values,
        "cost": frame["cost"].values,
        "cum_fees": cum_fees.values,
        "cum_costs": cum_costs.values,
        "sol_held": frame["sol_held"].values,
        "usdc_held": frame["usdc_held"].values,
        "range_start": frame["range_start"].values,
        "range_end": frame["range_end"].values,
    })
    # il is the price effect alone: costs are added back here and carried
    # as their own term, so net_pnl = fees + il - costs holds for both
    # strategies (costs are identically zero for the passive one).
    series["il"] = series["value"] - series["hodl"] + series["cum_costs"]
    series["net_pnl"] = series["cum_fees"] + series["value"] - series["hodl"]
    series["active_bin"] = [active_bin(c) for c in series["close"]]
    # A candle is "in range" exactly when the position earned from it.
    # That is what a user means by in range, and it needs no separate
    # definition: the fee IS computed from the bins the candle touched
    # inside the position.
    series["in_range"] = series["fee"] > 0

    params = {
        "dataset": path or DATA_FILE,
        "strategy": strategy,
        "candles": len(df),
        "days": len(df) / 1440,
        "start": str(series["timestamp"].iloc[0]),
        "end": str(series["timestamp"].iloc[-1]),
        "deposit": USER_DEPOSIT,
        "position_bins": POSITION_BINS,
        "bin_step": BIN_STEP,
        "pool_share": POOL_SHARE,
        "fee_rate": fee_rate,
        "fee_distribution": FEE_DISTRIBUTION,
        "bin_tvl": BIN_TVL,
        "rebalance_cost": cost_rate,
    }
    return {
        "params": params,
        "series": series,
        "events": events,
        "metrics": compute_metrics(series, events, params),
    }
