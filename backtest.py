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
from config import (BIN_TVL, DATA_FILE, FEE_DISTRIBUTION, FEE_RATE, POOL,
                    POOL_SHARE, POSITION_BINS, REBALANCE_COST, USER_DEPOSIT)
from data_io import load_candles
from fees import accumulate_bin_fees
from inventory import active_bin, run_inventory
from metrics import compute_metrics
from pnl import hodl_series
from position import make_position, run_position
from strategies import run_rebalancing

STRATEGIES = ("passive", "rebalancing")


def prepare(df=None, path=None, bin_step=None):
    """Load candles and attach touched_bins -- the input every run shares.

    touched_bins is only meaningful for the bin step it was built with, so
    the step used is recorded on the frame and a frame prepared at a
    different step is re-binned rather than trusted. Skipping that check
    would silently run one bin step's position against another's grid.
    """
    bin_step = BIN_STEP if bin_step is None else bin_step
    if df is None:
        df = load_candles(path)
    if df.attrs.get("bin_step") != bin_step:
        df = add_bins_to_dataframe(df, bin_step)
        df.attrs["bin_step"] = bin_step
    return df


def run(df=None, strategy="rebalancing", path=None, fee_rate=None,
        cost_rate=None, per_candle_bin_fees=None, bin_step=None,
        pool_share=None, bin_tvl=None, deposit=None, position_bins=None,
        fee_distribution=None) -> dict:
    """Run one strategy over one dataset and return its result dict.

    Every parameter defaults to None, meaning "use the config value", so
    the command line behaves exactly as it did when none of them existed.
    Overriding them runs a different pool in the same process without
    editing config.py: that is what lets the break-even fee rate be
    checked by re-running, and what lets a web page run a configuration
    the user chose.

    per_candle_bin_fees can be passed in when several runs share a
    dataset AND a fee rate AND a pool, to skip repeating the split. It is
    the caller's job not to hand over a split built for a different pool;
    nothing here can tell.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy!r}; "
                         f"expected one of {STRATEGIES}")
    fee_rate = FEE_RATE if fee_rate is None else fee_rate
    cost_rate = REBALANCE_COST if cost_rate is None else cost_rate
    bin_step = BIN_STEP if bin_step is None else bin_step
    pool_share = POOL_SHARE if pool_share is None else pool_share
    bin_tvl = BIN_TVL if bin_tvl is None else bin_tvl
    deposit = USER_DEPOSIT if deposit is None else deposit
    position_bins = POSITION_BINS if position_bins is None else position_bins
    fee_distribution = (FEE_DISTRIBUTION if fee_distribution is None
                        else fee_distribution)

    df = prepare(df, path, bin_step)
    if per_candle_bin_fees is None:
        _, per_candle_bin_fees = accumulate_bin_fees(
            df, fee_distribution=fee_distribution, fee_rate=fee_rate,
            pool_share=pool_share, bin_step=bin_step)

    # Both strategies open the same range on the first candle, so they
    # share a HODL baseline: the same initial tokens, held untouched.
    center = get_bin_id_from_price(ui_to_raw(df["open"].iloc[0]), bin_step)
    half = position_bins // 2
    pos = make_position(deposit, center - half, center + half, bin_tvl)

    if strategy == "passive":
        inv = run_inventory(df, pos, bin_step)
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
                                        width=position_bins,
                                        cost_rate=cost_rate, deposit=deposit,
                                        bin_tvl=bin_tvl, bin_step=bin_step)

    hodl = hodl_series(pos, df["close"], bin_step)
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
    series["active_bin"] = [active_bin(c, bin_step) for c in series["close"]]
    # A candle is "in range" exactly when the position earned from it.
    # That is what a user means by in range, and it needs no separate
    # definition: the fee IS computed from the bins the candle touched
    # inside the position.
    series["in_range"] = series["fee"] > 0

    params = {
        "pool": POOL,
        "dataset": path or DATA_FILE,
        "strategy": strategy,
        "candles": len(df),
        "days": len(df) / 1440,
        "start": str(series["timestamp"].iloc[0]),
        "end": str(series["timestamp"].iloc[-1]),
        "deposit": deposit,
        "position_bins": position_bins,
        "bin_step": bin_step,
        "pool_share": pool_share,
        "fee_rate": fee_rate,
        "fee_distribution": fee_distribution,
        "bin_tvl": bin_tvl,
        "rebalance_cost": cost_rate,
    }
    return {
        "params": params,
        "series": series,
        "events": events,
        "metrics": compute_metrics(series, events, params),
    }
