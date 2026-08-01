"""How the numbers on the Results page are produced.

Plain language, for a reader who has never used a DLMM. Everything
quantitative comes from the precomputed summary, including the worked
candle and the worked rebalance, so nothing here can drift away from what
the engine actually did.
"""

import streamlit as st

from webdata import (chart_path, load_summary, md, md_caption, money,
                     money_precise, money_round, pct, rate)

summary = load_summary()
params = summary["params"]
pool = summary["pool"]
example = summary["worked_example"]
rebal = summary["first_rebalance"]
passive = summary["strategies"]["passive"]
rebalancing = summary["strategies"]["rebalancing"]
width_pct = summary["position_width_pct"]

BIN_WIDTH_PCT = params["bin_step"] / 100  # 4 basis points = 0.04%

# Where each configured value came from. The point of the page: these are
# measured from live Meteora pools, not chosen to make the result work.
PROVENANCE = [
    ("Bin step", f"{params['bin_step']}",
     "The pool being modelled. It fixes how wide one bin is: "
     f"{BIN_WIDTH_PCT:.2f}% of price."),
    ("Pool share", pct(params["pool_share"] * 100, 0),
     "Measured, averaged over 16 observations in July 2026: the fraction "
     "of SOL market volume this pool handles."),
    ("Fee rate", rate(params["fee_rate"], 2),
     f"Meteora's base fee for bin step {params['bin_step']}."),
    ("TVL per bin", money_round(params["bin_tvl"]),
     "Measured: the liquidity sitting in the position's range, divided by "
     "the 69 bins that range covers. Derivation below."),
    ("Position width", f"{params['position_bins']} bins",
     f"Meteora's default range width, which is {pct(width_pct)} of price "
     f"at bin step {params['bin_step']}."),
    ("Deposit", money_round(params["deposit"]),
     "Chosen, not measured. Every result scales linearly with it."),
    ("Rebalance cost", pct(params["rebalance_cost"] * 100, 1),
     "Assumed, not measured: a stand-in for swap fee, slippage and gas on "
     "the value that changes hands. The Results page tests 0% and 0.5% "
     "against it."),
]

LIMITS = [
    ("Every bin holds the same fixed TVL",
     "Real liquidity moves. It thins as you go further from the current "
     "price, and other providers crowd into a range that is earning well, "
     "which would shrink our share exactly when it matters most. Holding "
     "it constant is the single biggest simplification here, and every fee "
     "number scales inversely with it."),
    ("The pool's share of volume is held constant",
     f"{pct(params['pool_share'] * 100, 0)} is an average of 16 "
     "observations, applied to every minute of the year. It really varies "
     "day to day, and all fee income scales linearly with it."),
    ("Fees are split across a candle's bins by price overlap",
     "A candle says the price visited a range, not how much volume traded "
     "at each point inside it. We assume volume is spread evenly across "
     "the range. Getting this exactly right needs tick data or on-chain "
     "swap events. It moves very little: on this dataset, switching to an "
     "equal split changes the totals by about 1%."),
    ("Inventory follows candle closes only",
     "A bin flips side when the close crosses it. A minute that spikes "
     "through several bins and comes back is treated as its close, so very "
     "short round trips inside a minute are invisible."),
    ("Fees are withdrawn, not compounded",
     "Earned fees sit outside the position rather than being redeposited. "
     "That is why the rebalancing position can decay to nothing while its "
     "fee total keeps rising."),
    ("Meteora's variable fee is not modelled",
     "Real DLMM pools add a volatility-driven component on top of the base "
     "fee, which would raise fee income in exactly the turbulent stretches "
     "this year had. The run uses the base fee only, so the fee side is "
     "conservative."),
    ("One price path, not a distribution",
     "This is a single year in which SOL fell "
     f"{pct(abs(summary['market']['change_pct']))}. It is one sample, not "
     "an expectation. A flat or rising year would rank these strategies "
     "differently, and nothing here says how likely this year was."),
    ("The data has small gaps",
     "180 minutes are missing across 15 gaps, 0.03% of the year. The "
     "engine steps through rows rather than assuming every minute is "
     "present, so these pass through as single long candles."),
]


