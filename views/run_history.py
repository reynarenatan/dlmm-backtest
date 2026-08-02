"""Every run that has been saved, filtered on the parameters it used.

Reads results/runs.csv and nothing else -- no page runs the engine.

The filters are built from `store.CONFIG_COLUMNS` and from the values
actually present in the file, not from a list written here: save a new
parameter with a run and it gets a filter without this file changing. The
DISPLAY table below is labels and number formats only, and anything
missing from it still renders, so a new column is visible immediately and
just looks plainer until someone gives it a label.
"""

from functools import partial, reduce

import streamlit as st

try:
    from pandas.api.types import is_numeric_dtype

    from results.store import CONFIG_COLUMNS, RUNS_PATH, load_runs
    from webdata import md_caption, rate
except ImportError as error:
    from stale import guard

    guard(error)

# Above this many distinct values a numeric column gets a range slider
# instead of a pick-list. Twelve is about where scanning a list of options
# stops being quicker than dragging a handle.
MAX_CHOICES = 12

# label, and a printf format for the columns that are numbers. "as_pct"
# means the value is stored as a fraction and shown as a percentage --
# the store keeps what metrics.py produced, so the conversion happens here.
DISPLAY = {
    "execution_id": {"label": "Execution"},
    "timestamp": {"label": "Saved (UTC)"},
    "pool": {"label": "Pool"},
    "dataset": {"label": "Dataset"},
    "start_date": {"label": "Start"},
    "end_date": {"label": "End"},
    "bin_step": {"label": "Bin step", "format": "%d"},
    "fee_rate": {"label": "Fee rate", "format": "%.4f%%", "as_pct": True},
    "pool_share": {"label": "Pool share", "format": "%.1f%%", "as_pct": True},
    "bin_tvl": {"label": "Bin TVL", "format": "$%.0f"},
    "deposit": {"label": "Deposit", "format": "$%.0f"},
    "position_bins": {"label": "Bins", "format": "%d"},
    "strategy": {"label": "Strategy"},
    "rebalance_cost": {"label": "Rebalance cost", "format": "%.2f%%",
                       "as_pct": True},
    "fees": {"label": "Fees", "format": "$%.2f"},
    "il": {"label": "Impermanent loss", "format": "$%.2f"},
    "costs": {"label": "Costs", "format": "$%.2f"},
    "net_pnl": {"label": "Net vs holding", "format": "$%.2f"},
    "net_apy": {"label": "Net APY", "format": "%.1f%%", "as_pct": True},
    "gross_fee_apy": {"label": "Gross fee APY", "format": "%.1f%%",
                      "as_pct": True},
    "break_even_fee_rate": {"label": "Break-even fee rate",
                            "format": "%.4f%%", "as_pct": True},
    "time_in_range": {"label": "Time in range", "format": "%.1f%%"},
    "rebalance_count": {"label": "Rebalances", "format": "%d"},
    "max_drawdown": {"label": "Max drawdown", "format": "$%.2f"},
}


def label_of(column) -> str:
    """A column's heading, falling back to the column name made readable."""
    spec = DISPLAY.get(column, {})
    return spec.get("label", column.replace("_", " ").capitalize())


def option_label(column, value) -> str:
    """One filter option, shown the way the table shows the same value."""
    if DISPLAY.get(column, {}).get("as_pct"):
        return rate(value)
    return str(value)


def filter_widget(runs, column):
    """One filter for one column, shaped by the values in the file.

    Returns a boolean mask, or None when the filter is not narrowing
    anything. Nothing here knows what any column means: a column with few
    distinct values becomes a pick-list and a numeric one with many
    becomes a range. That is what makes a newly saved parameter filterable
    without this function being told about it.
    """
    values = runs[column].dropna()
    options = sorted(values.unique())
    label = label_of(column)

    if len(options) > MAX_CHOICES and is_numeric_dtype(values):
        low, high = float(options[0]), float(options[-1])
        chosen = st.slider(label, low, high, (low, high))
        if chosen == (low, high):
            return None
        return runs[column].between(*chosen)

    picked = st.multiselect(label, options, placeholder="All",
                            format_func=partial(option_label, column))
    # Nothing picked means the filter is off, not that nothing matches --
    # an empty table would be the more confusing reading of an empty box.
    return runs[column].isin(picked) if picked else None


def display_frame(runs):
    """The same rows, with stored fractions turned into percentages."""
    shown = runs.copy()
    for column, spec in DISPLAY.items():
        if spec.get("as_pct") and column in shown:
            shown[column] = shown[column] * 100
    return shown


def column_config() -> dict:
    """Heading and number format per column, for st.dataframe."""
    config = {}
    for column, spec in DISPLAY.items():
        if "format" in spec:
            config[column] = st.column_config.NumberColumn(
                spec["label"], format=spec["format"])
        else:
            config[column] = st.column_config.TextColumn(spec["label"])
    return config


st.title("Run history")

runs = load_runs()
if runs.empty:
    st.info(f"No runs saved yet. `python run_backtest.py` appends one row "
            f"per strategy to `{RUNS_PATH.name}`.")
    st.stop()

md_caption(
    f"Every backtest that has been run and saved, read from "
    f"`results/runs.csv`. One row per strategy, so one execution of the "
    f"backtest writes two rows sharing an execution id. Click any heading "
    f"to sort; the filters in the sidebar narrow the table by the "
    f"parameters a run used."
)

with st.sidebar:
    st.header("Filters")
    st.caption("One per saved parameter. Leave a box empty to ignore it.")
    masks = [mask for mask in
             (filter_widget(runs, column) for column in CONFIG_COLUMNS)
             if mask is not None]

shown = runs[reduce(lambda a, b: a & b, masks)] if masks else runs

st.dataframe(display_frame(shown), column_config=column_config(),
             hide_index=True, width="stretch")

md_caption(
    f"{len(shown):,} of {len(runs):,} rows "
    f"({shown['execution_id'].nunique():,} of "
    f"{runs['execution_id'].nunique():,} executions). Fee rates, APYs and "
    f"the rebalance cost are stored as fractions and shown here as "
    f"percentages; net PnL is measured against holding the same starting "
    f"tokens, not against the deposit."
)
