"""Loading candle files, and converting them between CSV and Parquet.

Every module reads its candles through `load_candles()` so the dataset in use
is decided in one place (config.DATA_FILE) rather than by six hardcoded paths.

Parquet matters at the 1-year size. Measured on the 525k-row file: CSV takes
~15 s to load, Parquet 0.2 s warm and ~1.5 s cold, and the file is 25.8 MB
against 59.7 MB. The types are stored in the file, so nothing has to be
re-parsed out of text on every run. Values and dtypes round-trip identically.

Convert a fetched CSV with:  python data_io.py data/sol_1m_1y.csv
"""

import os
import sys

import pandas as pd

from config import DATA_FILE


def load_candles(path=None):
    """Read a candle file into a DataFrame with a real datetime column.

    Dispatches on the file extension, so callers do not care which format
    the configured dataset happens to be stored in.
    """
    path = path or DATA_FILE
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    return pd.read_csv(path, parse_dates=["timestamp"])


def csv_to_parquet(csv_path, parquet_path=None):
    """Write a CSV candle file out as Parquet; returns the path written."""
    parquet_path = parquet_path or csv_path.replace(".csv", ".parquet")
    df = pd.read_csv(csv_path, parse_dates=["timestamp"])
    df.to_parquet(parquet_path, index=False)
    return parquet_path


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/sol_1m_1y.csv"
    out = csv_to_parquet(csv_path)
    csv_mb = os.path.getsize(csv_path) / 1e6
    parquet_mb = os.path.getsize(out) / 1e6
    print(f"{csv_path}  {csv_mb:.1f} MB")
    print(f"{out}  {parquet_mb:.1f} MB  ({csv_mb / parquet_mb:.1f}x smaller)")
