"""Map each candle to the DLMM bins its price range touched.

A 1-minute candle traded at every price between its low and its high at
some moment during that minute. So the bins it "touched" are every bin
from the one containing the low up to the one containing the high.

Price convention: RAW on-chain prices, so bin ids match on-chain tooling.
On-chain there are no decimal points: SOL amounts are lamports (10^9 per
SOL) and USDC amounts are base units (10^6 per USDC), so the price the
contract sees is
    raw = ui / 10^(BASE_DECIMALS - QUOTE_DECIMALS) = ui / 1000
SOL at ~$76 -> raw ~0.076 -> NEGATIVE bin ids (~ -1287 at step 20).
The CSV stays in UI prices; conversion happens inside this module.
"""

from bin_math import get_bin_id_from_price, get_bin_range, get_price_from_bin_id
from config import BIN_STEP

BASE_DECIMALS = 9  # SOL
QUOTE_DECIMALS = 6  # USDC


def ui_to_raw(price: float) -> float:
    """Human price (USD per SOL) -> on-chain price (USDC units per lamport)."""
    return price / 10 ** (BASE_DECIMALS - QUOTE_DECIMALS)


def raw_to_ui(price: float) -> float:
    """On-chain price -> human price, for display."""
    return price * 10 ** (BASE_DECIMALS - QUOTE_DECIMALS)


def map_candle_to_bins(low: float, high: float, bin_step: int) -> list[int]:
    """Return every bin id whose price range overlaps [low, high].

    low/high are UI prices as found in the CSV; they are converted to raw
    on-chain prices here so the resulting bin ids match on-chain tools.
    Bin ids are consecutive integers and each bin covers one contiguous
    slice of prices, so the touched bins are simply every id from the
    low's bin to the high's bin, inclusive.
    """
    low_bin = get_bin_id_from_price(ui_to_raw(low), bin_step)
    high_bin = get_bin_id_from_price(ui_to_raw(high), bin_step)
    return list(range(low_bin, high_bin + 1))


def add_bins_to_dataframe(df, bin_step):
    """Return a copy of df with two new columns:

    touched_bins — list of bin ids the candle's [low, high] overlapped
    num_bins     — how many bins that is
    """
    df = df.copy()
    df["touched_bins"] = [
        map_candle_to_bins(low, high, bin_step)
        for low, high in zip(df["low"], df["high"])
    ]
    df["num_bins"] = df["touched_bins"].map(len)
    return df


if __name__ == "__main__":
    # --- Edge case: low == high must touch exactly 1 bin -------------------
    bins = map_candle_to_bins(76.50, 76.50, BIN_STEP)
    print("low == high == 76.50      ->", bins)
    assert len(bins) == 1
    assert bins[0] < 0  # raw convention: SOL prices sit in negative bins

    # --- Boundary: high exactly ON a bin edge ------------------------------
    # Build an exact edge price from the formula itself, then use it as the
    # candle's high. The edge belongs to the bin ABOVE it, because bin i
    # covers [price(i), price(i+1)) — closed at its own edge, open at the top.
    edge_bin = get_bin_id_from_price(ui_to_raw(76.50), BIN_STEP) + 1
    edge_raw = get_price_from_bin_id(edge_bin, BIN_STEP)
    lo, hi = get_bin_range(edge_bin, BIN_STEP)
    print(f"\nedge price {edge_raw:.9f} raw ({raw_to_ui(edge_raw):.6f} UI) "
          f"= lower edge of bin {edge_bin} [{lo:.9f}, {hi:.9f})")

    bins = map_candle_to_bins(76.50, raw_to_ui(edge_raw), BIN_STEP)
    print("high exactly on that edge ->", bins)
    assert bins[-1] == edge_bin  # the edge price counts as inside the upper bin

    # A hair below the edge stays in the lower bin:
    bins_below = map_candle_to_bins(76.50, raw_to_ui(edge_raw) - 0.000001, BIN_STEP)
    print("high a hair below edge    ->", bins_below)
    assert bins_below[-1] == edge_bin - 1

    # --- Ordinary multi-bin candle ----------------------------------------
    bins = map_candle_to_bins(76.20, 76.65, BIN_STEP)
    print("\nlow 76.20, high 76.65     ->", bins)
    assert bins == list(range(bins[0], bins[-1] + 1))

    print("\nall pure-function tests passed")

    # ======================================================================
    # Demo on the real data (matplotlib only needed when run directly)
    # ======================================================================
    import matplotlib.pyplot as plt

    from data_io import load_candles

    df = load_candles()
    df = add_bins_to_dataframe(df, BIN_STEP)

    # --- Hand-check one real candle ---------------------------------------
    row = df[df["num_bins"] >= 3].iloc[0]
    print(f"\n--- hand-check: candle at {row['timestamp']} ---")
    print(f"low  = {row['low']:.6f} UI  ({ui_to_raw(row['low']):.9f} raw)")
    print(f"high = {row['high']:.6f} UI  ({ui_to_raw(row['high']):.9f} raw)")
    print(f"touched_bins = {row['touched_bins']}")
    for b in row["touched_bins"]:
        lo, hi = get_bin_range(b, BIN_STEP)
        print(f"  bin {b}: raw [{lo:.9f}, {hi:.9f})"
              f"  = UI [{raw_to_ui(lo):.6f}, {raw_to_ui(hi):.6f})")

    # --- Summary stats over all candles ------------------------------------
    n = df["num_bins"]
    print("\n--- num_bins over the whole CSV ---")
    print(f"min {n.min()} | median {n.median():.0f} | max {n.max()}")
    print(f"candles touching exactly 1 bin: {(n == 1).mean() * 100:.1f}%")

    # --- Chart: 2-hour window with the bin grid ----------------------------
    # Use the most volatile 2-hour stretch so several boundary crossings
    # are visible.
    span = df["high"].rolling(120).max() - df["low"].rolling(120).min()
    end = span.idxmax()
    window = df.iloc[end - 119 : end + 1]

    lo_bin = get_bin_id_from_price(ui_to_raw(window["low"].min()), BIN_STEP)
    hi_bin = get_bin_id_from_price(ui_to_raw(window["high"].max()), BIN_STEP)

    fig, ax = plt.subplots(figsize=(10, 5))
    for b in range(lo_bin, hi_bin + 2):  # +2: include top edge of highest bin
        ax.axhline(raw_to_ui(get_price_from_bin_id(b, BIN_STEP)),
                   color="#b3b3bd", lw=0.9)
    ax.plot(window["timestamp"], window["close"], color="#2563eb", lw=1.8)
    ax.set_title(
        f"SOL close price vs DLMM bin grid (step {BIN_STEP}, raw-price bins "
        f"{lo_bin}..{hi_bin}) — {window['timestamp'].iloc[0]:%Y-%m-%d %H:%M} to "
        f"{window['timestamp'].iloc[-1]:%H:%M} UTC",
        fontsize=11, color="#3f3f46",
    )
    ax.set_ylabel("price (USD)", color="#52525b")
    ax.tick_params(colors="#52525b", labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig("data/bin_grid_2h.png", dpi=150)
    print("\nchart saved to data/bin_grid_2h.png")
