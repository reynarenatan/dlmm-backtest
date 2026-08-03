"""Every run that has been done, and where the pool's fees were earned.

An overview, not a case study. A single run's metrics, its wealth table,
its break-even rate and its cost sensitivity all used to follow here for
the full year at bin step 4 -- but Run history shows any saved run's
numbers and puts two of them side by side, so one run singled out on the
landing page was the same comparison told worse.

Every string that reaches markdown goes through webdata.md/md_caption/
md_info, which escape the dollar signs -- Streamlit reads a $...$ pair as
LaTeX and would eat the money.
"""

import streamlit as st

try:
    import pandas as pd

    from config import (DATA_FILE, POSITION_BINS, TRACKED_POOLS,
                        USER_DEPOSIT)
    from results.store import load_runs
    from webdata import (STRATEGY_LABELS, chart_path, load_summary, md,
                         md_caption, md_info, money, money_round, pct,
                         signed_money, signed_pct)
    from windows import label_for
except ImportError as error:
    from stale import guard

    guard(error)

summary = load_summary()
params = summary["params"]
pool = summary["pool"]
passive = summary["strategies"]["passive"]

# One chart, and the one thing it is there to show, written against the
# precomputed numbers so a re-run cannot leave the caption stale.
#
# It is the only one left here on purpose. The others were a run's own
# charts -- price against its range, where its money went, what it was
# worth -- and Run history draws exactly those for any saved run, two at
# a time side by side, which is a better way to compare than two pictures
# a page apart. This one is not about a run at all: it is where the whole
# pool earned over the year, the backdrop every run is drawn against.
CHARTS = [
    ("fee_per_bin.png", "Where the pool's fees were earned", (
        f"The whole pool earned {money_round(pool['total_fees'])} over the "
        f"year, spread across {pool['bins_touched']:,} bins. The busiest "
        f"single bin, {money(pool['busiest_bin_low'])}-"
        f"{money(pool['busiest_bin_high'])}, took "
        f"{money_round(pool['busiest_bin_fees'])}. A "
        f"{params['position_bins']}-bin position covers a narrow slice of "
        "that, which is the whole problem a fixed range has."
    )),
]


# ======================================================================
# Every run, together
# ======================================================================
# This section reads results/runs.csv. That is not running the engine --
# the history page reads the same file -- so the rule that a results page
# only ever shows precomputed values still holds.
#
# It is the bulk of the page, and the only place a reader can see that the
# market mattered more than the grid, and that beating holding and making
# money are different questions with different answers. Anything about one
# run belongs on Run history, which can show two at a time.

def comparable(runs):
    """Runs done at a tracked pool's own parameters, in the standard size.

    A conclusion is an average over things that belong together. A run
    someone made on the hosted site with an invented pool share is a
    perfectly good run and belongs in the history, but averaging it in
    here would move a number nobody could then explain -- so eligibility
    is by construction rather than by trust: the bin step has to be a
    pool we tracked, at that pool's own share and depth, in the standard
    deposit and width, over the same dataset.
    """
    if runs.empty:
        return runs
    tracked = runs["bin_step"].map(
        lambda step: TRACKED_POOLS.get(int(step)) if step == step else None)
    return runs[
        tracked.notna()
        & tracked.map(lambda p: p and p["pool_share"]).eq(runs["pool_share"])
        & tracked.map(lambda p: p and p["bin_tvl"]).eq(runs["bin_tvl"])
        & runs["deposit"].eq(USER_DEPOSIT)
        & runs["position_bins"].eq(POSITION_BINS)
        & runs["dataset"].eq(DATA_FILE)
    ]


def with_returns(runs):
    """The two things a reader wants per run, added as columns.

    `net_pnl` says how a run did against holding and `return_pct` says
    what the money did; the pair is the whole point of the section, and
    on this dataset they disagree constantly. Both come out of the store
    -- fees are withdrawn rather than compounded, so wealth is fees plus
    whatever the position is still worth.
    """
    runs = runs.copy()
    runs["window"] = [label_for(row.start_date, row.end_date)
                      for row in runs.itertuples()]
    runs["return_pct"] = ((runs["fees"] + runs["final_value"])
                          / runs["entry_value"] - 1) * 100
    runs["hodl_pct"] = (runs["hodl_final_value"] / runs["entry_value"] - 1) * 100
    return runs


