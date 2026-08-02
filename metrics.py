"""Every number a single run reports, computed from its series.

Pure and side-effect free: `compute_metrics` takes the per-candle series
that backtest.run built and returns a flat dict of scalars. Flat and
JSON-serialisable on purpose -- a results store can write it straight
out, and a report or a web page can read it without knowing how a
backtest works.

The headline metric here is the BREAK-EVEN FEE RATE: the fee rate at
which fees would exactly have covered impermanent loss and costs. Fees
scale linearly with the rate (fee = volume x pool_share x rate, and fee
income is never reinvested), while IL and rebalance costs do not depend
on it at all, so

    break_even = fee_rate x (costs - IL) / fees

is exact rather than an approximation. verify_break_even() checks that by
re-running at the reported rate instead of trusting the algebra.
"""

import math


def _f(x):
    """Plain Python float, so the dict serialises without numpy types."""
    return None if x is None else float(x)


def _drawdown(net):
    """Max drawdown of a PnL curve, in dollars, with its dates.

    A PnL curve crosses zero, so a percentage drawdown would be
    meaningless; this is peak-to-trough in dollars.
    """
    peak = net.cummax()
    dd = peak - net
    trough_i = dd.idxmax()
    peak_i = net.loc[:trough_i].idxmax()
    return float(dd.loc[trough_i]), peak_i, trough_i


def compute_metrics(series, events, params) -> dict:
    days = params["days"]
    deposit = params["deposit"]
    ts = series["timestamp"]
    dates = ts.dt.date

    total_fees = float(series["cum_fees"].iloc[-1])
    total_costs = float(series["cum_costs"].iloc[-1])
    total_il = float(series["il"].iloc[-1])
    net_pnl = float(series["net_pnl"].iloc[-1])

    # --- fee income vs what it had to cover -------------------------------
    # Two APYs side by side: the gap between them is exactly what IL and
    # costs ate out of the fee income.
    gross_fee_apy = total_fees / days * 365 / deposit
    net_apy = net_pnl / days * 365 / deposit

    needed = total_costs - total_il  # fees required for net_pnl == 0
    break_even_fee_rate = (params["fee_rate"] * needed / total_fees
                           if total_fees > 0 else None)

    # --- drawdown ---------------------------------------------------------
    max_dd, peak_i, trough_i = _drawdown(series["net_pnl"])

    # --- activity ---------------------------------------------------------
    # Every bin boundary the price crossed: |change in active bin| summed.
    steps = series["active_bin"].diff().fillna(0).abs()

    # --- days in and out of range ----------------------------------------
    by_day_in_range = series.groupby(dates)["in_range"].mean()
    days_fully_in = int((by_day_in_range == 1).sum())
    days_fully_out = int((by_day_in_range == 0).sum())

    # --- best and worst day ----------------------------------------------
    # Per-candle change in net PnL summed per calendar day, so the first
    # day is measured from zero rather than dropped.
    step_pnl = series["net_pnl"].diff()
    step_pnl.iloc[0] = series["net_pnl"].iloc[0]
    by_day_pnl = step_pnl.groupby(dates).sum()

    # --- what the position ended holding ----------------------------------
    end_close = float(series["close"].iloc[-1])
    end_sol = float(series["sol_held"].iloc[-1])
    end_usdc = float(series["usdc_held"].iloc[-1])
    end_value = float(series["value"].iloc[-1])

    # --- what the money did, as opposed to how it did against holding -----
    # net_pnl answers the second question. These answer the first, and on a
    # falling market they point opposite ways: a position can beat holding
    # and still end below what went in.
    #
    # entry_value is the deposit as the position is actually marked on the
    # first candle, which is a little under the deposit itself -- the bins
    # above the price hold tokens bought at their own, higher price. It is
    # also the hold baseline's entry, since both start from the same
    # tokens, so it is the denominator both returns are measured from.
    entry_value = float(series["value"].iloc[0])
    hodl_final_value = float(series["hodl"].iloc[-1])

    m = {
        # money
        "total_fees": total_fees,
        "total_il": total_il,
        "total_costs": total_costs,
        "net_pnl": net_pnl,
        "gross_fee_apy": _f(gross_fee_apy),
        "net_apy": _f(net_apy),
        "il_pct_of_deposit": _f(total_il / deposit * 100),
        "fees_covered_il": bool(net_pnl > 0),
        "break_even_fee_rate": _f(break_even_fee_rate),
        # risk
        "max_drawdown": max_dd,
        "max_drawdown_date": str(ts.loc[trough_i]),
        "max_drawdown_peak_date": str(ts.loc[peak_i]),
        # time in range
        "time_in_range_pct": _f(series["in_range"].mean() * 100),
        "days_total": int(by_day_in_range.size),
        "days_fully_in_range": days_fully_in,
        "days_fully_out_of_range": days_fully_out,
        "days_partially_in_range": int(by_day_in_range.size
                                       - days_fully_in - days_fully_out),
        # activity
        "bin_crossings": int(steps.sum()),
        "candles_with_crossing": int((steps > 0).sum()),
        # best / worst day
        "best_day": str(by_day_pnl.idxmax()),
        "best_day_pnl": _f(by_day_pnl.max()),
        "worst_day": str(by_day_pnl.idxmin()),
        "worst_day_pnl": _f(by_day_pnl.min()),
        # what the deposit became
        "entry_value": entry_value,
        "hodl_final_value": hodl_final_value,
        # final composition
        "final_value": end_value,
        "final_sol": end_sol,
        "final_usdc": end_usdc,
        "final_pct_sol": _f(end_sol * end_close / end_value * 100
                            if end_value > 0 else 0.0),
        # rebalancing
        "rebalances": len(events),
    }
    m.update(_rebalance_metrics(series, events))
    return m


