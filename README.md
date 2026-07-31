# DLMM Backtest

Backtesting engine for Meteora-style DLMM liquidity positions on SOL/USDC.
Fetches real 1-minute SOL candles, maps each candle to the DLMM bins its
price range touched, distributes trading fees to those bins, tracks the
token inventory of a position as price crosses its bins, and accounts the
result as fee income versus impermanent loss — comparing passive and
rebalancing strategies on the same data.

## Datasets

Two 1-minute SOL datasets, both from Jupiter's chart API. Which one every
module loads is set by `DATA_FILE` in `config.py`.

| dataset | range (UTC) | rows | size |
|---|---|---|---|
| `data/sol_1m_1y.parquet` | 2025-07-28 10:10 → 2026-07-28 10:09 | 525,420 | 25.8 MB — **the default** |
| `data/sol_1m_14d.csv` | 2026-07-05 14:41 → 2026-07-19 14:40 | 20,160 | 2.3 MB |

Both are committed, so a fresh clone (or a deployment) has data without a
fetch step. Switch between them by editing `DATA_FILE`; the results below
are from the year, and the 14-day set is small enough to iterate on
quickly (a full run takes about a second on it, against 96 s on the year).

The year ships as Parquet rather than CSV because at this size the format
carries its weight: 0.2 s to load versus ~15 s for the same rows as CSV, and
25.8 MB on disk versus 59.7 MB, with values and dtypes round-tripping
identically. The 57 MB intermediate CSV is gitignored.

To regenerate the year from scratch:

```
python fetch_data.py --days 365 --out data/sol_1m_1y.csv   # ~4 min, 106 API pages
python data_io.py data/sol_1m_1y.csv                       # → data/sol_1m_1y.parquet
```

`fetch_data.py` fetches a rolling window ending at run time, so a re-fetch
will not reproduce either committed file exactly.

### Data quality

Checked with `python verify_data.py data/sol_1m_1y.csv`:

- No duplicate timestamps and no zero/null-volume rows in either dataset.
- The 14-day set has no gaps. The 1-year set is missing **180 minutes across
  15 gaps** (0.03% of the year); the two largest are ~1 hour each, on
  2025-09-25 and 2026-01-23, and look like upstream outages. The engine
  iterates rows rather than assuming contiguous minutes, so these pass
  through as single long candles.
- **Zero candles** in the year have `open == high == low == close`, in any
  month. A padded or forward-filled range would be full of them, so the
  older portion is as genuinely observed as the recent portion — monthly
  price ranges and the daily-close path show real volatility throughout.

![SOL daily close over the year](data/sol_1y_daily.png)

## Results (1 year of 1-minute data, 2025-07-28 → 2026-07-28)

Produced from `data/sol_1m_1y.parquet`, the default dataset.

Both strategies put the same $1,000 into the same 69-bin range; the only
difference is whether the range is ever moved. Impermanent loss (IL) is
measured against holding the initial tokens untouched, so net PnL is what
LPing earned *over just holding*.

| strategy | fees | IL | costs | net PnL vs HODL | net APY | rebalances |
|---|---|---|---|---|---|---|
| passive (69 bins, $189.97–$195.29) | $401.63 | −$331.27 | — | **+$70.36** | 7.0% | 0 |
| rebalancing (69 bins) | $1,123.13 | −$603.67 | $107.38 | **+$412.08** | 41.2% | 2,236 |

![Net PnL by strategy](outputs/strategies.png)

SOL fell 62.1% over this year ($192.73 → $73.14), which is the single
fact driving every number below.

**The passive position is barely a baseline.** Its range was fixed on the
first candle at $189.97–$195.29. Price left it early and never came back,
so it earned on **2.6% of candles** (13,451 of 525,420) and collected 3.4%
of the pool's fees — essentially all of it in the first weeks. After that
it is a 100%-SOL bag riding the price down. It is here to answer "did
rebalancing help", and the answer is yes, decisively.

![Cumulative fees](outputs/cumulative_fees.png)