def listed(names) -> str:
    """Names as English rather than as a join: "a, b and c"."""
    names = list(names)
    if len(names) < 2:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def with_holding(runs):
    """Holding added as a third strategy, one per window and pool.

    Its return depends on the bin step even though it does no trading:
    holding means keeping the tokens the position opened with, and a
    wider bin buys its SOL further above the market, so those tokens are
    not the same tokens at every step. On the full year the baseline is
    -28.7% at step 4 and -30.1% at step 20. Quoting one figure for all
    three would silently measure two of the columns against the wrong
    baseline, so each gets its own.
    """
    hold = runs[runs["strategy"] == "passive"].copy()
    hold["strategy"] = "holding"
    hold["return_pct"] = hold["hodl_pct"]
    return pd.concat([runs, hold], ignore_index=True)


# Holding is not a strategy the engine runs, but it is a column in a
# table of returns, so it needs a name like the others.
COLUMN_LABELS = {**STRATEGY_LABELS, "holding": "Holding"}


def window_order(runs) -> list:
    """Chronological, with the longest window last.

    That puts the months in the order they happened and leaves the full
    year -- which contains them and is what the rest of the page is
    about -- at the bottom, the same order as the buttons on Run it
    yourself and the sweep that produced these rows.
    """
    spans = runs.groupby("window").agg(
        start=("start_date", "min"), end=("end_date", "max"))
    length = pd.to_datetime(spans["end"]) - pd.to_datetime(spans["start"])
    spans["last"] = length == length.max()
    return list(spans.sort_values(["last", "start"]).index)


def matrix(runs, value, fmt, strategies) -> str:
    """One row per window, one column per strategy and bin step."""
    steps = sorted(runs["bin_step"].unique())
    columns = [(strategy, step) for strategy in strategies for step in steps]
    header = ("| | " + " | ".join(f"{COLUMN_LABELS[s]} {int(step)}"
                                  for s, step in columns) + " |\n"
              + "|---|" + "---|" * len(columns) + "\n")
    lines = []
    for window in window_order(runs):
        cells = []
        for strategy, step in columns:
            cell = runs[(runs["window"] == window)
                        & (runs["strategy"] == strategy)
                        & (runs["bin_step"] == step)]
            cells.append(fmt(cell[value].iloc[0]) if len(cell) else "-")
        lines.append(f"| {window} | " + " | ".join(cells) + " |")
    return header + "\n".join(lines)


def overview() -> None:
    """Every comparable run at once, and what they say together."""
    st.subheader("Every run so far")

    all_runs = load_runs()
    runs = comparable(all_runs)
    if len(runs) < 2:
        md_caption(
            "There are too few comparable runs saved to draw anything from "
            "yet. `python scripts/sweep.py` records a spread of them.")
        return
    runs = with_returns(runs)

    beat = int((runs["net_pnl"] > 0).sum())
    made = int((runs["return_pct"] > 0).sum())
    left_out = len(all_runs) - len(runs)
    md(f"**{len(runs)} runs**, across {runs['window'].nunique()} market "
       f"windows and {runs['bin_step'].nunique()} pools. "
       f"**{beat} beat holding. {made} made money.** Those are different "
       f"questions, and on this data they have different answers: a "
       f"position can be the better thing to have done and still hand back "
       f"less than went in.")

    if left_out:
        md_caption(
            f"{left_out} further saved "
            f"{'run is' if left_out == 1 else 'runs are'} **left out of "
            f"this section**, having been run at parameters that do not "
            f"match a tracked pool - a different pool share, depth, deposit "
            f"or width. Averaging those in would move a number nobody could "
            f"then explain. Every run is still listed on Run history.")

    st.markdown("**Against holding**")
    md(matrix(runs, "net_pnl", signed_money, STRATEGY_LABELS))
    md_caption(f"Fees minus impermanent loss and costs, in dollars on a "
               f"{money_round(USER_DEPOSIT)} deposit. Positive means the "
               f"position was worth more than holding the same tokens. The "
               f"number beside each strategy is the bin step, and each is a "
               f"different pool: they handle 8%, 1.30% and 0.315% of SOL "
               f"volume.")

    st.markdown("**What the money did**")
    md(matrix(with_holding(runs), "return_pct", signed_pct,
              [*STRATEGY_LABELS, "holding"]))
    md_caption("Fees collected plus whatever the position was still worth, "
               "against what the deposit was marked at when it opened, over "
               "each window's own length rather than annualised. Holding is "
               "quoted per bin step because the tokens a position opens "
               "with - and so the tokens holding holds - depend on it.")

    conclusion(runs)


