"""The one place the web app runs the engine.

Every other page reads precomputed values; this module exists for the one
page that does not. It is kept out of `views/` for the same reason
`precompute.py` is kept out: what to compute is a separate question from
how to lay it out.

Three things make a page that runs a backtest bearable:

1. A saved run is never recomputed. `find_saved` looks the configuration
   up in results/runs.csv and returns the metrics from there, so a
   configuration someone has already run costs a CSV read rather than
   half a minute of engine.
2. What does get computed is cached on the configuration, so moving an
   unrelated widget does not run it again.
3. The wait is quoted before it is spent, from measured rates.

The candle window is sliced BEFORE the engine sees it, so a run over one
month is a run over one month's data -- not a year's work thrown away
afterwards.
"""

import io
from datetime import date

import pandas as pd
import streamlit as st

import charts
from backtest import prepare, run
from config import (BIN_STEP, BIN_TVL, DATA_FILE, FEE_DISTRIBUTION, POOL,
                    POOL_SHARE, POSITION_BINS, REBALANCE_COST, USER_DEPOSIT)
from data_io import load_candles
from fees import accumulate_bin_fees
from results.store import CONFIG_COLUMNS, load_runs, save_run

STRATEGIES = ("passive", "rebalancing")

# ----------------------------------------------------------------------
# Preset windows
# ----------------------------------------------------------------------
# Chosen from the dataset rather than picked off a calendar: the peak is
# the month holding the year's highest close, the crash is the month with
# the largest fall and the widest range, and the flat market is the most
# recent month and also the narrowest in the year. Every figure quoted in
# a description was measured off the candles.
PRESETS = {
    "Sept 2025 peak": {
        "start": date(2025, 9, 1),
        "end": date(2025, 9, 30),
        "dates": "1-30 Sep 2025",
        "help": "The top of the year. SOL climbed from 200.47 to close at "
                "247.54 on the 18th, the highest daily close in the "
                "dataset, and touched 253.60 intraday before easing back "
                "to 208.68. Up 4.1% over the month, with a 32.9% spread "
                "between its low and its high.",
    },
    "Feb 2026 crash": {
        "start": date(2026, 2, 1),
        "end": date(2026, 2, 28),
        "dates": "1-28 Feb 2026",
        "help": "The worst month in the dataset. SOL opened at 105.24 and "
                "closed at 84.34, down 19.9%, including a fall from 104.47 "
                "to 78.23 in the three days to 5 February. It set the "
                "year's low of 67.51 and swung 57.8% between low and high.",
    },
    "Recent flat market": {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 28),
        "dates": "1-28 Jul 2026",
        "help": "The most recent month, and the quietest in the dataset: "
                "SOL started at 73.56 and finished at 73.14, a change of "
                "-0.6%, inside a 15.6% low-to-high range. The nearest "
                "thing here to a market going nowhere.",
    },
    "Full year": {
        "start": date(2025, 7, 28),
        "end": date(2026, 7, 28),
        "dates": "28 Jul 2025 - 28 Jul 2026",
        "help": "The whole dataset, and the configuration the Results page "
                "reports. SOL fell 62.1% over these twelve months, so it "
                "is one long bear market rather than a neutral sample.",
    },
}

DEFAULT_PRESET = "Full year"

# ----------------------------------------------------------------------
# How long a run takes
# ----------------------------------------------------------------------
# Measured at 10k / 40k / 120k / 525k candles. Cost per candle was
# constant across all four (0.0374 s per 1,000 for both strategies
# together), so a single rate per phase is enough -- the old superlinear
# behaviour came from position width, which is now capped at MAX_BINS.
#
# These are development-machine rates. A hosted container is slower, so
# the estimate is a floor, and the page says so rather than implying a
# precision it does not have.
SECONDS_PER_1000_CANDLES = {
    "shared": 0.0073,       # slicing, binning, and splitting fees per bin
    "passive": 0.0140,
    "rebalancing": 0.0163,
}
SECONDS_PER_CHART = 0.5
CHARTS_PER_STRATEGY = 4


def estimate_seconds(candles, strategies) -> float:
    """Engine time plus chart time for one run, in seconds."""
    per_1000 = SECONDS_PER_1000_CANDLES["shared"] + sum(
        SECONDS_PER_1000_CANDLES[s] for s in strategies)
    return (candles / 1000 * per_1000
            + SECONDS_PER_CHART * CHARTS_PER_STRATEGY * len(strategies))


def format_duration(seconds) -> str:
    if seconds < 1:
        return "under a second"
    if seconds < 60:
        return f"about {seconds:.0f} seconds"
    return f"about {seconds / 60:.1f} minutes"