**Rebalancing beat holding, in absolute terms.** Following the price down
over 2,236 rebalances, it collected $1,123.13 of fees on a $996.96
deposit. Fees are withdrawn as earned, not compounded back in, so the
final wealth is fees plus whatever the position is still worth:

| | rebalancing | HODL |
|---|---|---|
| starting value | $996.96 | $996.96 |
| fees collected | $1,123.13 | — |
| ending position value | $0.02 | $711.07 |
| **total** | **$1,123.15** (+12.7%) | **$711.07** (−28.7%) |

**Read the APY column carefully — it is measured against HODL, not
against the deposit.** "+41.2%" means it beat holding by $412 over a year;
the absolute return on the money was +12.7%. Those are very different
claims, and only the second one is what a user gets.

This also explains the shape of the rebalancing line after early 2026: it
keeps drifting up while the position earns nothing. With the position at
roughly zero, net PnL is `fees − HODL`, so every further fall in SOL
*raises* it. That late rise is the baseline sinking, not the strategy
working.

**The position bleeds to nothing, and that caps the strategy.** Its value
goes $996.96 → $0.02, and fee income decays with it — **94% of the
$1,123.13 was earned in the first 90 days**:

| month end | 2025-07 | 2025-08 | 2025-09 | 2025-10 | 2025-11 | 2025-12 | 2026-01 | 2026-03 | 2026-07 |
|---|---|---|---|---|---|---|---|---|---|
| position value | $852.04 | $307.29 | $162.20 | $37.45 | $8.67 | $3.97 | $1.80 | $0.16 | $0.02 |
| fees that month | $110.78 | $604.08 | $240.21 | $118.65 | $32.71 | $10.07 | $5.23 | $0.13 | $0.01 |

This is not an accounting bug. On a closed price loop with `REBALANCE_COST`
set to zero, the passive position returns to exactly its starting value
(+0.000000%) while rebalancing loses **0.354% per rebalance** — the
buy-high/sell-low cost of recentring, about 3.5× larger than the 0.1%
explicit cost. Over 2,236 rebalances that compounds the position away.
Rebalancing converts impermanent loss into *permanent* loss, and the fee
income has to outrun it.

So the annualized figure is not repeatable: by month five the position is
worth $8 and earns nothing. Realizing anything like it again means
redepositing, which is a different (and untested) strategy.

**Cost sensitivity.** The verdict survives the cost assumption, though
the margin does not:

| `REBALANCE_COST` | 0% | 0.1% | 0.5% |
|---|---|---|---|
| net PnL vs HODL | +$556.43 | +$412.08 | +$53.67 |

![Fees, IL and net PnL](outputs/net_pnl.png)

The engine thus measures the two legs any range-management or hedging
approach is judged against: the fee income a position keeps, and the
price-exposure cost (IL) that must be managed away.

## Repository layout

| File | Purpose |
|---|---|
| `config.py` | All tunable parameters (bin step, pool share, fee rate, TVL, deposit, position width and the `MAX_BINS` ceiling, fee split mode, rebalance cost) |
| `bin_math.py` | Bin ↔ price math: `price(i) = (1 + bin_step/10000)^i` and its inverse |
| `fetch_data.py` | Fetches 1-minute SOL OHLCV from Jupiter's chart API (`--days`, `--out`) |
| `data_io.py` | Loads the configured dataset (CSV or Parquet); converts CSV → Parquet |
| `verify_data.py` | Data-quality check: monthly price ranges, flat-candle counts, daily-close chart |
| `candle_bins.py` | Maps each candle's [low, high] to the list of bins it touched |
| `fees.py` | Candle fee (`volume × pool_share × fee_rate`), split equally or weighted by price-range overlap |
| `position.py` | User position: deposit spread equally over a bin range; per-candle user fees |
| `inventory.py` | Token inventory per bin (USDC below the price, SOL above), flips as price crosses bins, position value |
| `pnl.py` | HODL baseline, impermanent loss, net PnL (fees + IL) |
| `strategies.py` | Rebalancing strategy: close-outside-range trigger, recenter, cost on the value traded |
| `run_backtest.py` | Runs both strategies end to end, prints the tables, writes charts to `outputs/` |
| `test_bin_math.py` | Tests for the bin math |
| `data/sol_1m_1y.parquet` | The exact dataset the results above were produced from (committed for reproducibility) |

