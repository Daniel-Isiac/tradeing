"""Multi-ticker runner for the ORB prior-day-retest strategy.

Usage:
    python engine.py --data-dir ./data --out-dir ./results

Expects one CSV per ticker in --data-dir, named <TICKER>.csv, with columns
timestamp,open,high,low,close,volume (timestamp anything pandas can parse;
naive timestamps are assumed to already be in the exchange's local time).

Writes, into --out-dir:
    trades_<TICKER>.csv   - every individual trade for that ticker
    summary.csv           - one row per ticker with aggregate stats
    all_trades.csv         - every trade across every ticker, concatenated
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

from strategy_orb_prior_day_retest import ORBParams, Trade, run_orb_backtest


def trades_to_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=[
            "symbol", "side", "signal_time", "entry_time", "entry_price", "stop", "target",
            "qty", "exit_time", "exit_price", "exit_reason", "pnl", "r_multiple", "equity_after",
        ])
    return pd.DataFrame([t.__dict__ for t in trades])


def summarize(trades_df: pd.DataFrame, symbol: str, initial_capital: float) -> dict:
    n = len(trades_df)
    if n == 0:
        return {
            "symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": np.nan,
            "gross_profit": 0.0, "gross_loss": 0.0, "profit_factor": np.nan,
            "net_pnl": 0.0, "net_return_pct": 0.0, "avg_r": np.nan,
            "max_drawdown_pct": np.nan, "final_equity": initial_capital,
        }

    wins = trades_df[trades_df["pnl"] > 0]
    losses = trades_df[trades_df["pnl"] <= 0]
    gross_profit = wins["pnl"].sum()
    gross_loss = -losses["pnl"].sum()
    net_pnl = trades_df["pnl"].sum()

    equity_curve = initial_capital + trades_df["pnl"].cumsum()
    running_peak = equity_curve.cummax()
    drawdown_pct = (equity_curve - running_peak) / running_peak * 100.0
    max_dd = drawdown_pct.min()

    return {
        "symbol": symbol,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / n, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else np.nan,
        "net_pnl": round(net_pnl, 2),
        "net_return_pct": round(100.0 * net_pnl / initial_capital, 2),
        "avg_r": round(trades_df["r_multiple"].mean(), 3),
        "max_drawdown_pct": round(max_dd, 2),
        "final_equity": round(initial_capital + net_pnl, 2),
    }


def load_ticker_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing required columns {sorted(missing)}")
    return df


def run_all(data_dir: str, out_dir: str, params: ORBParams) -> pd.DataFrame:
    os.makedirs(out_dir, exist_ok=True)
    csv_paths = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not csv_paths:
        print(f"No CSV files found in {data_dir}", file=sys.stderr)
        return pd.DataFrame()

    summaries = []
    all_trades_frames = []

    for path in csv_paths:
        symbol = os.path.splitext(os.path.basename(path))[0]
        try:
            df = load_ticker_csv(path)
        except ValueError as exc:
            print(f"Skipping {symbol}: {exc}", file=sys.stderr)
            continue

        trades = run_orb_backtest(df, params, symbol)
        trades_df = trades_to_frame(trades)
        trades_df.to_csv(os.path.join(out_dir, f"trades_{symbol}.csv"), index=False)
        all_trades_frames.append(trades_df)

        summaries.append(summarize(trades_df, symbol, params.initial_capital))
        print(f"{symbol}: {len(trades)} trades, "
              f"win rate {summaries[-1]['win_rate_pct']}%, "
              f"profit factor {summaries[-1]['profit_factor']}, "
              f"net return {summaries[-1]['net_return_pct']}%")

    summary_df = pd.DataFrame(summaries).sort_values("profit_factor", ascending=False)
    summary_df.to_csv(os.path.join(out_dir, "summary.csv"), index=False)

    if all_trades_frames:
        pd.concat(all_trades_frames, ignore_index=True).to_csv(
            os.path.join(out_dir, "all_trades.csv"), index=False)

    return summary_df


def build_params_from_args(args: argparse.Namespace) -> ORBParams:
    return ORBParams(
        atr_len=args.atr_len,
        use_rth_levels=args.use_rth_levels,
        allow_longs=not args.no_longs,
        allow_shorts=not args.no_shorts,
        min_breakout_atr_mult=args.min_breakout_atr_mult,
        retest_tolerance_atr_mult=args.retest_tolerance_atr_mult,
        max_wait_bars=args.max_wait_bars,
        risk_percent_per_trade=args.risk_pct,
        stop_buffer_atr_mult=args.stop_buffer_atr_mult,
        reward_multiple=args.reward_multiple,
        use_session=not args.no_session,
        session=(args.session_start, args.session_end),
        initial_capital=args.initial_capital,
        commission_pct=args.commission_pct,
        slippage_ticks=args.slippage_ticks,
        tick_size=args.tick_size,
        exchange_tz=args.exchange_tz,
    )


def main():
    p = argparse.ArgumentParser(description="Run the ORB prior-day-retest strategy across all tickers in a data directory.")
    p.add_argument("--data-dir", default="data", help="Directory of <TICKER>.csv files (default: ./data)")
    p.add_argument("--out-dir", default="results", help="Directory to write results into (default: ./results)")
    p.add_argument("--atr-len", dest="atr_len", type=int, default=14)
    p.add_argument("--use-rth-levels", action="store_true", default=False)
    p.add_argument("--no-longs", action="store_true", default=False)
    p.add_argument("--no-shorts", action="store_true", default=False)
    p.add_argument("--min-breakout-atr-mult", type=float, default=0.1)
    p.add_argument("--retest-tolerance-atr-mult", type=float, default=0.15)
    p.add_argument("--max-wait-bars", type=int, default=40)
    p.add_argument("--risk-pct", type=float, default=1.0)
    p.add_argument("--stop-buffer-atr-mult", type=float, default=0.15)
    p.add_argument("--reward-multiple", type=float, default=2.0)
    p.add_argument("--no-session", action="store_true", default=False)
    p.add_argument("--session-start", default="09:30")
    p.add_argument("--session-end", default="11:00")
    p.add_argument("--initial-capital", type=float, default=10000.0)
    p.add_argument("--commission-pct", type=float, default=0.05)
    p.add_argument("--slippage-ticks", type=float, default=1.0)
    p.add_argument("--tick-size", type=float, default=0.01)
    p.add_argument("--exchange-tz", default="America/New_York")
    args = p.parse_args()

    params = build_params_from_args(args)
    summary_df = run_all(args.data_dir, args.out_dir, params)
    if not summary_df.empty:
        pd.set_option("display.width", 160)
        print("\n=== Summary (sorted by profit factor) ===")
        print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