# ----------------------------------------------------------------------
# Candles
# ----------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def all_candles(path=DATA_FILE):
    """The whole dataset, read once per process and shared read-only.

    cache_resource rather than cache_data because this is half a million
    rows that nothing mutates: cache_data hands back a fresh copy on
    every call, which for a frame this size is real work on every rerun.
    Callers slice it, and both `window` and `prepare` copy before writing,
    so the shared frame is never modified.
    """
    return load_candles(path)


def window(start: date, end: date, path=DATA_FILE):
    """The candles between two dates, end inclusive.

    Compared as timestamps rather than by converting a column of half a
    million of them to dates, which this runs on every interaction.

    Returned unbinned: which bins a candle touched depends on the bin
    step, so binning belongs to the run, not to the slice.
    """
    candles = all_candles(path)
    stamps = candles["timestamp"]
    low = pd.Timestamp(start, tz=stamps.dt.tz)
    high = pd.Timestamp(end, tz=stamps.dt.tz) + pd.Timedelta(days=1)
    return candles[(stamps >= low) & (stamps < high)].reset_index(drop=True)


def dataset_bounds(path=DATA_FILE) -> tuple:
    """(first date, last date) available, for the date picker's limits."""
    stamps = all_candles(path)["timestamp"]
    return stamps.iloc[0].date(), stamps.iloc[-1].date()


# ----------------------------------------------------------------------
# A configuration
# ----------------------------------------------------------------------

def make_config(start_date, end_date, bin_step=BIN_STEP, fee_rate=None,
                pool_share=POOL_SHARE, bin_tvl=BIN_TVL, deposit=USER_DEPOSIT,
                position_bins=POSITION_BINS, rebalance_cost=REBALANCE_COST,
                pool=POOL, dataset=DATA_FILE) -> dict:
    """One run's inputs, in the same shape and units the store uses.

    start_date and end_date are the dates of the first and last candle in
    the window, not the dates that were asked for. That is what the store
    records, so it is what a lookup has to compare against.
    """
    return {
        "pool": pool,
        "dataset": dataset,
        "start_date": start_date,
        "end_date": end_date,
        "bin_step": int(bin_step),
        "fee_rate": default_fee_rate(bin_step) if fee_rate is None
                    else float(fee_rate),
        "pool_share": float(pool_share),
        "bin_tvl": float(bin_tvl),
        "deposit": float(deposit),
        "position_bins": int(position_bins),
        "rebalance_cost": float(rebalance_cost),
    }


def default_fee_rate(bin_step) -> float:
    """Meteora's base fee for a bin step: one basis point per unit of step.

    Bin step 4 gives 0.04%, which is the rate config.py carries and the
    one every published result was produced at. It is a default, not a
    law -- pools do run other rates, which is why the control stays
    editable.
    """
    return bin_step / 10_000


# ----------------------------------------------------------------------
# Looking a configuration up instead of running it
# ----------------------------------------------------------------------

# How precisely each stored column has to match. Rates carry more digits
# than money does, and comparing floats straight out of a CSV against
# floats out of a widget needs a tolerance somewhere.
_DECIMALS = {"fee_rate": 10, "pool_share": 10, "rebalance_cost": 10,
             "bin_tvl": 2, "deposit": 2}


def _comparable(column, value):
    if column in _DECIMALS:
        return round(float(value), _DECIMALS[column])
    if column in ("bin_step", "position_bins"):
        return int(value)
    return str(value)


def _key(source, strategy) -> tuple:
    """The identity of a run: its configuration and which strategy it is."""
    return tuple(_comparable(column, strategy if column == "strategy"
                             else source[column])
                 for column in CONFIG_COLUMNS)


def find_saved(config, strategy, runs=None):
    """The stored row for this exact configuration, or None.

    This is what makes the page open instantly on a configuration someone
    has already run: the answer is already on disk, and re-deriving it
    would produce the same numbers after half a minute of work.
    """
    runs = load_runs() if runs is None else runs
    if runs.empty:
        return None
    wanted = _key(config, strategy)
    for row in runs.to_dict("records"):
        if _key(row, row["strategy"]) == wanted:
            return row
    return None


# ----------------------------------------------------------------------
# Running it
# ----------------------------------------------------------------------

# A run is split into phases the page drives one at a time, rather than
# one cached call that reports its own progress. A cached function may not
# touch a Streamlit element -- Streamlit records elements created inside
# one so it can replay them on a cache hit, and a progress bar created
# outside the function cannot be replayed into. So the phases are called
# from the page, which owns the progress bar.
#
# Nothing in this module is cached, and that is the point: every artefact
# here is large. The frame carries a list of bin ids per candle, the fee
# split is one dict per candle, and a result holds a full per-candle
# series. The page caches what survives a run -- the metrics and the
# drawn charts -- and lets the rest go.