def section_bins() -> None:
    st.subheader("1. What a bin is")
    md("A normal exchange lets you quote any price you like. A DLMM does "
       "not: it chops the price line into fixed steps called **bins**, and "
       "all liquidity has to sit in one of them.")
    md(f"Each bin is a narrow price slot - at bin step "
       f"{params['bin_step']}, exactly **{BIN_WIDTH_PCT:.2f}% wide**. A bin "
       "holds one token, never both, and which one depends on where it "
       "sits relative to the current price:")
    md("- Bins **below** the current price hold **USDC**, waiting to buy "
       "SOL if the price falls to them.\n"
       "- Bins **above** hold **SOL**, waiting to sell if the price rises "
       "to them.")
    md("Think of each bin as a resting limit order at a fixed price. You "
       "are not betting on a direction; you are offering to trade at every "
       "price in your range, and collecting a fee whenever someone takes "
       "you up on it.")
    st.image(chart_path("bin_grid.png"),
             caption="Two hours of SOL price against the bin grid",
             width="stretch")
    md(f"A position covers a contiguous run of bins. Ours is "
       f"{params['position_bins']} bins wide - Meteora's default - which "
       f"at {BIN_WIDTH_PCT:.2f}% per bin comes to about **{pct(width_pct)} "
       "of price** end to end. That is the whole game in one number: the "
       "position earns while price is inside that narrow window, and "
       "earns nothing outside it.")


def section_fee_chain() -> None:
    st.subheader("2. How a fee reaches us")
    md("Five steps take a minute of trading in the wider market down to "
       "cents in our position. Here is one real minute from the run, "
       f"**{example['timestamp'][:16]} UTC**, chosen because its volume is "
       "the median of the minutes where our position was in range - a "
       "typical minute, not a flattering one.")

    steps = [
        ("1", "SOL traded across the whole market that minute",
         money_round(example["market_volume"])),
        ("2", f"of which this pool handled "
              f"{pct(example['pool_share'] * 100, 0)}",
         money_round(example["pool_volume"])),
        ("3", f"charged at a {rate(example['fee_rate'], 2)} fee rate",
         money(example["candle_fee"])),
        ("4", f"split across the {len(example['bins'])} bins the price "
              "passed through",
         "see below"),
        ("5", f"of which we own {pct(example['share_of_bin_pct'], 3)} of "
              "each bin",
         f"**{money_precise(example['user_fee'])}**"),
    ]
    md("| | Step | Amount |\n|---|---|---|\n"
       + "\n".join(f"| {n} | {label} | {value} |" for n, label, value
                   in steps))

    md(f"**Step 4 in detail.** The price ran from "
       f"{money(example['low'])} to {money(example['high'])} that minute, "
       f"crossing {len(example['bins'])} bins. Each bin earns in "
       "proportion to how much of the candle's price range fell inside it, "
       "so the bins the price crossed fully earn more than the two at the "
       "ends that it only clipped:")
    rows = [
        (f"{b['bin_id']}", f"{money(b['low'])} - {money(b['high'])}",
         pct(b["share_of_candle_fee_pct"]), money(b["fee"]))
        for b in example["bins"]
    ]
    md("| Bin | Price range | Share of the fee | Fee |\n|---|---|---|---|\n"
       + "\n".join("| " + " | ".join(r) + " |" for r in rows))
    md_caption(
        f"The parts add back to {money(example['candle_fee'])}, the whole "
        "candle fee - the split is checked for exactly this on every "
        "candle in the run.")

    md(f"**Step 5 in detail.** We deposited "
       f"{money_round(params['deposit'])} spread evenly over "
       f"{params['position_bins']} bins, so "
       f"{money(example['deposit_per_bin'])} sits in each one. Against a "
       f"bin holding {money_round(example['bin_tvl'])} of everyone's "
       f"liquidity, we own {pct(example['share_of_bin_pct'], 3)} of it, "
       "and we earn that fraction of every fee that bin collects.")
    md(f"That is **{money_precise(example['user_fee'])}** from this "
       f"minute - about a cent and a half. Small, but there are "
       f"{params['candles']:,} minutes in the year, and this is what adds "
       "up into the fee totals on the Results page.")


def section_inventory() -> None:
    st.subheader("3. Inventory, and where impermanent loss comes from")
    md("Bins do not just collect fees; they trade. When the price crosses "
       "a bin, that bin's contents flip - **at that bin's own fixed "
       "price**, not at the price the market later reaches.")
    md("Follow a rising price. Each bin it climbs past was holding SOL, "
       "and each one sells that SOL as the price crosses it. You end up "
       "having sold your SOL piece by piece on the way up, every piece at "
       "a price *below* where the price finally settles. You still hold "
       "the proceeds - you simply sold too early, all the way up.")
    md("That gap has a name: **impermanent loss**. It is measured against "
       "the plainest possible alternative - keeping the tokens you "
       "deposited and doing nothing. It is not a fee, a loss on paper, or "
       "money taken from you; it is the amount by which trading through "
       "your bins did worse than sitting still.")
    st.image(chart_path("position_vs_hodl_passive.png"),
             caption="The passive position against simply holding",
             width="stretch")
    md(f"The gap between the two lines is the impermanent loss - "
       f"{money(abs(passive['total_il']))} by the end for the passive "
       "position. Two things follow, and both matter for reading the "
       "results:")
    md("- It is called *impermanent* because it closes if the price comes "
       "back. Return to where you started and the gap goes to zero. It "
       "only becomes permanent when you leave, or when the range moves.\n"
       "- Out of range you get the worst of it: the price has passed all "
       "your bins, so you hold 100% of the falling token, earn no fees, "
       "and still carry the loss.")
    md("So a position has two legs pulling against each other: fees "
       "earned, and impermanent loss suffered. The whole engine exists to "
       "measure both on the same price path and see which wins.")


