"""Downloads 1-minute OHLCV bars for a list of tickers via yfinance and
writes one CSV per ticker into a data directory, in the schema
backtest/engine.py expects (timestamp,open,high,low,close,volume).

MUST BE RUN ON A MACHINE WITH NORMAL INTERNET ACCESS - this cannot run
inside a sandboxed Claude Code session whose network egress is restricted
to package registries only (Yahoo Finance is blocked there by policy).

Yahoo Finance's real limits, not worked around by this script because they
can't be:
  - 1-minute bars are retained for roughly the trailing 30 calendar days
    only, regardless of how far back you ask.
  - A single request for interval="1m" only covers up to about 7 days, so
    this script chunks the requested window into <=7-day pieces and
    concatenates them.

Usage:
    pip install -r requirements.txt
    python download_data.py --out-dir data --days 30

Ticker list defaults to the one you gave; override with --tickers or
--tickers-file (one symbol per line).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("Missing dependency: pip install -r requirements.txt", file=sys.stderr)
    raise

DEFAULT_TICKERS = [
    "BMNR", "CELH", "INTC", "ZS", "UPS", "ASML", "BABA", "DASH", "LUV", "AAL",
    "NFLX", "NET", "LMT", "BA", "DAL", "BKNG", "ABNB", "GM", "F", "GE",
    "WMT", "PEP", "KO", "CVX", "XOM", "OXY", "IBM", "ADBE", "MNDY", "NOW",
    "UNH", "LILY34.SA", "LRCX", "RGTI", "IONQ", "EBAY", "PYPL", "MARA", "MSTR", "COST",
    "MCD", "JPM", "UBER", "NKE", "MA", "V", "AMAT", "QCOM", "MU", "META",
    "AMD", "MSFT", "GOOG", "AMZN", "TSM", "NU", "ORCL", "AAPL", "TSLA", "NVDA",
    "PLTR", "VRT", "CRWD", "AVGO", "SOFI", "HIMS", "DELL",
]
# LILY34.SA is a B3 (Brazil) BDR - Yahoo's dash-form "LILY34-SA" doesn't
# resolve, the dot-form above does, but Yahoo's 1-minute intraday coverage
# for BDRs/foreign listings is frequently thin or empty. Expect this one
# to be the most likely to come back short or blank; it's not this
# script's fault if so, that's Yahoo's own data coverage for that listing.


def chunk_windows(days: int, max_span_days: int = 7):
    """Yields (start, end) datetime pairs covering the trailing `days`
    calendar days in chunks no larger than max_span_days, newest first is
    not required - yfinance doesn't care about order, concatenation sorts
    it out."""
    end = datetime.now(timezone.utc)
    start_overall = end - timedelta(days=days)
    cur_end = end
    while cur_end > start_overall:
        cur_start = max(start_overall, cur_end - timedelta(days=max_span_days))
        yield cur_start, cur_end
        cur_end = cur_start


def download_one(symbol: str, days: int, pause: float) -> pd.DataFrame:
    frames = []
    for start, end in chunk_windows(days):
        for attempt in range(3):
            try:
                df = yf.Ticker(symbol).history(
                    interval="1m", start=start, end=end,
                    prepost=False, auto_adjust=False,
                )
                break
            except Exception as exc:  # noqa: BLE001 - just retrying network flakiness
                if attempt == 2:
                    print(f"  {symbol}: failed window {start.date()}..{end.date()}: {exc}", file=sys.stderr)
                    df = pd.DataFrame()
                else:
                    time.sleep(pause * (attempt + 1))
                    continue
        if not df.empty:
            frames.append(df)
        time.sleep(pause)

    if not frames:
        return pd.DataFrame()

    full = pd.concat(frames)
    full = full[~full.index.duplicated(keep="first")].sort_index()
    full = full.reset_index()
    # yfinance names the index column "Datetime" for intraday data
    ts_col = "Datetime" if "Datetime" in full.columns else full.columns[0]
    out = pd.DataFrame({
        "timestamp": full[ts_col],
        "open": full["Open"],
        "high": full["High"],
        "low": full["Low"],
        "close": full["Close"],
        "volume": full["Volume"],
    })
    return out.dropna(subset=["open", "high", "low", "close"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data")
    p.add_argument("--days", type=int, default=30, help="Trailing calendar days to request (Yahoo retains ~30 for 1m data)")
    p.add_argument("--tickers", default=None, help="Comma-separated ticker list, overrides the default list")
    p.add_argument("--tickers-file", default=None, help="Path to a file with one ticker per line, overrides the default list")
    p.add_argument("--pause", type=float, default=1.0, help="Seconds to sleep between requests, be polite to Yahoo's rate limits")
    args = p.parse_args()

    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    elif args.tickers_file:
        with open(args.tickers_file) as f:
            tickers = [line.strip() for line in f if line.strip()]
    else:
        tickers = DEFAULT_TICKERS

    os.makedirs(args.out_dir, exist_ok=True)

    ok, empty = [], []
    for symbol in tickers:
        print(f"Downloading {symbol} ...")
        df = download_one(symbol, args.days, args.pause)
        # CSVs are saved with the ticker as given (dots kept, e.g. LILY34.SA.csv)
        # so engine.py's per-file symbol name matches what you'd expect.
        out_path = os.path.join(args.out_dir, f"{symbol}.csv")
        if df.empty:
            print(f"  no data returned for {symbol}", file=sys.stderr)
            empty.append(symbol)
            continue
        df.to_csv(out_path, index=False)
        print(f"  wrote {out_path} ({len(df)} rows, {df['timestamp'].min()} .. {df['timestamp'].max()})")
        ok.append(symbol)

    print("\n=== Summary ===")
    print(f"OK: {len(ok)}  Empty/no data: {len(empty)}")
    if empty:
        print("No data for:", ", ".join(empty))


if __name__ == "__main__":
    main()
