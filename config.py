"""All tunable parameters for the DLMM backtester in one place."""

# Which pool is being modelled. Nothing computes from this -- it is recorded
# with every saved run so a history of runs can say what they were runs OF.
POOL = "SOL/USDC"

# Which candle file every module loads. Both datasets are committed, so this
# works on a fresh clone either way; see the README for their ranges.
DATA_FILE = "data/sol_1m_1y.parquet"

BIN_STEP = 4  # basis points; a common step for SOL pools (each bin 0.04% apart)
POOL_SHARE = 0.08  # this pool captures 8% of total market volume
FEE_RATE = 0.0004  # 0.04% trading fee
# Fixed TVL per bin in USD, from the tracked pool rather than a guess: it held
# about $723k inside a +/-1% band, which at bin step 4 is 50 bins, so $14.46k
# per bin there. A 69-bin position reaches past that band into thinner
# liquidity, and interpolating the density out to 69 bins gives $13.44k.
BIN_TVL = 13_500
USER_DEPOSIT = 1_000  # total user deposit in USD 
POSITION_BINS = 69  # width (in bins) of every position; Meteora's default range
MAX_BINS = 69  # widest position the engine will build; wider is rejected outright
FEE_DISTRIBUTION = "weighted"  # "equal" or "weighted": how a candle's fee splits across its bins
REBALANCE_COST = 0.001  # 0.1% of the value traded at a rebalance (swap fee + slippage + gas stand-in)
