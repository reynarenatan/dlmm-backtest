"""Choose a configuration and back-test it.

The only page that runs the engine, so the whole design is about not
running it. A configuration already in results/runs.csv is answered from
there; anything else is quoted a wait before the work starts, and the
result is cached on the configuration so moving a widget cannot trigger
it again. The compute itself lives in runner.py; this file is controls
and layout.

Every markdown string goes through webdata.md/md_caption/md_info, which
escape the dollar signs -- Streamlit reads a $...$ pair as LaTeX.
"""

import streamlit as st

try:
    import runner
    from config import MAX_BINS
    from results.store import RUNS_PATH
    from runner import run_and_draw
    from webdata import (STRATEGY_LABELS, hosted_note, md, md_caption,
                         md_info, money, pct, rate, signed_money, signed_pct)
except ImportError as error:
    from stale import guard

    guard(error)

# Bin steps real Meteora SOL pools run at. A free number here would let
# someone ask for a step no pool offers and read the answer as if it
# meant something.
BIN_STEPS = [1, 2, 4, 5, 8, 10, 15, 20, 25, 50, 100]


def execute(config, strategies, progress) -> dict:
    """Run one configuration, reporting each phase as it goes.

    The phases are called from here, and not from inside a cached
    function, because a cached function may not touch a Streamlit
    element: Streamlit records elements created inside one so it can
    replay them on a cache hit, and it cannot replay into a progress bar
    that was created out here.

    The two shared phases are recomputed on every press, even when the
    strategies turn out to be cached. Pressing a button labelled "run"
    and being charged for the run is the honest reading, and it is also
    the safe one -- if the cache has dropped an entry, these are exactly
    what rebuilding it needs.
    """
    progress.progress(0.05, text="Loading candles")
    df = runner.prepared(config)

    progress.progress(0.25, text=f"Splitting each candle's fee across bin "
                                 f"step {config['bin_step']}")
    fees = runner.fee_split(config, df)

    runs = {}
    for i, strategy in enumerate(strategies):
        progress.progress(0.35 + 0.6 * i / len(strategies),
                          text=f"Running the {strategy} strategy over "
                               f"{len(df):,} candles, and drawing its charts")
        runs[strategy] = run_and_draw(config, strategy, _df=df, _fees=fees)

    progress.progress(1.0, text="Done")
    return runs


def cached_runs(config, strategies) -> dict:
    """Every requested strategy, from the cache.

    Cheap when the run has happened. Called cold it does the whole run
    without progress, which only happens if the cache dropped an entry
    the page still expects.
    """
    return {strategy: run_and_draw(config, strategy)
            for strategy in strategies}


# ======================================================================
# Controls
# ======================================================================

def preset_buttons() -> None:
    """Four windows picked out of the data, one button each."""
    st.caption("Preset windows")
    for name, preset in runner.PRESETS.items():
        st.button(f"{name} - {preset['dates']}", width="stretch",
                  help=preset["help"], on_click=choose_preset, args=(name,))


def choose_preset(name) -> None:
    """Set the date pickers from a preset.

    Runs as a button callback, i.e. before the script re-executes, which
    is the only point at which a widget's stored value can still be
    changed.
    """
    preset = runner.PRESETS[name]
    st.session_state["start_date"] = preset["start"]
    st.session_state["end_date"] = preset["end"]


