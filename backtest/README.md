# ORB prior-day-retest backtester

A Python port of `pine/ORB_PriorDayRetest.pine`, built to run across many
tickers at once instead of one symbol at a time in TradingView's Strategy
Tester. It reimplements the strategy's logic bar-by-bar (not a
vectorized/approximate version) including its exact order-fill timing, so
results should closely match what the Pine script does on the same data.

## The data problem (read this first)

You asked for 50 tickers x 365 days x 1-minute bars. That specific
combination is **not available for free from any source this was checked
against**:

- Yahoo Finance (yfinance): 1-minute bars are capped at the trailing ~30
  calendar days, period, regardless of how the requests are chunked. This is
  a server-side retention limit, not a rate limit you can work around.
- The `viaNexus` data connector available in this session: its intraday
  dataset only serves true 1-minute bars for `range=today` (i.e. live data,
  current day only). Any real lookback window is coarser - 10-minute bars
  for 5 days, or 30-minute bars for 1 month. Nothing gives 1-minute bars
  over a year.

Real 365-day 1-minute equity history is a paid-data-vendor thing (Polygon.io,
Databento, Algoseek, Tiingo's paid intraday tier) or something you pull from
a broker's own historical API if you have an account with deep history
entitlements (Interactive Brokers, TradeStation, etc).

**This engine itself doesn't care where the data comes from** - it just
needs one CSV per ticker with the columns below. So the practical path is:

1. Pick a real data source (see above) and get 1-minute OHLCV CSVs for your
   ~50 tickers, for whatever lookback that source actually gives you.
2. Put them in `backtest/data/<TICKER>.csv`.
3. Run `python engine.py`.

`download_data.py` is a ready-to-run downloader scoped to 30 days of
1-minute bars (Yahoo's actual real limit) for a specific 67-ticker list.
**It must be run on a machine with normal internet access** - this sandbox's
network egress is restricted to package registries by policy, so Yahoo
Finance is unreachable from here no matter what. On your own machine:

```bash
cd backtest
pip install -r requirements.txt
python download_data.py --out-dir data --days 30
```

This chunks each ticker's request into <=7-day windows (Yahoo's per-request
cap for 1-minute data) and writes `data/<TICKER>.csv` in the schema below.
One ticker in the list, `LILY34.SA` (a Brazilian BDR), is flagged in the
script as likely to come back empty or thin - Yahoo's intraday coverage for
foreign/BDR listings is generally poor, independent of this script.

Once you have the CSVs, send them back (or hand me the `data/` folder) and
the actual backtest runs with `python engine.py`.

## CSV format expected

One file per ticker, named `<TICKER>.csv`, columns:

```
timestamp,open,high,low,close,volume
```

`timestamp` can be anything pandas can parse. Naive (no timezone)
timestamps are assumed to already be in the exchange's local time
(`America/New_York` by default, see `--exchange-tz`).

## Quick start (synthetic demo, no real data needed)

Verifies the engine runs end-to-end using fake but plausible price data -
useful to confirm the setup works before pointing it at real data:

```bash
cd backtest
pip install -r requirements.txt
python make_synthetic_data.py --out-dir data --tickers AAA,BBB,CCC,DDD,EEE --days 20
python engine.py --data-dir data --out-dir results
```

Writes `results/summary.csv` (one row per ticker, sorted by profit factor),
`results/trades_<TICKER>.csv` (every trade for that ticker), and
`results/all_trades.csv` (everything combined).

## Real usage

```bash
python engine.py --data-dir data --out-dir results \
    --session-start 09:30 --session-end 11:00 \
    --risk-pct 1.0 --reward-multiple 2.0
```

All of the Pine script's inputs are exposed as CLI flags - run
`python engine.py --help` for the full list. Defaults match the Pine
script's own defaults exactly.

## Fidelity notes / known approximations

- **Order fill timing**: the Pine script does not set
  `process_orders_on_close`, so Pine's default applies - a decision made
  from bar N's close fills at bar N+1's open. This is replicated exactly
  (verify via `entry_time - signal_time` in the trades CSV, always one bar).
- **Same-bar stop/target resolution**: when a single bar's high/low range
  could have hit both the stop and the target, Pine's broker emulator
  assumes the intrabar path moves toward whichever of the bar's high/low is
  closer to its open first. This engine uses that same heuristic. It's a
  standard backtesting approximation, not verified against real tick data -
  real fills can differ.
- **ATR**: computed as Wilder's RMA via `ewm(alpha=1/length, adjust=False)`,
  which is mathematically the same recursion Pine's `ta.rma` uses. The only
  difference is the warmup/seed value, whose effect is negligible after a
  few multiples of the ATR length.
- **Commission**: percent-of-notional on both entry and exit, matching the
  Pine script's `commission_type=strategy.commission.percent,
  commission_value=0.05`.
- **Slippage**: a flat number of ticks (`--slippage-ticks`, `--tick-size`)
  applied unfavorably to the entry fill, approximating Pine's `slippage=1`
  parameter (which is also tick-based, but Pine doesn't disclose its exact
  internal application, so treat this as a reasonable approximation, not a
  verified match).
- **Position sizing**: risk-based, using the ticker's own compounding
  equity (starts at `--initial-capital`, grows/shrinks from that ticker's
  own realized P&L). Each ticker is backtested independently with its own
  capital pool, mirroring how TradingView's Strategy Tester evaluates one
  symbol at a time - this is not a shared-capital portfolio simulation
  across all 50 tickers at once.