def section_rebalancing() -> None:
    st.subheader("4. What rebalancing does")
    md("A passive position is set once and left. A rebalancing position "
       "chases the price:")
    md("- **The trigger.** A candle closes outside the range. There is no "
       "profit test and no waiting period - out is out.\n"
       "- **The action.** Everything is marked at the current price, and "
       "the same-width range is reopened centred on where the price is "
       "now.\n"
       "- **The cost.** Reopening means holding a different mix of tokens, "
       f"so some have to be traded. We charge "
       f"{pct(params['rebalance_cost'] * 100, 1)} of whatever changes "
       "hands, standing in for swap fee, slippage and gas.")
    if rebal:
        md(f"**The first one in the run, {rebal['timestamp'][:16]} UTC.** "
           f"The price closed at {money(rebal['close'])}, below the "
           f"opening range of {money(rebal['old_low'])}-"
           f"{money(rebal['old_high'])}. Falling out of range means every "
           f"bin had already flipped to SOL, so recentring meant "
           f"**{rebal['direction'].lower()}ing "
           f"{rebal['sol_traded']:.4f} SOL** "
           f"({money(rebal['value_traded'])} changing hands, costing "
           f"{money(rebal['cost'])}) to refill the bins below. The new "
           f"range became {money(rebal['new_low'])}-"
           f"{money(rebal['new_high'])}.")
    md("Notice the direction. You fall out of range by the price "
       "dropping, and recentring makes you **sell low**; you rise out of "
       "range, and it makes you **buy high**. Each rebalance takes the "
       "impermanent loss you had accumulated and makes it permanent. "
       f"Over {rebalancing['rebalances']:,} of them that compounds - which "
       "is why the Results page shows the rebalancing position decaying to "
       "almost nothing even while its fee total climbs.")
    md("Rebalancing is therefore a straight trade: stay in range and keep "
       "earning fees, and pay for it in realised losses and costs. On this "
       "year it was worth it against holding, and still lost money.")


def section_provenance() -> None:
    st.subheader("5. Where the parameters come from")
    md("Backtests are easy to rig through their inputs. Most of these are "
       "measured from live Meteora pools rather than chosen, and the ones "
       "that are not are marked:")
    md("| Parameter | Value | Source |\n|---|---|---|\n"
       + "\n".join(f"| {name} | **{value}** | {source} |"
                   for name, value, source in PROVENANCE))
    md(f"**How the {money_round(params['bin_tvl'])} per bin was "
       "derived**, since it is the least obvious and every fee number "
       "moves with it:")
    md(f"1. At bin step {params['bin_step']}, a band of plus or minus 1% "
       "around the price is 50 bins wide.\n"
       "2. The tracked pool held about $723,000 of liquidity in that "
       "band.\n"
       "3. That is about $14,460 per bin - but only across those inner 50 "
       f"bins.\n"
       f"4. Our {params['position_bins']}-bin position reaches beyond that "
       "band into thinner liquidity, so interpolating the density out to "
       f"{params['position_bins']} bins gives about $13,440 per bin, and "
       f"we use {money_round(params['bin_tvl'])}.")
    md_caption(
        "Our share of a bin is deposit-per-bin divided by this number, so "
        "a 10% error here is a 10% error on every fee figure in the app.")


def section_limits() -> None:
    st.subheader("6. What this model does not do")
    md("Every simplification, in one place. None of them is hidden in the "
       "results, and the ones that would flatter the strategies are called "
       "out as such.")
    for title, detail in LIMITS:
        md(f"**{title}.** {detail}")
    md("The honest summary: this measures the two legs - fee income and "
       "impermanent loss - carefully and against real price data, on one "
       "year, with liquidity depth held still. It is a good tool for "
       "comparing strategies against each other on the same path. It is "
       "not a forecast of what a position would earn next year.")


st.title("How it works")
md_caption("How the numbers on the Results page are produced, start to "
           "finish")

md("A liquidity position earns trading fees and suffers impermanent loss. "
   "Everything in this app is an attempt to measure those two things "
   "honestly, minute by minute, against a real year of SOL prices. This "
   "page explains how, in the order the engine does it.")

st.divider()
section_bins()

st.divider()
section_fee_chain()

st.divider()
section_inventory()

st.divider()
section_rebalancing()

st.divider()
section_provenance()

st.divider()
section_limits()

md_caption(
    "The worked candle and the worked rebalance are real rows from the "
    "run, computed by `precompute.py` with the same functions the backtest "
    "uses. This page never runs the engine."
)
