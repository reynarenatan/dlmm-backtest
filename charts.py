"""Charts for a run. Every function takes data and returns a figure.

Nothing here writes a file. run_backtest.py saves these to outputs/ for
the README and the web app; anything else calls the same functions and
hands the figures somewhere else.

Colours come from one palette shared by every chart, so a colour means
the same thing across the whole report. The two that ever share an axis
(blue vs orange for the two strategies, blue vs red for fees vs IL) were
checked for colour-blind separation rather than picked by eye.
"""

import matplotlib.pyplot as plt
import numpy as np

from bin_math import get_bin_id_from_price, get_price_from_bin_id
from candle_bins import raw_to_ui, ui_to_raw

# Chart chrome: text and rules never wear a series colour.
INK = {
    "primary": "#0b0b0b",
    "secondary": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "surface": "#fcfcfb",
}

# Series roles. Strategy identity is blue/orange; inside one run the roles
# are gain (blue) vs loss (red), with the net line in plain ink.
COLOR = {
    "passive": "#2a78d6",
    "rebalancing": "#eb6834",
    "fees": "#2a78d6",
    "il": "#e34948",
    "costs": "#898781",
    "net": "#0b0b0b",
    "value": "#2a78d6",
    "hodl": "#eb6834",
    "price": "#52514e",
    "band": "#2a78d6",
}

LINE_W = 1.8

# Points of space above the axes for a title that has a subtitle under it.
TITLE_PAD = 20

# A year of minute candles is 525,420 points drawn into about 1,500 pixels.
# Rasterising all of them costs ~15 s per chart and shows nothing extra.
CHART_MAX_POINTS = 12_000