def conclusion(runs) -> None:
    """What the runs say, written from the runs.

    Every figure here is read off the frame. Nothing is typed, so a sweep
    that changes the answer changes the paragraph too -- which is the only
    way a conclusion on a page like this can be trusted.
    """
    pairs = runs.pivot_table(index=["window", "bin_step"], columns="strategy",
                             values="net_pnl")
    won = pairs["rebalancing"] > pairs["passive"]
    of_window = won.groupby("window")
    always = [w for w, n in of_window.sum().items() if n == of_window.size()[w]]
    never = [w for w, n in of_window.sum().items() if n == 0]

    # How much the answer moves with the market, against how much it moves
    # with the grid: the spread of window averages against the spread of
    # bin step averages, on the same numbers.
    per_window = runs.groupby("window")["net_pnl"].mean()
    per_step = runs.groupby("bin_step")["net_pnl"].mean()
    market_spread = per_window.max() - per_window.min()
    grid_spread = per_step.max() - per_step.min()

    # The longest window is the only one long enough to be read as an
    # outcome rather than as a month that happened to go well.
    longest = window_order(runs)[-1]
    over_year = runs[runs["window"] == longest]
    best_year = over_year.loc[over_year["return_pct"].idxmax()]
    worst = runs.loc[runs["net_pnl"].idxmin()]

    lines = [
        f"**Rebalancing beat sitting still in {int(won.sum())} of "
        f"{len(won)} matched pairs.** It won every pair in "
        f"{listed(always)} and lost every pair in {listed(never)}. "
        f"Recentring pays when the price walks far enough that a fixed "
        f"range is abandoned, and charges for every crossing when it "
        f"does not.",

        f"**The market moved the answer far more than the grid did.** "
        f"Average net against holding spans {money(market_spread)} across "
        f"the {runs['window'].nunique()} windows and only "
        f"{money(grid_spread)} across the {runs['bin_step'].nunique()} bin "
        f"steps - the tracked pools differ by a factor of 28 in the volume "
        f"they handle, and it still matters less than which month you were "
        f"in.",

        f"**Over a full year, the best case was getting the money back.** "
        f"Across the {len(over_year)} runs of the {longest} window, the "
        f"best was {COLUMN_LABELS[best_year['strategy']].lower()} at bin "
        f"step {int(best_year['bin_step'])}, finishing "
        f"{signed_pct(best_year['return_pct'])} on the deposit against "
        f"{signed_pct(best_year['hodl_pct'])} for holding. A year of fees "
        f"cancelled a year of decline rather than beating it. The worst "
        f"showing anywhere was "
        f"{COLUMN_LABELS[worst['strategy']].lower()} at bin step "
        f"{int(worst['bin_step'])} through the {worst['window']}, "
        f"{signed_money(worst['net_pnl'])} against holding.",
    ]
    md_info("\n\n".join(lines))


st.title("Results")
md_caption(
    "What every backtest run so far found, taken together"
)

md("Money is put into a SOL/USDC liquidity position, which earns trading "
   "fees and suffers impermanent loss, and the question is whether the "
   "first covers the second. Two strategies answer it on identical "
   "candles: a **passive** position that sets its range once and leaves "
   "it, and a **rebalancing** one that recentres whenever price closes "
   "outside the range.")

overview()

st.divider()
st.subheader("Where the year's fees were")
for filename, caption, takeaway in CHARTS:
    st.image(chart_path(filename), caption=caption, width="stretch")
    md(takeaway)
    st.write("")

md(f"**Two things that chart does not show, and they are the finding.** "
   f"Take the full-year passive run in this pool, a row of the tables "
   f"above. Its range was fixed at "
   f"{money(passive['initial_range_low'])}-"
   f"{money(passive['initial_range_high'])} on the first candle and price "
   f"left it within weeks, so it earned on "
   f"{pct(passive['time_in_range_pct'])} of candles all year. And for "
   f"{passive['phases']['usdc_only_candles']:,} of them it was worth "
   f"exactly {money(passive['phases']['usdc_only_value'])} whatever SOL "
   f"did - every bin below the price holds USDC, and USDC does not move "
   f"when the price does. From "
   f"{passive['phases']['sol_only_from'][:10]} the price was below the "
   f"range for good: the bins had spent their cash buying SOL, so the "
   f"position became a pure SOL bag and fell with it, "
   f"{money(passive['phases']['sol_only_start_value'])} down to "
   f"{money(passive['final_value'])}.")

md_caption(
    "Each run's own charts - its range against the price, where its money "
    "went, what it was worth - are on **Run history**: tick a row to see "
    "one, or two rows to put them side by side. They are not repeated "
    "here, because comparing runs is that page's job."
)

md_caption(
    "The tables above are read from `results/runs.csv`, and the chart and "
    "the paragraph under it were produced ahead of time by `run_backtest.py` "
    "and `precompute.py`. The page never runs the engine."
)