def _rebalance_metrics(series, events) -> dict:
    """Interval, clustering and decay metrics; zeros when nothing moved."""
    month_end = (series.set_index("timestamp")["value"]
                 .resample("ME").last())
    out = {
        "month_end_values": {f"{d:%Y-%m}": _f(v)
                             for d, v in month_end.items()},
    }
    if not events:
        return out | {
            "rebalance_gap_min_minutes": None,
            "rebalance_gap_median_minutes": None,
            "rebalance_gap_mean_minutes": None,
            "rebalance_gap_max_minutes": None,
            "rebalances_within_5min": 0,
            "mean_cost_per_rebalance_pct": None,
            "value_change_per_rebalance_pct": None,
        }

    at = series["timestamp"].iloc[[e["index"] for e in events]]
    gaps = at.diff().dropna().dt.total_seconds() / 60

    # The explicit charge per rebalance: REBALANCE_COST on the value that
    # changed hands, as a share of the position it was taken from. This is
    # NOT the whole cost of recentring -- the buy-high/sell-low part is
    # realised over the excursion, not at the instant. strategies.py's
    # oscillation check isolates that on a closed price loop.
    costs = [e["cost"] / e["value_before"] * 100
             for e in events if e["value_before"] > 0]

    v0 = float(series["value"].iloc[0])
    v1 = float(series["value"].iloc[-1])
    per_rebalance = (math.exp(math.log(v1 / v0) / len(events)) - 1
                     if v0 > 0 and v1 > 0 else None)

    return out | {
        "rebalance_gap_min_minutes": _f(gaps.min()),
        "rebalance_gap_median_minutes": _f(gaps.median()),
        "rebalance_gap_mean_minutes": _f(gaps.mean()),
        "rebalance_gap_max_minutes": _f(gaps.max()),
        "rebalances_within_5min": int((gaps <= 5).sum()),
        "mean_cost_per_rebalance_pct": _f(sum(costs) / len(costs))
                                       if costs else None,
        # Geometric average change in position value per rebalance over the
        # run. It includes price moves, so it is an outcome measure, not the
        # isolated cost of recentring.
        "value_change_per_rebalance_pct": _f(per_rebalance * 100
                                             if per_rebalance is not None
                                             else None),
    }


# ======================================================================
# Verification
# ======================================================================

def verify_break_even(strategy="rebalancing", df=None, path=None,
                      tolerance=0.01) -> None:
    """Re-run at the reported break-even rate; net PnL must land on zero.

    The rate is derived algebraically, so this checks the derivation
    against the engine rather than against itself: nothing in the second
    run knows where its fee rate came from.
    """
    from backtest import prepare, run

    df = prepare(df, path)
    base = run(df, strategy=strategy)
    rate = base["metrics"]["break_even_fee_rate"]
    print(f"  {strategy}: fees ${base['metrics']['total_fees']:.2f}, "
          f"IL ${base['metrics']['total_il']:.2f}, "
          f"costs ${base['metrics']['total_costs']:.2f} "
          f"-> net ${base['metrics']['net_pnl']:+.2f} "
          f"at FEE_RATE {base['params']['fee_rate']:.6%}")
    print(f"  break-even fee rate: {rate:.6%}")

    again = run(df, strategy=strategy, fee_rate=rate)
    net = again["metrics"]["net_pnl"]
    print(f"  re-run at {rate:.6%}: fees "
          f"${again['metrics']['total_fees']:.2f}, net ${net:+.4f}")
    assert abs(net) < tolerance, (
        f"re-running at the break-even rate should give net PnL 0, got {net}"
    )
    # IL and costs must be untouched by the fee rate -- if they moved, fees
    # are feeding back into the position and the whole derivation is void.
    assert abs(again["metrics"]["total_il"]
               - base["metrics"]["total_il"]) < 1e-6
    assert abs(again["metrics"]["total_costs"]
               - base["metrics"]["total_costs"]) < 1e-6
    print(f"  net PnL is 0 to within ${tolerance}, and IL and costs are "
          "unchanged by the fee rate -- PASS")


if __name__ == "__main__":
    from backtest import prepare

    print("=" * 72)
    print("Break-even fee rate: re-run at the reported rate must net zero")
    print("=" * 72)
    df = prepare()
    for strategy in ("passive", "rebalancing"):
        verify_break_even(strategy=strategy, df=df)
        print()
