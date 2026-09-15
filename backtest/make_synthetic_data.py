"""Generates fake but plausible 1-minute OHLCV CSVs for a handful of tickers,
purely so the backtest engine can be exercised end-to-end without real market
data. Not a substitute for real data - the point is only to verify the
strategy/engine code runs and produces sane-looking output.

Usage: python make_synthetic_data.py --out-dir data --tickers AAA,BBB,CCC --days 10
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd


def make_ticker(symbol: str, days: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    start_price = rng.uniform(20, 300)

    rows = []
    price = start_price
    day_start = pd.Timestamp("2025-01-02 09:30")

    for d in range(days):
        # advance a running pointer one calendar day at a time, skipping
        # weekends - computing each day independently from a fixed offset
        # instead of advancing this pointer causes date collisions (multiple
        # simulated days landing on the same real calendar date)
        if d > 0:
            day_start += pd.Timedelta(days=1)
            while day_start.weekday() >= 5:
                day_start += pd.Timedelta(days=1)

        # small overnight drift + a mildly trending intraday walk, so
        # breakouts of the prior day's range actually happen sometimes
        drift = rng.normal(0, 0.004)
        price *= (1 + drift)

        n_bars = 390  # 09:30-16:00
        vol = rng.uniform(0.0008, 0.003)
        steps = rng.normal(0, vol, n_bars)
        # add a mild intraday trend component so ORB setups have something to catch
        trend = rng.normal(0, 0.0006)
        steps = steps + trend

        closes = price * np.cumprod(1 + steps)
        opens = np.empty(n_bars)
        opens[0] = price
        opens[1:] = closes[:-1]
        highs = np.maximum(opens, closes) * (1 + rng.uniform(0, 0.0015, n_bars))
        lows = np.minimum(opens, closes) * (1 - rng.uniform(0, 0.0015, n_bars))
        volumes = rng.integers(500, 20000, n_bars)

        timestamps = pd.date_range(day_start, periods=n_bars, freq="1min")
        for j in range(n_bars):
            rows.append((timestamps[j], opens[j], highs[j], lows[j], closes[j], volumes[j]))

        price = closes[-1]

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="data")
    p.add_argument("--tickers", default="AAA,BBB,CCC,DDD,EEE")
    p.add_argument("--days", type=int, default=15)
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    for i, sym in enumerate(tickers):
        df = make_ticker(sym, args.days, seed=1000 + i)
        out_path = os.path.join(args.out_dir, f"{sym}.csv")
        df.to_csv(out_path, index=False)
        print(f"wrote {out_path} ({len(df)} rows)")


if __name__ == "__main__":
    main()
