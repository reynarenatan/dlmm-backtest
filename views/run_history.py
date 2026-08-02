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

    import runner
    from results.store import (CONFIG_COLUMNS, RESULT_COLUMNS, RUNS_PATH,
                               load_runs)
    from webdata import (STRATEGY_LABELS, hosted_note, md, md_caption,
                         md_info, rate)
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


def present(value) -> bool:
    """Whether a number is there to be shown.

    A stored run keeps its blanks as empty CSV cells, which come back as
    NaN -- and NaN is truthy, so a plain `if value` would print it.
    """
    return value is not None and value == value


def format_value(column, value) -> str:
    """One stored value, formatted the way the table formats it.

    Reuses DISPLAY, so a column given a format there is formatted here
    for free and a column missing from it still prints.
    """
    spec = DISPLAY.get(column, {})
    if not present(value):
        return "--"
    if "format" not in spec:
        return str(value)
    if spec.get("as_pct"):
        value = value * 100
    # The sign goes outside the format, so a negative reads "-$331.27"
    # rather than "$-331.27" and agrees with the differences beside it.
    negative = isinstance(value, (int, float)) and value < 0
    return ("-" if negative else "") + spec["format"] % abs(value)


def format_delta(column, delta) -> str:
    """A difference, signed, in that column's own units."""
    if not present(delta):
        return "--"
    if delta == 0:
        return "same"
    return ("+" if delta > 0 else "-") + format_value(column, abs(delta))


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


# ======================================================================
# Looking at a stored run
# ======================================================================
# The store keeps a run's numbers but not its per-candle series, so the
# metrics below come free from the CSV and the charts do not: drawing
# them means a run. That goes through runner.run_and_draw, the same
# cached call Run it yourself uses, so a configuration already run on
# either page comes back from the cache instead of being recomputed.

def config_of(row) -> dict:
    """A stored row's configuration, in the shape runner uses.

    Built through runner.make_config so it comes out identical to the
    configuration Run it yourself builds for the same settings -- which
    is exactly what makes a run done there a cache hit here.
    """
    return runner.make_config(
        start_date=row["start_date"], end_date=row["end_date"],
        bin_step=row["bin_step"], fee_rate=row["fee_rate"],
        pool_share=row["pool_share"], bin_tvl=row["bin_tvl"],
        deposit=row["deposit"], position_bins=row["position_bins"],
        rebalance_cost=row["rebalance_cost"], pool=row["pool"],
        dataset=row["dataset"])


def config_row(row) -> dict:
    """Every config column of a stored row, normalised for comparison.

    make_config covers the pool and the position; the strategy is a
    config column too, and the one that most often differs.
    """
    return {**config_of(row), "strategy": row["strategy"]}


def run_label(row) -> str:
    return (f"{STRATEGY_LABELS.get(row['strategy'], row['strategy'])}, "
            f"{row['start_date']} to {row['end_date']}, bin step "
            f"{int(row['bin_step'])}, {format_value('fee_rate', row['fee_rate'])} "
            f"fee, {format_value('deposit', row['deposit'])} deposit")


def wait_for(pairs) -> float:
    """Seconds the engine needs for whichever pairs are not already drawn."""
    total = 0.0
    for config, strategy in pairs:
        if runner.is_drawn(config, strategy):
            continue
        candles = runner.window(config["start_date"], config["end_date"],
                                config["dataset"])
        total += runner.estimate_seconds(len(candles), [strategy])
    return total


def ready(pairs, what) -> bool:
    """True to draw now; otherwise quote the wait and offer the button."""
    seconds = wait_for(pairs)
    if not seconds:
        return True
    md(f"**Drawing {what} needs the engine.** A run's per-candle series is "
       f"not stored -- only its numbers are -- so the charts have to come "
       f"from a fresh run: **{runner.format_duration(seconds)}**. The "
       f"numbers above are already the run's own and do not change.")
    return st.button(f"Run and draw {what}", type="primary",
                     key=f"draw-{hash(repr(pairs))}")


def draw_all(pairs, progress) -> list:
    """Draw every pair, sharing the candle work where the config allows.

    Two strategies of one configuration -- the commonest comparison, and
    what one execution writes -- differ only in the walk, so the window
    is binned and its fees split once for both.
    """
    drawn, shared = [], {}
    for i, (config, strategy) in enumerate(pairs):
        base = 0.9 * i / len(pairs)
        if runner.is_drawn(config, strategy):
            drawn.append(runner.run_and_draw(config, strategy))
            continue
        key = repr(sorted(config.items()))
        if key not in shared:
            progress.progress(base + 0.05, text="Loading candles")
            frame = runner.prepared(config)
            progress.progress(base + 0.15, text="Splitting each candle's fee "
                                                "across its bins")
            shared[key] = (frame, runner.fee_split(config, frame))
        frame, fees = shared[key]
        progress.progress(base + 0.30,
                          text=f"Running the {strategy} strategy over "
                               f"{len(frame):,} candles, and drawing it")
        drawn.append(runner.run_and_draw(config, strategy,
                                         _df=frame, _fees=fees))
    progress.progress(1.0, text="Done")
    return drawn


