"""What the pages read, and how they format it.

Every page imports from here rather than touching the engine. The engine
is never run by the web app: `precompute.py` writes results/year_summary.json
ahead of time and this module hands it out.
"""

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


@st.cache_data
def load_summary(path=SUMMARY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
