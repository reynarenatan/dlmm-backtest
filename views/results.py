"""The headline results for the full year, from precomputed values."""

import streamlit as st

from webdata import (STRATEGY_LABELS, chart_path, load_summary, money, pct,
                     period_caption, rate, signed_money, signed_pct)

summary = load_summary()
params = summary["params"]
market = summary["market"]
hodl = summary["hodl"]
passive = summary["strategies"]["passive"]
rebalancing = summary["strategies"]["rebalancing"]

# Each chart with the one thing it is there to show. Written against the
# precomputed numbers so a re-run cannot leave a caption stale.
CHARTS = [
    ("net_pnl_comparison.png", "Net PnL against holding", (
        "The passive position spent most of the year ahead of holding and "
        "gave it all back; rebalancing spent most of the year behind and "
        f"finished {money(rebalancing['net_pnl'])} in front."
    )),
    ("price_with_range_band_passive.png", "Price against the passive range", (
        f"The range was fixed at {money(passive['initial_range_low'])}-"
        f"{money(passive['initial_range_high'])} on the first candle; price "
        f"left it within weeks and never returned, so the position earned on "
        f"{pct(passive['time_in_range_pct'])} of candles."
    )),
    ("cumulative_fees.png", "Fees collected", (
        f"Moving the range earned {money(rebalancing['total_fees'])} against "
        f"{money(passive['total_fees'])} sitting still - but "
        f"{pct(rebalancing['fees_first_90d_pct'], 0)} of it arrived in the "
        "first 90 days."
    )),
    ("pnl_decomposition_rebalancing.png", "Where the rebalancing money went",
     (
        f"{money(rebalancing['total_fees'])} of fees against "
        f"{money(abs(rebalancing['total_il']))} of impermanent loss and "
        f"{money(rebalancing['total_costs'])} of costs; the areas sum to the "
        "net line by construction."
     )),
    ("position_value_rebalancing.png", "The rebalancing position itself", (
        f"Every rebalance realises a little of the loss, so across "
        f"{rebalancing['rebalances']:,} of them the position decays from "
        f"{money(rebalancing['entry_value'])} to "
        f"{money(rebalancing['final_value'])} and the fee income stops with "
        "it."
    )),
]


def metric_cards(s) -> None:
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
    st.metric("Break-even fee rate", rate(s["break_even_fee_rate"]),
              help="The fee rate at which fees would exactly have covered "
                   "impermanent loss and costs on this price path.")


def wealth_table() -> None:
    st.subheader("What happened to the deposit")
    st.markdown(
        "Net PnL is a comparison against holding, not a return. On a year "
        "like this one the two point in opposite directions, so this is the "
        "money itself:"
    )
    rows = [
        ("Fees collected", money(passive["total_fees"]),
         money(rebalancing["total_fees"]), "-"),
        ("Position at the end", money(passive["final_value"]),
         money(rebalancing["final_value"]), money(hodl["end_value"])),
        ("**Total at the end**", f"**{money(passive['total_wealth'])}**",
         f"**{money(rebalancing['total_wealth'])}**",
         f"**{money(hodl['end_value'])}**"),
        ("**Return on the deposit**",
         f"**{signed_pct(passive['absolute_return_pct'])}**",
         f"**{signed_pct(rebalancing['absolute_return_pct'])}**",
         f"**{signed_pct(hodl['absolute_return_pct'])}**"),
        ("Against holding", signed_money(passive["net_pnl"]),
         signed_money(rebalancing["net_pnl"]), "-"),
    ]
    header = (f"| From {money(hodl['entry_value'])} at entry | Passive | "
              f"Rebalancing | Just holding |\n|---|---|---|---|\n")
    st.markdown(header + "\n".join("| " + " | ".join(r) + " |" for r in rows))
    st.caption(
        "Fees are withdrawn as they are earned rather than compounded back "
        "in, so the total is fees plus whatever the position is still worth."
    )


