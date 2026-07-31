"""All tunable parameters for the DLMM backtester in one place."""

# Which candle file every module loads. Both datasets are committed, so this
# works on a fresh clone either way; see the README for their ranges.
DATA_FILE = "data/sol_1m_1y.parquet"

BIN_STEP = 20  # basis points; a common step for SOL pools (each bin 0.2% apart)
POOL_SHARE = 0.02  # this pool captures 2% of total market volume
FEE_RATE = 0.001  # 0.1% trading fee 
BIN_TVL = 10_000  # fixed TVL per bin in USD 
USER_DEPOSIT = 1_000  # total user deposit in USD 
CONCENTRATED_BINS = 51  # width (in bins) of the concentrated position
FEE_DISTRIBUTION = "weighted"  # "equal" or "weighted": how a candle's fee splits across its bins
REBALANCE_COST = 0.001  # 0.1% of the value traded at a rebalance (swap fee + slippage + gas stand-in)
