"""Fetch historical 1-minute SOL candles from Jupiter's chart API.

Endpoint notes (probed 2026-07-19):
- `to` must be in unix MILLISECONDS; candle `time` in the response is in SECONDS.
- The API returns the `candles` most recent candles ENDING at `to`, oldest first.
- `volume` is already in USD (quote terms). Verified: avg ~$102k/minute
  extrapolates to ~$148M/day, ~12% of SOL's $1.19B global 24h volume (CMC).
  If it were SOL units it would imply ~$11B/day on-chain, 9x the global total.
"""

import csv
import os
import time
from datetime import datetime, timezone

import requests

TOKEN_MINT = "So11111111111111111111111111111111111111112"  # SOL
INTERVAL = "1_MINUTE"
DAYS_BACK = 14
OUTPUT_FILE = "data/sol_1m.csv"

API_URL = "https://datapi.jup.ag/v2/charts/" + TOKEN_MINT
CANDLES_PER_REQUEST = 1000  # max the API gives per call
SLEEP_SECONDS = 0.2  # politeness delay between requests

# The API returns 403 for the default "python-requests" User-Agent
# (Cloudflare bot filter); a browser-like one is accepted.
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_page(to_ms):
    """One API call: up to 1000 one-minute candles ending at to_ms, oldest first."""
    params = {
        "interval": INTERVAL,
        "to": to_ms,
        "candles": CANDLES_PER_REQUEST,
        "type": "price",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()["candles"]


def fetch_history(cutoff_s):
    """Paginate backwards from now until cutoff_s is covered.

    The cursor is `to_ms`. Each page gives the 1000 minutes before the cursor,
    so after each page we move the cursor to the oldest candle we received
    (minus 1 ms, so that candle is not returned again on the next page).
    We stop when the oldest candle is at or before the cutoff, or when the
    API has no more data to give.
    """
    all_candles = []
    to_ms = int(time.time()) * 1000

    while True:
        page = fetch_page(to_ms)
        if not page:  # API ran out of history before our cutoff
            break

        all_candles.extend(page)
        oldest_s = page[0]["time"]
        print(
            f"page {len(all_candles) // CANDLES_PER_REQUEST:>3}: "
            f"{len(page):>4} candles, oldest = "
            f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(oldest_s))} UTC"
        )

        if oldest_s <= cutoff_s:  # reached 14 days back: done
            break

        to_ms = oldest_s * 1000 - 1  # next page ends just before this one began
        time.sleep(SLEEP_SECONDS)

    return all_candles


def clean_candles(candles, cutoff_s):
    """Dedupe by timestamp, drop rows older than the cutoff, sort ascending.

    Returns (clean_list, n_duplicates_dropped).
    """
    by_time = {}
    duplicates = 0
    for c in candles:
        if c["time"] in by_time:
            duplicates += 1
        by_time[c["time"]] = c
    clean = [by_time[t] for t in sorted(by_time) if t >= cutoff_s]
    return clean, duplicates


def iso_utc(unix_s):
    return datetime.fromtimestamp(unix_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(candles):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume_usd"])
        for c in candles:
            writer.writerow(
                [iso_utc(c["time"]), c["open"], c["high"], c["low"], c["close"], c["volume"]]
            )


def print_summary(candles, duplicates):
    print("\n--- validation summary ---")
    print(f"1. total candles: {len(candles)}")
    print(f"2. range: {iso_utc(candles[0]['time'])} .. {iso_utc(candles[-1]['time'])}")
    print(f"3. duplicate timestamps dropped: {duplicates}")

    # A gap is any pair of consecutive rows more than 60s apart; the minutes
    # in between are missing candles.
    gaps = []
    for prev, cur in zip(candles, candles[1:]):
        step = cur["time"] - prev["time"]
        if step > 60:
            gaps.append((prev["time"], cur["time"], step // 60 - 1))
    missing = sum(g[2] for g in gaps)
    print(f"4. missing minutes: {missing} (in {len(gaps)} gaps)")
    for start, end, n in gaps[:10]:
        print(f"   gap: {iso_utc(start)} -> {iso_utc(end)} ({n} missing)")
    if len(gaps) > 10:
        print(f"   ... and {len(gaps) - 10} more gaps")

    bad_volume = sum(1 for c in candles if not c["volume"])  # zero or null
    print(f"5. rows with zero/null volume: {bad_volume}")


if __name__ == "__main__":
    cutoff_s = int(time.time()) - DAYS_BACK * 24 * 60 * 60
    raw = fetch_history(cutoff_s)
    print(f"\nfetched {len(raw)} candles total (before cleaning)")

    candles, duplicates = clean_candles(raw, cutoff_s)
    write_csv(candles)
    print(f"wrote {len(candles)} rows to {OUTPUT_FILE}")
    print_summary(candles, duplicates)
