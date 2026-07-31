"""Turning a run's result dict into something a person reads.

Everything here takes the dict backtest.run() returns and writes to
stdout. Nothing computes: if a number is missing, it belongs in
metrics.py, not here.
"""

import textwrap

WIDTH = 78


def _hr(title=""):
    if title:
        print(f"\n{title}")
        print("-" * WIDTH)
    else:
        print("-" * WIDTH)


def _row(label, value, note=""):
    print(f"  {label:<34} {value:>18}  {note}".rstrip())


def _money(x):
    return f"${x:,.2f}" if x is not None else "n/a"


def _pct(x, dp=1):
    return f"{x:.{dp}f}%" if x is not None else "n/a"


def _minutes(x):
    """Minutes as something readable: 7 min, 3.2 h, 4.1 d."""
    if x is None:
        return "n/a"
    if x < 90:
        return f"{x:.0f} min"
    if x < 60 * 48:
        return f"{x / 60:.1f} h"
    return f"{x / 1440:.1f} d"


def print_report(result) -> None:
    """The full metrics report for one run."""
    p, m = result["params"], result["metrics"]

    print("=" * WIDTH)
    print(f"{p['strategy'].upper()}  --  {p['position_bins']}-bin position, "
          f"${p['deposit']:,} deposit")
    print("=" * WIDTH)
    _row("dataset", p["dataset"])
    _row("period", f"{p['start'][:10]} to {p['end'][:10]}",
         f"{p['days']:.0f} days, {p['candles']:,} candles")
    _row("fee rate / pool share",
         f"{p['fee_rate']:.4%} / {p['pool_share']:.1%}",
         f"{p['fee_distribution']} split")
    _row("bin step / rebalance cost",
         f"{p['bin_step']} bps / {p['rebalance_cost']:.2%}")

    _hr("RESULT")
    _row("fees earned", _money(m["total_fees"]))
    _row("impermanent loss", _money(m["total_il"]),
         f"{_pct(m['il_pct_of_deposit'])} of deposit")
    _row("rebalancing costs",
         _money(-m["total_costs"] if m["total_costs"] else 0.0))
    _row("net PnL vs holding", _money(m["net_pnl"]),
         "fees covered IL" if m["fees_covered_il"] else "IL exceeded fees")
    _row("gross fee APY", _pct(m["gross_fee_apy"] * 100),
         "fees only, ignoring IL")
    _row("net APY", _pct(m["net_apy"] * 100), "vs holding, after IL + costs")
    _row("  gap between them",
         _pct((m["gross_fee_apy"] - m["net_apy"]) * 100),
         "what IL and costs ate")
    _row("BREAK-EVEN FEE RATE",
         f"{m['break_even_fee_rate']:.4%}" if m["break_even_fee_rate"]
         else "n/a",
         f"run used {p['fee_rate']:.4%}")

    _hr("RISK")
    _row("max drawdown of net PnL", _money(m["max_drawdown"]))
    _row("  peaked", m["max_drawdown_peak_date"][:16])
    _row("  trough", m["max_drawdown_date"][:16])
    _row("best day", _money(m["best_day_pnl"]), m["best_day"])
    _row("worst day", _money(m["worst_day_pnl"]), m["worst_day"])

    _hr("TIME IN RANGE")
    _row("candles earning fees", _pct(m["time_in_range_pct"]))
    _row("days fully in range",
         f"{m['days_fully_in_range']} / {m['days_total']}")
    _row("days fully out of range",
         f"{m['days_fully_out_of_range']} / {m['days_total']}")
    _row("days partially in range",
         f"{m['days_partially_in_range']} / {m['days_total']}")

    _hr("ACTIVITY")
    _row("bin boundaries crossed", f"{m['bin_crossings']:,}")
    _row("candles that crossed one", f"{m['candles_with_crossing']:,}",
         _pct(m["candles_with_crossing"] / p["candles"] * 100))

    _hr("ENDED HOLDING")
    _row("position value", _money(m["final_value"]))
    _row("SOL", f"{m['final_sol']:,.4f}", _pct(m["final_pct_sol"], 0)
         + " of value")
    _row("USDC", _money(m["final_usdc"]))

    if m["rebalances"]:
        _print_rebalancing(m)

    _print_month_ends(m)
    _hr("IN PLAIN ENGLISH")
    print(summary_text(result))
    print()