def _decimate(s, column, max_points=CHART_MAX_POINTS):
    """Thin a long series for DRAWING only, keeping `column`'s envelope.

    Every series in one chart has to keep a common x -- stacked fills
    depend on it -- so buckets are taken on the row index and each bucket
    contributes the two rows where `column` hits its min and max. Spikes
    survive; the redundancy between them does not. Metrics are always
    computed on the full series: nothing reported here is thinned.
    """
    n = len(s)
    if n <= max_points:
        return s
    values = s[column].values
    edges = np.linspace(0, n, max_points // 2 + 1).astype(int)
    keep = {0, n - 1}
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi > lo:
            keep.add(lo + int(np.argmin(values[lo:hi])))
            keep.add(lo + int(np.argmax(values[lo:hi])))
    return s.iloc[sorted(keep)]


def _axes(figsize=(10, 5)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(INK["surface"])
    ax.set_facecolor(INK["surface"])
    ax.grid(True, color=INK["grid"], lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK["muted"], labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK["axis"])
    return fig, ax


def _esc(text):
    """Escape the dollar signs in a label.

    Matplotlib reads a $...$ pair as maths, so "$996.96 at the start,
    $0.02 at the end" renders as "996.96atthestart, 0.02 at the end" in
    italics. Everything drawn here quotes money, so everything is escaped.
    """
    return text.replace("$", r"\$")


def _finish(fig, ax, title, ylabel, legend=True, subtitle=None):
    # A subtitle sits in the gap between axes and title, so the title has
    # to be padded out of the way or the two are drawn on top of each other.
    ax.set_title(_esc(title), fontsize=11, color=INK["secondary"], loc="left",
                 pad=TITLE_PAD if subtitle else 6)
    ax.set_ylabel(ylabel, color=INK["muted"], fontsize=9)
    if subtitle:
        ax.text(0.0, 1.01, _esc(subtitle), transform=ax.transAxes, fontsize=9,
                color=INK["muted"], ha="left", va="bottom")
    if legend:
        leg = ax.legend(loc="best", frameon=False, fontsize=9)
        for text in leg.get_texts():
            text.set_color(INK["secondary"])
            text.set_text(_esc(text.get_text()))
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def _label(result):
    return result["params"]["strategy"]


def _bin_edges_ui(bins, bin_step):
    """Lower-edge UI price for an array of bin ids, via a small cache.

    The passive position has one range for the whole run and the
    rebalancing one has a few thousand, so resolving the unique ids and
    mapping back beats calling the price math half a million times.
    """
    lookup = {b: raw_to_ui(get_price_from_bin_id(int(b), bin_step))
              for b in np.unique(bins)}
    return np.array([lookup[int(b)] for b in bins])


# ======================================================================
# Single-run charts
# ======================================================================

# Days shown when the range moves. A 69-bin range at step 4 spans about
# 2.8% of price, so against a full year of a 62% fall it is a hairline
# sitting on the price line -- true, and showing nothing. Over a month the
# axis is tight enough for the band and its steps to be visible.
MOVING_RANGE_WINDOW_DAYS = 30


def price_with_range_band(result):
    """Price path with the position's range drawn as a shaded band.

    Where the line leaves the band, the position was out of range and
    earning nothing -- the thing a "time in range" percentage states but
    does not show.

    A range that never moves is drawn over the whole run. A range that
    recentres is drawn over the opening window instead, because a band
    that tracks the price is invisible at full-year scale.
    """
    p, m = result["params"], result["metrics"]
    full = result["series"]
    moves = bool(m["rebalances"])

    if moves:
        window = min(len(full), MOVING_RANGE_WINDOW_DAYS * 1440)
        full = full.iloc[:window]
    s = _decimate(full, "close")
    fig, ax = _axes(figsize=(10, 5))

    lo = _bin_edges_ui(s["range_start"].values, p["bin_step"])
    hi = _bin_edges_ui(s["range_end"].values + 1, p["bin_step"])

    ax.fill_between(s["timestamp"], lo, hi, color=COLOR["band"], alpha=0.30,
                    lw=0, label="position range")
    ax.plot(s["timestamp"], s["close"], color=COLOR["price"], lw=1.2,
            label="SOL price")

    if moves:
        moved = (full["range_start"] != full["range_start"].shift()).sum() - 1
        subtitle = (f"first {MOVING_RANGE_WINDOW_DAYS} days -- the range "
                    f"recentres {moved:,} times in this window and "
                    f"{m['rebalances']:,} times over the year, so the band "
                    f"tracks the price")
    else:
        subtitle = f"in range {m['time_in_range_pct']:.1f}% of candles"

    return _finish(
        fig, ax,
        f"Price against the {p['strategy']} position's range",
        "price (USD)", subtitle=subtitle)


def pnl_decomposition(result):
    """The money chart: fees up, IL down, costs down, net PnL on top.

    The stacked areas sum to the net line by construction
    (net = fees + IL - costs), so the picture is the accounting identity.
    """
    m = result["metrics"]
    s = _decimate(result["series"], "net_pnl")
    fig, ax = _axes(figsize=(10, 5.5))
    t = s["timestamp"]

    ax.axhline(0, color=INK["axis"], lw=0.8)
    ax.fill_between(t, 0, s["cum_fees"], color=COLOR["fees"], alpha=0.55,
                    lw=0, label=f"fees earned (${m['total_fees']:,.0f})")
    ax.fill_between(t, 0, s["il"], color=COLOR["il"], alpha=0.55, lw=0,
                    label=f"impermanent loss (${m['total_il']:,.0f})")
    if m["total_costs"] > 0:
        ax.fill_between(t, s["il"], s["il"] - s["cum_costs"],
                        color=COLOR["costs"], alpha=0.65, lw=0,
                        label=f"rebalance costs (-${m['total_costs']:,.0f})")
    ax.plot(t, s["net_pnl"], color=COLOR["net"], lw=2.0,
            label=f"net PnL vs holding (${m['net_pnl']:,.0f})")
    return _finish(fig, ax,
                   f"What the {result['params']['strategy']} position earned "
                   "and gave back", "USD")


def position_vs_hodl(result):
    """Position value against holding the same starting tokens.

    The gap between the lines IS the impermanent loss; where they meet,
    there is none.
    """
    m = result["metrics"]
    s = _decimate(result["series"], "value")
    fig, ax = _axes(figsize=(10, 5))
    ax.plot(s["timestamp"], s["hodl"], color=COLOR["hodl"], lw=LINE_W,
            label=f"just holding (${s['hodl'].iloc[-1]:,.2f})")
    ax.plot(s["timestamp"], s["value"], color=COLOR["value"], lw=LINE_W,
            label=f"position value (${m['final_value']:,.2f})")
    ax.fill_between(s["timestamp"], s["value"], s["hodl"],
                    color=COLOR["il"], alpha=0.13, lw=0,
                    label="impermanent loss")
    return _finish(fig, ax,
                   f"{result['params']['strategy'].capitalize()} position "
                   "vs holding the starting tokens", "USD")


def position_value_over_time(result):
    """Position value across the run, rebalances as a density wash.

    One faint vertical line per rebalance. Individually invisible, they
    darken where rebalances cluster -- which is the readable form of an
    event layer at this count. Scatter markers were the earlier attempt
    and 2,236 of them buried the line they annotated.
    """
    m = result["metrics"]
    full = result["series"]
    s = _decimate(full, "value")
    fig, ax = _axes(figsize=(10, 5))
    events = result["events"]
    if events:
        # Event rows are positions in the FULL series, so they are looked
        # up there -- every rebalance is drawn, only the line is thinned.
        at = full["timestamp"].iloc[[e["index"] for e in events]]
        ax.vlines(at, 0, 1, transform=ax.get_xaxis_transform(),
                  color=COLOR["rebalancing"], alpha=0.06, lw=0.6, zorder=0,
                  label=f"{len(events):,} rebalances")
    ax.plot(s["timestamp"], s["value"], color=COLOR["value"], lw=LINE_W,
            label="position value", zorder=2)
    ax.set_ylim(bottom=0)
    return _finish(
        fig, ax,
        f"{result['params']['strategy'].capitalize()} position value",
        "USD",
        subtitle=f"${s['value'].iloc[0]:,.2f} at the start, "
                 f"${m['final_value']:,.2f} at the end")


def fee_per_bin(total_bin_fees, bin_step, top=None):
    """Total fees each bin earned, against that bin's price.

    Shows where the price actually spent its time -- the shape any fixed
    range is betting on.
    """
    bins = np.array(sorted(total_bin_fees))
    fees = np.array([total_bin_fees[b] for b in bins])
    prices = _bin_edges_ui(bins, bin_step)

    fig, ax = _axes(figsize=(10, 4.5))
    width = np.diff(prices).min() if len(prices) > 1 else 1.0
    ax.bar(prices, fees, width=width, color=COLOR["fees"], alpha=0.9, lw=0)
    ax.set_xlabel("bin price (USD)", color=INK["muted"], fontsize=9)
    ax.set_title("Fees earned by the pool at each price",
                 fontsize=11, color=INK["secondary"], loc="left",
                 pad=TITLE_PAD)
    ax.set_ylabel("fees (USD)", color=INK["muted"], fontsize=9)
    ax.text(0.0, 1.01, _esc(f"{len(bins):,} bins touched, "
                            f"${fees.sum():,.0f} total"),
            transform=ax.transAxes, fontsize=9, color=INK["muted"],
            ha="left", va="bottom")
    fig.tight_layout()
    return fig


def bin_grid(df, bin_step, window_minutes=120, target_bins=7):
    """The bin grid itself: price crossing a handful of bin boundaries.

    A teaching chart rather than a result. It needs a window calm enough
    that individual bins are countable, so it picks the stretch whose
    price span is closest to `target_bins` bins wide -- on a volatile
    stretch a 0.04% grid is a solid block and shows nothing.
    """
    highs = df["high"].rolling(window_minutes).max()
    lows = df["low"].rolling(window_minutes).min()
    # Width of each window in bins, which is what "readable" is measured in.
    span_bins = (np.log(highs / lows) / np.log(1 + bin_step / 10_000))
    end = int((span_bins - target_bins).abs().idxmin())
    window = df.iloc[max(0, end - window_minutes + 1):end + 1]

    lo_bin = get_bin_id_from_price(ui_to_raw(window["low"].min()), bin_step)
    hi_bin = get_bin_id_from_price(ui_to_raw(window["high"].max()), bin_step)

    fig, ax = _axes(figsize=(10, 5))
    # Alternate shading so a bin reads as a band, not just a pair of lines.
    for i, b in enumerate(range(lo_bin, hi_bin + 1)):
        low_edge = raw_to_ui(get_price_from_bin_id(b, bin_step))
        high_edge = raw_to_ui(get_price_from_bin_id(b + 1, bin_step))
        ax.axhspan(low_edge, high_edge, color=COLOR["band"],
                   alpha=0.16 if i % 2 else 0.06, lw=0)
        ax.axhline(low_edge, color=INK["axis"], lw=0.8)
    ax.axhline(raw_to_ui(get_price_from_bin_id(hi_bin + 1, bin_step)),
               color=INK["axis"], lw=0.8)

    ax.plot(window["timestamp"], window["close"], color=COLOR["price"],
            lw=1.8, label="SOL price")
    width_pct = ((1 + bin_step / 10_000) - 1) * 100
    return _finish(
        fig, ax, "Price moving across the bin grid", "price (USD)",
        legend=False,
        subtitle=f"{hi_bin - lo_bin + 1} bins at step {bin_step}, each "
                 f"{width_pct:.2f}% of price wide "
                 f"({window_minutes} minutes)")


# ======================================================================
# Comparison charts (more than one run)
# ======================================================================

def cumulative_fees(results):
    """Cumulative fee income, one line per strategy."""
    fig, ax = _axes(figsize=(10, 5))
    for result in results:
        s = _decimate(result["series"], "cum_fees")
        name = _label(result)
        ax.plot(s["timestamp"], s["cum_fees"], color=COLOR[name], lw=LINE_W,
                label=f"{name} (${result['metrics']['total_fees']:,.2f})")
    days = results[0]["params"]["days"]
    return _finish(fig, ax,
                   f"Cumulative fees on "
                   f"${results[0]['params']['deposit']:,} over {days:.0f} days",
                   "cumulative fees (USD)")


def net_pnl_comparison(results):
    """Net PnL against holding, one line per strategy."""
    fig, ax = _axes(figsize=(10, 5))
    ax.axhline(0, color=INK["axis"], lw=0.8)
    for result in results:
        s = _decimate(result["series"], "net_pnl")
        name = _label(result)
        ax.plot(s["timestamp"], s["net_pnl"], color=COLOR[name], lw=LINE_W,
                label=f"{name} (${result['metrics']['net_pnl']:+,.2f})")
    days = results[0]["params"]["days"]
    return _finish(fig, ax,
                   f"Net PnL vs holding on "
                   f"${results[0]['params']['deposit']:,} over {days:.0f} days",
                   "net PnL (USD)")


# ======================================================================
# Verification
# ======================================================================

def check_position_vs_hodl_round_trip() -> None:
    """On a closed price loop the position and HODL lines must meet.

    The chart's whole claim is that the gap between its two lines is the
    impermanent loss. IL is zero when price returns to where it started,
    so on a round trip the lines have to close -- if they do not, the
    chart is drawing something other than IL.
    """
    import pandas as pd

    from backtest import run
    from inventory import active_bin, mid_price_ui
    from strategies import make_synthetic_df

    print("=" * 72)
    print("CHECK -- position_vs_hodl: the lines meet again on a round trip")
    print("=" * 72)
    a = active_bin(76.0)
    path = [a, a + 1, a + 2, a + 3, a + 2, a + 1, a]
    df = make_synthetic_df(path)
    df["timestamp"] = pd.date_range("2026-01-01", periods=len(df), freq="min")
    assert df["close"].iloc[-1] == mid_price_ui(a)

    result = run(df, strategy="passive")
    s = result["series"]
    gap_start = s["value"].iloc[0] - s["hodl"].iloc[0]
    gap_end = s["value"].iloc[-1] - s["hodl"].iloc[-1]
    print(f"  close path (active bin): {path}")
    print(f"  start: position {s['value'].iloc[0]:.6f} vs hodl "
          f"{s['hodl'].iloc[0]:.6f}  (gap {gap_start:+.2e})")
    print(f"  end:   position {s['value'].iloc[-1]:.6f} vs hodl "
          f"{s['hodl'].iloc[-1]:.6f}  (gap {gap_end:+.2e})")
    print(f"  widest gap mid-path: ${(s['value'] - s['hodl']).min():.6f}")

    assert abs(gap_start) < 1e-9
    assert abs(gap_end) < 1e-9, "IL must close to zero on a round trip"
    assert (s["value"] - s["hodl"]).min() < 0, (
        "the lines must actually separate in between, or the check is vacuous")
    fig = position_vs_hodl(result)
    assert fig is not None
    plt.close(fig)
    print("  lines meet at both ends and separate in between -- PASS")


if __name__ == "__main__":
    check_position_vs_hodl_round_trip()
