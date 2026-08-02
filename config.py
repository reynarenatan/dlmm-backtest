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

# The same two measurements for every pool tracked in "DLMM Pool Tracking.xlsx"
# -- three live Meteora SOL/USDC pools, 16 observations each through July 2026.
# Derived and checked by scripts/pool_params.py; three significant figures
# because these are averages of noisy observations, not constants.
#
# POOL SHARE IS NOT THE SAME ACROSS BIN STEPS, and not nearly: the step 4 pool
# handles 28x the volume share of the step 20 pool. Trading is concentrated in
# the tightest grid. TVL per bin barely moves, since a wider bin holds
# proportionally more even where liquidity is thinner. Anything that varies the
# bin step has to vary the pool share with it or it is pricing a pool that does
# not exist.
#
# Bin step 4's entries are the settled values above rather than the sheet's
# current means (9.0% and $13,442). They were fixed before the sheet reached
# 16 observations, every published result is produced at them, and 8% is the
# conservative side of the difference.
TRACKED_POOLS = {
    4: {"pool_share": POOL_SHARE, "bin_tvl": BIN_TVL},
    10: {"pool_share": 0.0130, "bin_tvl": 12_300},
    20: {"pool_share": 0.00315, "bin_tvl": 14_100},
}
USER_DEPOSIT = 1_000  # total user deposit in USD 
POSITION_BINS = 69  # width (in bins) of every position; Meteora's default range
MAX_BINS = 69  # widest position the engine will build; wider is rejected outright
FEE_DISTRIBUTION = "weighted"  # "equal" or "weighted": how a candle's fee splits across its bins
REBALANCE_COST = 0.001  # 0.1% of the value traded at a rebalance (swap fee + slippage + gas stand-in)