def _print_rebalancing(m) -> None:
    _hr("REBALANCING")
    _row("rebalances", f"{m['rebalances']:,}")
    _row("time between: min", _minutes(m["rebalance_gap_min_minutes"]))
    _row("              median", _minutes(m["rebalance_gap_median_minutes"]))
    _row("              mean", _minutes(m["rebalance_gap_mean_minutes"]))
    _row("              max", _minutes(m["rebalance_gap_max_minutes"]))
    _row("within 5 min of previous", f"{m['rebalances_within_5min']:,}",
         _pct(m["rebalances_within_5min"] / m["rebalances"] * 100))
    _row("mean explicit cost each",
         _pct(m["mean_cost_per_rebalance_pct"], 3), "of position value")
    _row("value change per rebalance",
         _pct(m["value_change_per_rebalance_pct"], 3),
         "geometric, includes price")


def _print_month_ends(m) -> None:
    values = m["month_end_values"]
    if len(values) < 2:
        return
    _hr("POSITION VALUE AT MONTH END")
    for month, value in values.items():
        bar = "#" * max(0, min(40, round(value / max(values.values()) * 40)))
        print(f"  {month}  {value:>12,.2f}  {bar}")


def summary_text(result) -> str:
    """A paragraph someone who has never used this tool can follow."""
    p, m = result["params"], result["metrics"]
    verb = ("never moved" if p["strategy"] == "passive"
            else f"was recentred {m['rebalances']:,} times")

    parts = [
        f"A ${p['deposit']:,} deposit was placed in a {p['position_bins']}-bin "
        f"price range and {verb} over {p['days']:.0f} days "
        f"({p['start'][:10]} to {p['end'][:10]}).",

        f"It collected {_money(m['total_fees'])} in trading fees.",

        f"Over the same period the price moved, which left the position "
        f"worth {_money(-m['total_il'])} less than simply holding the "
        f"original tokens would have been - that gap is impermanent loss.",
    ]
    if m["total_costs"] > 0:
        parts.append(f"Rebalancing cost a further {_money(m['total_costs'])}.")

    if m["fees_covered_il"]:
        parts.append(
            f"The fees more than covered it: the position finished "
            f"{_money(m['net_pnl'])} ahead of just holding "
            f"({_pct(m['net_apy'] * 100)} a year).")
    else:
        parts.append(
            f"The fees did not cover it: the position finished "
            f"{_money(-m['net_pnl'])} behind just holding "
            f"({_pct(m['net_apy'] * 100)} a year).")

    if m["time_in_range_pct"] >= 99.95:
        parts.append(
            "The position was inside its price range, and so earning fees, "
            "essentially the whole time - moving the range kept it there.")
    else:
        parts.append(
            f"The position was inside its price range, and so earning fees, "
            f"{_pct(m['time_in_range_pct'])} of the time; for the rest it "
            f"earned nothing while still being exposed to the price.")

    if m["break_even_fee_rate"]:
        cmp = ("above" if m["break_even_fee_rate"] < p["fee_rate"]
               else "below")
        parts.append(
            f"Fees would have exactly covered the loss at a fee rate of "
            f"{m['break_even_fee_rate']:.4%}; this run assumed "
            f"{p['fee_rate']:.4%}, which is {cmp} it.")

    parts.append(
        f"The position ended worth {_money(m['final_value'])}, held as "
        f"{m['final_sol']:,.4f} SOL and {_money(m['final_usdc'])}.")

    return textwrap.fill(" ".join(parts), width=WIDTH,
                         initial_indent="  ", subsequent_indent="  ")


if __name__ == "__main__":
    import sys

    from backtest import prepare, run

    df = prepare()
    for strategy in sys.argv[1:] or ["passive", "rebalancing"]:
        print_report(run(df, strategy=strategy))