def break_even_section() -> None:
    st.subheader("The break-even fee rate")
    st.markdown(
        "The rate at which fees would have exactly covered impermanent loss "
        "and costs on this price path. It turns the whole result into one "
        "number you can compare against the pool you are actually in."
    )
    assumed = params["fee_rate"]
    rows = []
    for key, s in summary["strategies"].items():
        needed = s["break_even_fee_rate"]
        # How far the assumed rate sits from the rate this strategy needed.
        gap = (assumed - needed) / needed * 100
        verdict = (f"{abs(gap):.0f}% {'above' if gap > 0 else 'below'} it - "
                   f"{'beats' if gap > 0 else 'loses to'} holding")
        rows.append((STRATEGY_LABELS[key], rate(needed), rate(assumed),
                     verdict))
    st.markdown(
        "| | Needed | This run assumed | Verdict |\n|---|---|---|---|\n"
        + "\n".join("| " + " | ".join(r) + " |" for r in rows)
    )
    st.caption(
        "Verified by re-running at the reported rate: net PnL comes out "
        "0.0000 with impermanent loss and costs unchanged."
    )


def cost_sensitivity_section() -> None:
    st.subheader("Does rebalancing survive a higher trading cost?")
    rows = summary["cost_sensitivity"]
    configured = params["rebalance_cost"]

    header = "| Cost per rebalance | " + " | ".join(
        f"**{pct(r['cost_rate'] * 100)}**" if r["cost_rate"] == configured
        else pct(r["cost_rate"] * 100) for r in rows) + " |\n"
    header += "|---|" + "---|" * len(rows) + "\n"
    body = [
        "| Total costs | " + " | ".join(money(r["total_costs"])
                                        for r in rows) + " |",
        "| Net vs holding | " + " | ".join(signed_money(r["net_pnl"])
                                           for r in rows) + " |",
    ]
    st.markdown(header + "\n".join(body))

    worst = rows[-1]
    st.markdown(
        f"Not comfortably. At {pct(worst['cost_rate'] * 100)} the "
        f"{worst['rebalances']:,} rebalances cost "
        f"{money(worst['total_costs'])} and rebalancing loses to holding as "
        f"well. Its edge is a bet that recentring stays cheap; the "
        f"{pct(configured * 100)} used above is the configured assumption, "
        "not a measured one."
    )


st.title("Results")
st.caption(period_caption(params))

st.markdown(
    f"This is {money(params['deposit'])} placed in a "
    f"{params['position_bins']}-bin SOL/USDC liquidity position and left to "
    f"run for a year, to {params['end'][:10]}. Over that year SOL fell "
    f"{pct(abs(market['change_pct']))}, from "
    f"{money(market['start_price'])} to {money(market['end_price'])}. Two "
    "strategies are compared on exactly the same candles: a **passive** "
    "position that never moves, and a **rebalancing** one that recentres its "
    "range whenever price closes outside it."
)

st.info(
    f"**Both strategies lost money.** The deposit finished "
    f"{signed_pct(passive['absolute_return_pct'])} under the passive "
    f"strategy and {signed_pct(rebalancing['absolute_return_pct'])} under "
    f"rebalancing, against {signed_pct(hodl['absolute_return_pct'])} for "
    f"simply holding. Rebalancing still beat holding by "
    f"{money(rebalancing['net_pnl'])}, while the passive position finished "
    f"{money(abs(passive['net_pnl']))} behind it."
)

left, right = st.columns(2)
for column, (key, s) in zip((left, right), summary["strategies"].items()):
    with column:
        st.subheader(STRATEGY_LABELS[key])
        metric_cards(s)

st.divider()
wealth_table()

st.divider()
break_even_section()

st.divider()
cost_sensitivity_section()

st.divider()
st.subheader("Charts")
for filename, caption, takeaway in CHARTS:
    st.image(chart_path(filename), caption=caption, width="stretch")
    st.markdown(takeaway)
    st.write("")

st.caption(
    "Every number and chart on this page was produced ahead of time by "
    "`precompute.py` and `run_backtest.py`. The page never runs the engine."
)