def metric_cards(row) -> None:
    """Every stored number for one run, straight from the CSV."""
    columns = st.columns(5)
    for column, name in zip(columns * 2, RESULT_COLUMNS):
        with column:
            st.metric(label_of(name), format_value(name, row[name]))


def show_detail(row) -> None:
    st.subheader("Run detail")
    md_caption(run_label(row))
    metric_cards(row)

    config, strategy = config_of(row), row["strategy"]
    st.divider()
    if not ready([(config, strategy)], "this run's charts"):
        return

    progress = st.progress(0.0, text="Starting")
    drawn, = draw_all([(config, strategy)], progress)
    progress.empty()
    for title, image in drawn["charts"]:
        st.image(image, caption=title, width="stretch")


def config_diff(left, right) -> list:
    """The config columns whose values differ, and both values."""
    a, b = config_row(left), config_row(right)
    return [(column, a[column], b[column]) for column in CONFIG_COLUMNS
            if a[column] != b[column]]


def show_compare(left, right) -> None:
    st.subheader("Compare two runs")
    names = ("Run A", "Run B")
    for name, row in zip(names, (left, right)):
        md_caption(f"**{name}** - {run_label(row)}")

    # --- what is configured differently --------------------------------
    st.markdown("**Configuration**")
    differences = config_diff(left, right)
    if not differences:
        md_info("Both runs were configured identically, including the "
                "strategy. Any difference in the numbers below would mean "
                "the engine changed between them.")
    else:
        rows = [f"| {label_of(column)} | {format_value(column, a)} | "
                f"{format_value(column, b)} |"
                for column, a, b in differences]
        md("| Parameter | Run A | Run B |\n|---|---|---|\n" + "\n".join(rows))
        md_caption(f"{len(differences)} of {len(CONFIG_COLUMNS)} parameters "
                   f"differ; the rest are identical and left out.")

    # --- what came out --------------------------------------------------
    st.markdown("**Results**")
    rows = []
    for column in RESULT_COLUMNS:
        a, b = left[column], right[column]
        delta = b - a if present(a) and present(b) else None
        rows.append(f"| {label_of(column)} | {format_value(column, a)} | "
                    f"{format_value(column, b)} | {format_delta(column, delta)} |")
    md("| | Run A | Run B | B - A |\n|---|---|---|---|\n" + "\n".join(rows))

    # --- the same chart for both ----------------------------------------
    pairs = [(config_of(left), left["strategy"]),
             (config_of(right), right["strategy"])]
    st.divider()
    if not ready(pairs, "both runs' charts"):
        return

    progress = st.progress(0.0, text="Starting")
    drawn_a, drawn_b = draw_all(pairs, progress)
    progress.empty()

    st.markdown("**Charts**")
    for index, (title, _) in enumerate(runner.CHARTS):
        st.markdown(f"*{title}*")
        for column, drawn, name in zip(st.columns(2), (drawn_a, drawn_b),
                                       names):
            with column:
                st.image(drawn["charts"][index][1], caption=name,
                         width="stretch")


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
hosted_note()

with st.sidebar:
    st.header("Filters")
    st.caption("One per saved parameter. Leave a box empty to ignore it.")
    masks = [mask for mask in
             (filter_widget(runs, column) for column in CONFIG_COLUMNS)
             if mask is not None]

shown = runs[reduce(lambda a, b: a & b, masks)] if masks else runs

event = st.dataframe(display_frame(shown), column_config=column_config(),
                     hide_index=True, width="stretch",
                     on_select="rerun", selection_mode="multi-row",
                     key="history_table")

md_caption(
    f"{len(shown):,} of {len(runs):,} rows "
    f"({shown['execution_id'].nunique():,} of "
    f"{runs['execution_id'].nunique():,} executions). Fee rates, APYs and "
    f"the rebalance cost are stored as fractions and shown here as "
    f"percentages; net PnL is measured against holding the same starting "
    f"tokens, not against the deposit."
)

# The selection indexes the frame that was displayed, which is `shown`
# reformatted -- same rows, same order -- so the positions carry straight
# back to the stored values.
picked = event.selection.rows
selected = [shown.iloc[position] for position in picked]

st.divider()
if not selected:
    md_caption("Tick one row to see its charts, or two to compare them.")
elif len(selected) == 1:
    show_detail(selected[0])
elif len(selected) == 2:
    show_compare(selected[0], selected[1])
else:
    st.warning(f"{len(selected)} rows selected. Pick one to see it, or two "
               f"to compare them.")
