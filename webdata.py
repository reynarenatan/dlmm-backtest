"""What the pages read, and how they format it.

Every page imports from here rather than touching the engine. The engine
is never run by the web app: `precompute.py` writes results/year_summary.json
ahead of time and this module hands it out.
"""

import inspect
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
SUMMARY_PATH = ROOT / "results" / "year_summary.json"
CHART_DIR = ROOT / "outputs"

STRATEGY_LABELS = {
    "passive": "Passive",
    "rebalancing": "Rebalancing",
}

# What a page is entitled to find in the summary. Checked on load so that
# adding a field to a page and forgetting to re-run precompute.py fails
# with a sentence instead of a KeyError three screens down.
REQUIRED_TOP = ("params", "position_width_pct", "market", "hodl", "pool",
                "worked_example", "first_rebalance", "strategies",
                "cost_sensitivity")
REQUIRED_STRATEGY = ("total_fees", "total_il", "total_costs", "net_pnl",
                     "net_apy", "break_even_fee_rate", "final_value",
                     "rebalances", "time_in_range_pct", "max_drawdown",
                     "entry_value", "total_wealth", "absolute_return_pct",
                     "initial_range_low", "initial_range_high",
                     "fees_first_90d_pct")

STALE_MESSAGE = (
    "**The precomputed results are out of date.** This page expects fields "
    "that `results/year_summary.json` does not have: {missing}.\n\n"
    "Run `python precompute.py` and commit `results/year_summary.json`."
)


def _file_stamp(path):
    """Cache key ingredient: how the file looked when it was read.

    Caching on the path alone was a bug -- the cached value survives a
    deploy that changed only the data file, so the app serves the previous
    contents against the new code. Including size and mtime means any
    change to the file invalidates the cache.
    """
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@st.cache_data
def _read_summary(path_str, stamp) -> dict:
    """Read the summary. `stamp` is unused, and is the point: it is part of
    the cache key, so a changed file is a different call. It must not be
    named with a leading underscore -- Streamlit leaves those out of the
    key, which is the bug this whole function exists to close.
    """
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def missing_fields(summary) -> list:
    """Which required fields the summary does not have."""
    missing = [key for key in REQUIRED_TOP if key not in summary]
    for name, strategy in summary.get("strategies", {}).items():
        missing += [f"{name}.{key}" for key in REQUIRED_STRATEGY
                    if key not in strategy]
    return missing


def load_summary(path=SUMMARY_PATH) -> dict:
    """The precomputed results, or a clear stop if they cannot be used."""
    if not path.exists():
        st.error(STALE_MESSAGE.format(missing=f"the file `{path.name}` "
                                              "itself is not there"))
        st.stop()

    summary = _read_summary(str(path), _file_stamp(path))

    missing = missing_fields(summary)
    if missing:
        st.error(STALE_MESSAGE.format(
            missing="`" + "`, `".join(missing) + "`"))
        st.stop()
    return summary


def chart_path(name) -> str:
    return str(CHART_DIR / name)


def escape(text) -> str:
    """Escape the dollar signs in text bound for markdown.

    Streamlit reads a $...$ pair as LaTeX, so "$831.95 against $297.50"
    renders as italic maths with the dollar signs eaten. Every page here
    quotes money, so every markdown string goes through this.
    """
    return text.replace("$", r"\$")


def md(text, **kwargs) -> None:
    """st.markdown, with the money escaped."""
    st.markdown(escape(text), **kwargs)


def md_caption(text, **kwargs) -> None:
    """st.caption, with the money escaped."""
    st.caption(escape(text), **kwargs)


def md_info(text, **kwargs) -> None:
    """st.info, with the money escaped."""
    st.info(escape(text), **kwargs)


def money(x) -> str:
    return f"${x:,.2f}"


def money_round(x) -> str:
    """Money with the cents dropped, for figures big enough not to need them."""
    return f"${x:,.0f}"


def money_precise(x) -> str:
    """Money that keeps its digits below a cent.

    One minute's fee on a $1,000 position is fractions of a cent, and
    rounding it to $0.02 hides the very thing the worked example is
    showing.
    """
    return f"${x:,.4f}" if abs(x) < 1 else money(x)


def signed_money(x) -> str:
    return f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def pct(x, dp=1) -> str:
    return f"{x:.{dp}f}%"


def signed_pct(x, dp=1) -> str:
    return f"{x:+.{dp}f}%"


def rate(x, dp=4) -> str:
    """A fee rate held as a fraction, shown as a percentage."""
    return f"{x * 100:.{dp}f}%"


def period_caption(params) -> str:
    return (f"{params['start'][:10]} to {params['end'][:10]} - "
            f"{params['candles']:,} one-minute candles - "
            f"${params['deposit']:,} into a {params['position_bins']}-bin "
            f"range at bin step {params['bin_step']}")


def coming_soon(what) -> None:
    """Placeholder body for a page that is not built yet."""
    st.info(f"Coming soon - {what}")


def code_expander(label, *functions, expanded=False) -> None:
    """Show the real source of the functions behind a piece of prose.

    Read out of the live modules with inspect rather than pasted in: a
    copy would drift from the code the results came from, and a page
    claiming to show the implementation would then be lying. It also
    means renaming or editing a function updates this page for free.
    """
    with st.expander(label, expanded=expanded):
        for function in functions:
            st.caption(f"`{function.__module__}.{function.__qualname__}` "
                       f"in `{function.__module__}.py`")
            st.code(inspect.getsource(function), language="python")