def controls() -> dict:
    """Every input, returned as a configuration dict."""
    first, last = runner.dataset_bounds()

    # The date pickers are seeded from the default preset before they are
    # created; afterwards only choose_preset may write to them.
    default = runner.PRESETS[runner.DEFAULT_PRESET]
    st.session_state.setdefault("start_date", default["start"])
    st.session_state.setdefault("end_date", default["end"])

    preset_buttons()
    st.caption("Or pick your own dates")
    start = st.date_input("From", key="start_date",
                          min_value=first, max_value=last)
    end = st.date_input("To", key="end_date",
                        min_value=first, max_value=last)

    st.divider()
    strategies = st.multiselect(
        "Strategy", runner.STRATEGIES, default=list(runner.STRATEGIES),
        format_func=STRATEGY_LABELS.get,
        help="Passive sets the range once and leaves it. Rebalancing "
             "recentres it whenever a candle closes outside it.")

    st.divider()
    st.caption("The pool")
    bin_step = st.select_slider(
        "Bin step (basis points)", BIN_STEPS, value=4,
        help="How far apart neighbouring bins are. Step 4 means each bin "
             "covers 0.04% of price.")

    # Meteora's base fee tracks the bin step, so the default follows it --
    # but only when the step actually changed, or it would overwrite an
    # edit on every rerun.
    fee_default = runner.default_fee_rate(bin_step) * 100
    if st.session_state.get("_fee_follows_step") != bin_step:
        st.session_state["fee_rate_pct"] = fee_default
        st.session_state["_fee_follows_step"] = bin_step

    fee_rate_pct = st.number_input(
        "Fee rate (%)", min_value=0.0, max_value=5.0, step=0.01,
        format="%.4f", key="fee_rate_pct",
        help="The pool's trading fee, charged on the volume it routes.")
    md_caption(f"Pre-filled with {fee_default:.4f}%, Meteora's base fee "
               f"for bin step {bin_step} - one basis point per unit of "
               f"step. Edit it to model a pool that charges something "
               f"else.")

    pool_share_pct = st.number_input(
        "Pool share (%)", min_value=0.01, max_value=100.0, value=8.0,
        step=0.5, format="%.2f",
        help="The share of all SOL market volume this pool handles. The "
             "published results use 8%, measured over 16 observations in "
             "July 2026.")
    bin_tvl = st.number_input(
        "TVL per bin ($)", min_value=100.0, max_value=1_000_000.0,
        value=13_500.0, step=500.0,
        help="Liquidity sitting in each bin. Your share of a bin, and so "
             "your share of its fees, is your deposit per bin divided by "
             "this.")

    st.divider()
    st.caption("The position")
    deposit = st.number_input(
        "Deposit ($)", min_value=100.0, max_value=10_000_000.0,
        value=1_000.0, step=100.0,
        help="Every fee figure scales linearly with this; impermanent "
             "loss does too.")
    position_bins = st.slider(
        "Position width (bins)", min_value=1, max_value=MAX_BINS, value=69,
        step=2,
        help=f"How many bins the deposit is spread over. {MAX_BINS} is "
             f"Meteora's cap for a single position and the engine "
             f"enforces it. Widths are odd so the range sits centred on "
             f"one bin.")
    rebalance_cost_pct = st.number_input(
        "Rebalance cost (%)", min_value=0.0, max_value=5.0, value=0.1,
        step=0.05, format="%.2f",
        help="Charged on the value that changes hands each time the range "
             "moves - swap fee, slippage and gas together. Only affects "
             "the rebalancing strategy.")

    return start, end, tuple(strategies), dict(
        bin_step=bin_step,
        fee_rate=fee_rate_pct / 100,
        pool_share=pool_share_pct / 100,
        bin_tvl=bin_tvl,
        deposit=deposit,
        position_bins=position_bins,
        rebalance_cost=rebalance_cost_pct / 100,
    )


# ======================================================================
# Output
# ======================================================================

def present(value) -> bool:
    """Whether a number is there to be shown.

    A stored run keeps its blanks as empty CSV cells, which come back as
    NaN -- and NaN is truthy, so a plain `if value` would print it.
    """
    return value is not None and value == value


def metric_cards(source) -> None:
    """The headline numbers, from a run's metrics or from a stored row.

    Takes either, because a saved run and a fresh one have to look the
    same on the page: the numbers are identical, only their provenance
    differs.
    """
    st.metric("Fees earned", money(source["fees"]))
    st.metric("Impermanent loss", signed_money(source["il"]))
    st.metric("Rebalancing costs",
              money(source["costs"]) if source["costs"] else "--")
    st.metric("Net vs holding", signed_money(source["net_pnl"]))
    st.metric("Net APY", pct(source["net_apy"] * 100))
    st.metric("Break-even fee rate",
              rate(source["break_even_fee_rate"])
              if present(source["break_even_fee_rate"]) else "--",
              help="The fee rate at which fees would exactly have covered "
                   "impermanent loss and costs. Undefined when the "
                   "position never earned a fee.")
    st.metric("Time in range", pct(source["time_in_range"]))
    st.metric("Rebalances", f"{int(source['rebalance_count']):,}")


def from_metrics(metrics) -> dict:
    """A fresh run's metrics under the names the store and cards use."""
    return {
        "fees": metrics["total_fees"],
        "il": metrics["total_il"],
        "costs": metrics["total_costs"],
        "net_pnl": metrics["net_pnl"],
        "net_apy": metrics["net_apy"],
        "break_even_fee_rate": metrics["break_even_fee_rate"],
        "time_in_range": metrics["time_in_range_pct"],
        "rebalance_count": metrics["rebalances"],
    }


