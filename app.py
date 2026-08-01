"""DLMM backtest results, as a web page.

Reads precomputed numbers only. Running the engine here would mean tens of
seconds of work on a page load, so `precompute.py` does it ahead of time
and commits the result; this file formats what it wrote.

    streamlit run app.py
"""

import json
from pathlib import Path

import streamlit as st

SUMMARY_PATH = Path(__file__).parent / "results" / "year_summary.json"

STRATEGY_LABELS = {
    "passive": "Passive",
    "rebalancing": "Rebalancing",
}


@st.cache_data
def load_summary(path=SUMMARY_PATH):
    return json.loads(path.read_text(encoding="utf-8"))


def money(x):
    return f"${x:,.2f}"


def signed_money(x):
    return f"{'-' if x < 0 else '+'}${abs(x):,.2f}"


def pct(x, dp=1):
    return f"{x:.{dp}f}%"


def metric_cards(s):
    """The six headline numbers for one strategy."""
    st.metric("Fees earned", money(s["total_fees"]),
              help="Trading fees the position collected over the year.")
    st.metric("Impermanent loss", signed_money(s["total_il"]),
              help="What the position gave up against simply holding the "
                   "tokens it started with.")
    st.metric("Rebalancing costs",
              money(s["total_costs"]) if s["total_costs"] else "--",
              help="Charged on the value that changed hands each time the "
                   "range moved." if s["total_costs"]
                   else "This strategy never moves its range.")
    st.metric("Net vs holding", signed_money(s["net_pnl"]),
              help="Fees minus impermanent loss and costs. A comparison "
                   "against holding, not a return on the deposit.")
    st.metric("Net APY", pct(s["net_apy"] * 100),
              help="The same comparison, annualised.")
    st.metric("Break-even fee rate", pct(s["break_even_fee_rate"] * 100, 4),
              help="The fee rate at which fees would exactly have covered "
                   "impermanent loss and costs on this price path.")


st.set_page_config(page_title="DLMM Backtest", layout="wide")

summary = load_summary()
params, hodl = summary["params"], summary["hodl"]
passive = summary["strategies"]["passive"]
rebalancing = summary["strategies"]["rebalancing"]

st.title("DLMM backtest results")
st.caption(
    f"{params['start'][:10]} to {params['end'][:10]} - "
    f"{params['candles']:,} one-minute candles - "
    f"${params['deposit']:,} into a {params['position_bins']}-bin range at "
    f"bin step {params['bin_step']}"
)

st.info(
    f"**Both strategies lost money.** The deposit finished "
    f"{pct(passive['absolute_return_pct'])} under the passive strategy and "
    f"{pct(rebalancing['absolute_return_pct'])} under rebalancing, against "
    f"{pct(hodl['absolute_return_pct'])} for simply holding. Rebalancing "
    f"still beat holding by {money(rebalancing['net_pnl'])}, while the "
    f"passive position finished {money(abs(passive['net_pnl']))} behind it."
)

left, right = st.columns(2)
for column, (key, s) in zip((left, right), summary["strategies"].items()):
    with column:
        st.subheader(STRATEGY_LABELS[key])
        metric_cards(s)

st.caption(
    "Precomputed by `precompute.py` and read from "
    "`results/year_summary.json`. This page never runs the engine."
)
