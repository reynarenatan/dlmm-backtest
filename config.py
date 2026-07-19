"""All tunable parameters for the DLMM backtester in one place."""

BIN_STEP = 20  # basis points; a common step for SOL pools (each bin 0.2% apart)
POOL_SHARE = 0.02  # this pool captures 2% of total market volume
FEE_RATE = 0.001  # 0.1% trading fee (fixed for v1, per the task doc)
BIN_TVL = 10_000  # fixed TVL per bin in USD (used from Stage 5)
USER_DEPOSIT = 1_000  # total user deposit in USD (used from Stage 5)
CONCENTRATED_BINS = 51  # width (in bins) of the concentrated position, Stage 6