Bin ids use the **raw on-chain price convention** (price in token base
units: SOL 9 decimals, USDC 6), so SOL at ~$76 sits near bin −6444 at
step 4 and ids match on-chain tooling. The data files store human (UI)
prices; `candle_bins.py` converts internally.

Positions are a fixed `POSITION_BINS`-wide range (69, Meteora's default),
and `make_position` rejects anything wider than `MAX_BINS`. Every position
in the engine — including the ones a rebalance opens — is built there, so
there is no path around the ceiling.

## How to run

Requires Python 3.12+ with `pandas`, `matplotlib`, `requests`, and `pyarrow`
(the last only for the Parquet path).

```
python run_backtest.py     # the full backtest (uses config.DATA_FILE)
python fetch_data.py       # optional: re-fetch a fresh 14-day window
python verify_data.py      # data-quality check on a fetched file
python test_bin_math.py    # bin math tests
python candle_bins.py      # bin-mapping tests + bin-grid chart
python fees.py             # fee distribution tests + fee-per-bin chart
python position.py         # position tests incl. the reference worked example
python inventory.py        # inventory checks on synthetic price paths
python pnl.py              # IL checks (round trip closes to 0; one-way matches the hand formula)
python strategies.py       # rebalancing checks (equivalence, value neutrality, trade direction)
```

## Verification

- Bin math: floor/boundary behavior asserted, including exact bin-edge prices.
- Data: 20,160 rows, no duplicate timestamps, no gaps, no zero-volume rows
  (14-day set; see Data quality above for the 1-year set).
- Fee conservation: per candle, distributed bin fees sum exactly to the candle
  fee (asserted for every candle in the dataset); per-bin totals sum to total
  pool fees.
- The passive position's cumulative curve is monotone and matches the analytic
  total — with equal shares across the range, its fees must come to exactly
  `share × (fees landing in range)` — and is flat exactly when price is
  outside the range.
- A position wider than `MAX_BINS` is rejected by `make_position`.
- Inventory: a price round trip restores every bin's exact tokens and value;
  value is constant when no bin is crossed and all bins hold USDC.
- IL: ≤ 0 at every candle (an LP never beats holding without fees); closes to
  exactly 0 on a round trip; a one-way move matches the closed-form
  `sol_sold × (final price − average sale price)`.
- Rebalancing: with no range exit the strategy equals the passive position
  exactly; with zero cost, value is continuous through every rebalance
  (the conversion is value-neutral by construction); a rise out of range
  buys SOL and a fall sells it, asserted on synthetic paths.

## Model assumptions

- Fees per candle: `volume_usd × POOL_SHARE × FEE_RATE`, split among the
  bins the candle touched — weighted by each bin's share of the candle's
  price range by default, or equally (`FEE_DISTRIBUTION`). On this
  dataset the two modes differ by cents: only candles straddling a
  range edge are affected.
- Every bin has fixed TVL (`BIN_TVL`); the user's share of a bin is
  `deposit_per_bin / BIN_TVL`.
- Inventory is driven by candle **closes** only: bins at or below the
  active bin hold USDC, bins above hold SOL, and a bin that changes side
  converts its whole holding at its own price. Intra-candle paths are
  ignored.
- IL is an opportunity cost versus holding the initial tokens, not a
  direct loss; it closes again if price returns to entry.
- Rebalancing triggers when a candle closes outside the range; the
  position reopens at the same width centered on the current bin, with
  `REBALANCE_COST` charged on the value that changes hands in the
  conversion (a stand-in for swap fees, slippage and gas).