def prepared(config):
    """The window, binned onto this configuration's bin step."""
    df = window(config["start_date"], config["end_date"], config["dataset"])
    return prepare(df, bin_step=config["bin_step"])


def fee_split(config, df):
    """Each candle's fee, spread across the bins that candle touched."""
    _, per_candle_bin_fees = accumulate_bin_fees(
        df, fee_rate=config["fee_rate"], pool_share=config["pool_share"],
        bin_step=config["bin_step"])
    return per_candle_bin_fees


def run_strategy(config, strategy, df=None, fees=None) -> dict:
    """One strategy over one configuration; the full result dict.

    Deliberately NOT cached. The result carries a per-candle series, and
    measured on the year that is 64 MB pickled per strategy -- 127 MB for
    a pair, against the roughly 1 GB a hosted container gets. Caching a
    handful of those is enough to put the process into swap, which is
    exactly what it did: a run that takes 1.3 s took 578 s with two
    year-long results already cached.

    So the series is treated as what it is, working material. The caller
    draws its charts, keeps the metrics, and lets it go; what gets cached
    is that small residue, not this.

    df and fees are passed in when the caller has already built them for
    a sibling strategy, and rebuilt here when they are not.
    """
    df = prepared(config) if df is None else df
    fees = fee_split(config, df) if fees is None else fees
    return run(df, strategy=strategy, per_candle_bin_fees=fees,
               fee_rate=config["fee_rate"], cost_rate=config["rebalance_cost"],
               bin_step=config["bin_step"], pool_share=config["pool_share"],
               bin_tvl=config["bin_tvl"], deposit=config["deposit"],
               position_bins=config["position_bins"],
               fee_distribution=FEE_DISTRIBUTION)


# ----------------------------------------------------------------------
# A run, reduced to what is worth keeping
# ----------------------------------------------------------------------
# This lives here rather than on a page because two pages need it and
# st.cache_data keys on a function's module and name: a copy per page
# would be a cache per page, so a configuration run on one would be
# recomputed by the other. One function, imported by both, is one cache.

# Each per-strategy chart with the question it answers.
CHARTS = [
    ("Price against the position's range", charts.price_with_range_band),
    ("Fees, impermanent loss and net PnL", charts.pnl_decomposition),
    ("The position against holding", charts.position_vs_hodl),
    ("What the position was worth", charts.position_value_over_time),
]


def _png(figure) -> bytes:
    """A figure as bytes, so it can be cached and the figure released."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150,
                   facecolor=figure.get_facecolor())
    charts.plt.close(figure)
    return buffer.getvalue()


@st.cache_data(show_spinner=False, max_entries=24)
def _run_and_draw(config, strategy, _df=None, _fees=None) -> dict:
    """One strategy's run, reduced to what is worth keeping.

    Returns params, metrics and the charts as PNG bytes -- about 400 KB.
    What it deliberately does NOT return is the per-candle series the
    charts were drawn from: that is 64 MB for a year, and caching a few
    of them puts the process into swap. The series lives inside this call
    and is released when it ends.

    Caching bytes rather than figures matters for the same reason: a
    matplotlib figure is not something to hand between reruns.

    _df and _fees lead with an underscore so Streamlit leaves them out of
    the cache key. They are derived entirely from `config`, so including
    them would only make identical runs look different; they are passed
    in when the caller has already built them for a sibling strategy.
    """
    result = run_strategy(config, strategy, df=_df, fees=_fees)
    return {
        "params": result["params"],
        "metrics": result["metrics"],
        "charts": [(title, _png(draw(result))) for title, draw in CHARTS],
    }


def run_and_draw(config, strategy, _df=None, _fees=None) -> dict:
    """The cached run, and a note that this pair has now been drawn.

    The note is what lets a page say whether a click will be instant
    before the click happens. It is a session-level hint, not the truth
    about the cache -- there is no way to ask Streamlit that -- so it can
    only be wrong in the safe direction after an eviction: a wait that
    was quoted as instant, never a wait quoted for something already in
    hand.
    """
    drawn = _run_and_draw(config, strategy, _df=_df, _fees=_fees)
    mark_drawn(config, strategy)
    return drawn


def drawn_key(config, strategy) -> tuple:
    return repr(sorted(config.items())), strategy


def is_drawn(config, strategy) -> bool:
    """Whether this pair has been drawn in this session."""
    return drawn_key(config, strategy) in st.session_state.get("_drawn", set())


def mark_drawn(config, strategy) -> None:
    st.session_state.setdefault("_drawn", set()).add(drawn_key(config, strategy))


def save(results) -> str:
    """Record a run so it shows up in the history. Returns the run's id."""
    return save_run(list(results.values()))
