"""Run the engine once and write the numbers the web app reads.

The app never runs a backtest: a year of minute candles takes tens of
seconds per strategy, which is not something a page load can do. So the
results are computed here, ahead of time, and committed as JSON.

Re-run this after any change to config.py or the engine, or the app will
keep showing the previous numbers:

    python precompute.py
"""

import json
from pathlib import Path

from backtest import prepare, run
from fees import accumulate_bin_fees

OUT_PATH = Path("results/year_summary.json")

# What a results page quotes. Everything else stays in the run.
HEADLINE = ("total_fees", "total_il", "total_costs", "net_pnl", "net_apy",
            "gross_fee_apy", "break_even_fee_rate", "final_value",
            "rebalances", "time_in_range_pct")


def summarise(result) -> dict:
    """The headline metrics, plus what the deposit itself did.

    net_pnl is measured against holding, so on its own it cannot say
    whether the money grew: total_wealth and absolute_return answer that.
    """
    m, s = result["metrics"], result["series"]
    hodl_end = float(s["hodl"].iloc[-1])
    entry_value = float(s["value"].iloc[0])
    total_wealth = m["total_fees"] + m["final_value"]

    return {
        **{key: m[key] for key in HEADLINE},
        "entry_value": entry_value,
        "hodl_end": hodl_end,
        "total_wealth": total_wealth,
        "absolute_return_pct": (total_wealth / entry_value - 1) * 100,
    }


def build() -> dict:
    df = prepare()
    _, per_candle_bin_fees = accumulate_bin_fees(df)

    strategies, params = {}, None
    for strategy in ("passive", "rebalancing"):
        result = run(df, strategy=strategy,
                     per_candle_bin_fees=per_candle_bin_fees)
        strategies[strategy] = summarise(result)
        params = result["params"]

    hodl_end = strategies["passive"]["hodl_end"]
    entry_value = strategies["passive"]["entry_value"]

    return {
        "params": params,
        "hodl": {
            "entry_value": entry_value,
            "end_value": hodl_end,
            "absolute_return_pct": (hodl_end / entry_value - 1) * 100,
        },
        "strategies": strategies,
    }


if __name__ == "__main__":
    summary = build()
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    for name, s in summary["strategies"].items():
        print(f"  {name:<13} fees ${s['total_fees']:>8,.2f}   "
              f"net ${s['net_pnl']:>+8,.2f}   "
              f"absolute {s['absolute_return_pct']:>+6.1f}%")