def verdict(sources) -> None:
    """One sentence on what the run says, written from its own numbers."""
    lines = []
    for strategy, source in sources.items():
        label = STRATEGY_LABELS[strategy]
        covered = source["net_pnl"] > 0
        lines.append(
            f"**{label}** collected {money(source['fees'])} in fees against "
            f"{money(abs(source['il']))} of impermanent loss"
            + (f" and {money(source['costs'])} of costs" if source["costs"]
               else "")
            + f", finishing {signed_money(source['net_pnl'])} against "
            f"holding ({signed_pct(source['net_apy'] * 100)} a year). Fees "
            + ("covered it." if covered else "did not cover it."))
    md_info("\n\n".join(lines))


def show_results(sources, pngs=None) -> None:
    columns = st.columns(len(sources))
    for column, (strategy, source) in zip(columns, sources.items()):
        with column:
            st.subheader(STRATEGY_LABELS[strategy])
            metric_cards(source)

    st.divider()
    verdict(sources)

    if pngs is None:
        return
    st.divider()
    st.subheader("Charts")
    tabs = st.tabs([STRATEGY_LABELS[s] for s in pngs])
    for tab, strategy in zip(tabs, pngs):
        with tab:
            for title, image in pngs[strategy]:
                st.image(image, caption=title, width="stretch")


# ======================================================================
# Page
# ======================================================================

st.title("Run it yourself")
md_caption(
    "Change the pool, the position or the period and back-test it on the "
    "same minute-by-minute SOL data as the Results page. This is the only "
    "page that runs the engine."
)

with st.sidebar:
    st.header("Configuration")
    start, end, strategies, settings = controls()

if start > end:
    st.error("The start date is after the end date.")
    st.stop()
if not strategies:
    st.warning("Pick at least one strategy in the sidebar.")
    st.stop()

candles = runner.window(start, end)
if candles.empty:
    st.error(f"No candles between {start} and {end}.")
    st.stop()

# The configuration is identified by the dates of the candles it actually
# covers, not the dates that were asked for -- that is what the store
# records, so it is what a lookup can match.
config = runner.make_config(
    start_date=str(candles["timestamp"].iloc[0].date()),
    end_date=str(candles["timestamp"].iloc[-1].date()),
    **settings)

md_caption(
    f"{len(candles):,} one-minute candles, {config['start_date']} to "
    f"{config['end_date']} ({len(candles) / 1440:.0f} days)."
)

# --- what we already have ---------------------------------------------
runs = runner.load_runs()
saved = {s: runner.find_saved(config, s, runs) for s in strategies}
have_saved = all(row is not None for row in saved.values())

ran = st.session_state.setdefault("ran", set())
run_key = (repr(sorted(config.items())), strategies)
already_ran = run_key in ran

estimate = runner.estimate_seconds(len(candles), strategies)

if already_ran:
    label = "Run it again"
elif have_saved:
    label = "Run it anyway, to draw the charts"
    when = list(saved.values())[0]["timestamp"][:10]
    md_info(
        f"**This exact configuration has been run before** - saved on "
        f"{when}, so the numbers below were read from "
        f"`{RUNS_PATH.name}` rather than recomputed. Charts are not "
        f"stored with a run, so drawing them means running the engine: "
        f"{runner.format_duration(estimate)}."
    )
else:
    label = "Run the backtest"
    md(f"**Not run before.** Backtesting {len(candles):,} candles across "
       f"{len(strategies)} "
       f"{'strategy' if len(strategies) == 1 else 'strategies'} takes "
       f"**{runner.format_duration(estimate)}**.")
    md_caption(
        "Estimated from measured rates on the development machine, so "
        "treat it as a floor; a hosted container is slower. Nothing runs "
        "until you press the button."
    )

go = st.button(label, type="primary")

# --- run it ------------------------------------------------------------
# The results are shown in this same pass rather than after a st.rerun():
# a rerun would re-enter the display path only to read back what was just
# computed, and it makes the run harder to reason about for nothing.
if go:
    progress = st.progress(0.0, text="Starting")
    runs_now = execute(config, strategies, progress)
    progress.empty()

    if not already_ran:
        run_id = runner.save(runs_now)
        ran.add(run_key)
        st.toast(f"Saved as run {run_id}")
    already_ran = True

st.divider()

if already_ran:
    done = cached_runs(config, strategies)
    st.success("These numbers and charts came from the engine.")
    show_results({s: from_metrics(r["metrics"]) for s, r in done.items()},
                 {s: r["charts"] for s, r in done.items()})
    md_caption(f"Saved to `{RUNS_PATH.name}` and listed on the Run history "
               f"page.")
    hosted_note()
elif have_saved:
    show_results(saved)
    md_caption(
        "Read from the saved run, not recomputed. Press the button above "
        "to run the engine and draw the charts."
    )
else:
    md_caption("Press the button to run this configuration.")
