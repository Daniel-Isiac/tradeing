"""Python port of pine/ORB_PriorDayRetest.pine.

Faithful bar-by-bar reimplementation, including two details that are easy to
get wrong and change the results if missed:

1. The Pine strategy() call does NOT set process_orders_on_close, so Pine's
   default order-fill model applies: an order decided from bar i's
   close-of-bar calculation fills at bar i+1's OPEN, not at bar i's close.
   Stop/target levels are still computed from bar i's data (close/low/high),
   so a gap between bar i's close and bar i+1's open changes the *realized*
   risk/reward versus what was planned - exactly as it would in the real
   Pine strategy.

2. Pine's arm -> retest -> entry-decision logic is written as separate
   top-level `if` blocks, not mutually-exclusive branches, and Pine variables
   update immediately. That means a breakout that arms the setup on bar i can
   ALSO satisfy the retest condition on that very same bar i (if bar i's low
   dips back within tolerance of the level even though its close broke out
   cleanly), cascading all the way to a scheduled entry within one bar's
   evaluation. This port preserves that same-bar cascade instead of using
   elif/early-return shortcuts that would silently change behavior.

Same-bar stop/target resolution (when a single bar's range could have hit
both) follows Pine's documented broker-emulator heuristic: the assumed
intrabar path goes toward whichever of the bar's high/low is closer to its
open first. This is a standard backtesting approximation, not a guarantee of
the real fill order - flagged here so it isn't mistaken for verified data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ORBParams:
    atr_len: int = 14
    use_rth_levels: bool = False
    rth_session: tuple = ("09:30", "16:00")
    allow_longs: bool = True
    allow_shorts: bool = True
    min_breakout_atr_mult: float = 0.1
    retest_tolerance_atr_mult: float = 0.15
    max_wait_bars: int = 40
    risk_percent_per_trade: float = 1.0
    stop_buffer_atr_mult: float = 0.15
    reward_multiple: float = 2.0
    use_session: bool = True
    session: tuple = ("09:30", "11:00")
    initial_capital: float = 10000.0
    commission_pct: float = 0.05
    slippage_ticks: float = 1.0
    tick_size: float = 0.01
    exchange_tz: str = "America/New_York"


@dataclass
class Trade:
    symbol: str
    side: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    target: float
    qty: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    pnl: float
    r_multiple: float
    equity_after: float


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    return np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    tr = pd.Series(_true_range(high, low, close))
    # ewm(alpha=1/length, adjust=False) reproduces Wilder's RMA recursion;
    # the only difference from Pine's SMA-seeded rma is the warmup value,
    # whose influence decays to negligible within a few multiples of length.
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean().to_numpy()


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _in_window(minute_of_day: np.ndarray, start_min: int, end_min: int) -> np.ndarray:
    return (minute_of_day >= start_min) & (minute_of_day < end_min)


def run_orb_backtest(df: pd.DataFrame, params: ORBParams, symbol: str) -> list[Trade]:
    """df needs a 'timestamp' column (any pandas-parseable datetime, naive or
    tz-aware) plus open/high/low/close/volume, one row per bar, ascending.
    """
    df = df.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(df["timestamp"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(params.exchange_tz)
    else:
        ts = ts.dt.tz_convert(params.exchange_tz)

    o = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    n = len(df)
    if n == 0:
        return []

    atr = _wilder_atr(hi, lo, c, params.atr_len)

    minute_of_day = (ts.dt.hour * 60 + ts.dt.minute).to_numpy()
    date_id = (ts.dt.year * 10000 + ts.dt.month * 100 + ts.dt.day).to_numpy()

    sess_start, sess_end = _minutes(params.session[0]), _minutes(params.session[1])
    rth_start, rth_end = _minutes(params.rth_session[0]), _minutes(params.rth_session[1])

    in_session = _in_window(minute_of_day, sess_start, sess_end) if params.use_session else np.ones(n, dtype=bool)
    in_rth = _in_window(minute_of_day, rth_start, rth_end) if params.use_rth_levels else np.ones(n, dtype=bool)

    is_new_day = np.empty(n, dtype=bool)
    is_new_day[0] = True
    is_new_day[1:] = date_id[1:] != date_id[:-1]

    pdh = np.nan
    pdl = np.nan
    day_high = np.nan
    day_low = np.nan

    state = 0  # 0 idle, 1 armed long, 2 armed short
    bars_in_state = 0
    breakout_level = np.nan

    position = 0  # 0 flat, 1 long, -1 short
    entry_price = np.nan
    stop_level = np.nan
    target_level = np.nan
    qty = 0.0
    entry_time = None
    signal_time = None

    pending: Optional[dict] = None
    equity = params.initial_capital
    trades: list[Trade] = []

    slip = params.slippage_ticks * params.tick_size

    for i in range(n):
        if is_new_day[i]:
            pdh = day_high
            pdl = day_low
            day_high = hi[i]
            day_low = lo[i]
            state = 0
            bars_in_state = 0
        else:
            if in_rth[i]:
                day_high = hi[i] if np.isnan(day_high) else max(day_high, hi[i])
                day_low = lo[i] if np.isnan(day_low) else min(day_low, lo[i])

        # ---- fill a pending entry from the previous bar's decision (next-bar-open fill) ----
        if pending is not None:
            fill_price = o[i] + (slip if pending["side"] == "long" else -slip)
            position = 1 if pending["side"] == "long" else -1
            entry_price = fill_price
            stop_level = pending["stop"]
            target_level = pending["target"]
            qty = pending["qty"]
            entry_time = ts.iloc[i]
            signal_time = pending["signal_time"]
            pending = None

        # ---- manage an open position against this bar's range ----
        if position != 0:
            exit_price = None
            exit_reason = None
            if position == 1:
                if o[i] <= stop_level:
                    exit_price, exit_reason = o[i], "stop"
                elif o[i] >= target_level:
                    exit_price, exit_reason = o[i], "target"
                else:
                    hit_stop = lo[i] <= stop_level
                    hit_target = hi[i] >= target_level
                    if hit_stop and hit_target:
                        goes_up_first = (hi[i] - o[i]) < (o[i] - lo[i])
                        exit_price, exit_reason = (target_level, "target") if goes_up_first else (stop_level, "stop")
                    elif hit_stop:
                        exit_price, exit_reason = stop_level, "stop"
                    elif hit_target:
                        exit_price, exit_reason = target_level, "target"
            else:
                if o[i] >= stop_level:
                    exit_price, exit_reason = o[i], "stop"
                elif o[i] <= target_level:
                    exit_price, exit_reason = o[i], "target"
                else:
                    hit_stop = hi[i] >= stop_level
                    hit_target = lo[i] <= target_level
                    if hit_stop and hit_target:
                        goes_up_first = (hi[i] - o[i]) < (o[i] - lo[i])
                        exit_price, exit_reason = (stop_level, "stop") if goes_up_first else (target_level, "target")
                    elif hit_stop:
                        exit_price, exit_reason = stop_level, "stop"
                    elif hit_target:
                        exit_price, exit_reason = target_level, "target"

            if exit_price is None and i == n - 1:
                exit_price, exit_reason = c[i], "end_of_data"

            if exit_price is not None:
                gross = (exit_price - entry_price) * qty * position
                commission = (entry_price * qty + exit_price * qty) * (params.commission_pct / 100.0)
                pnl = gross - commission
                risk_amount = abs(entry_price - stop_level) * qty
                r_multiple = pnl / risk_amount if risk_amount > 0 else np.nan
                equity += pnl
                trades.append(Trade(
                    symbol=symbol, side="long" if position == 1 else "short",
                    signal_time=signal_time, entry_time=entry_time, entry_price=entry_price,
                    stop=stop_level, target=target_level, qty=qty,
                    exit_time=ts.iloc[i], exit_price=exit_price, exit_reason=exit_reason,
                    pnl=pnl, r_multiple=r_multiple, equity_after=equity,
                ))
                position = 0

        # ---- Block 1: idle -> armed (clean breakout of prior day high/low) ----
        if state == 0 and in_session[i] and i > 0 and not np.isnan(atr[i]):
            if (params.allow_longs and not np.isnan(pdh)
                    and c[i] > pdh and c[i - 1] <= pdh
                    and (c[i] - pdh) >= params.min_breakout_atr_mult * atr[i]):
                state = 1
                breakout_level = pdh
                bars_in_state = 0
            elif (params.allow_shorts and not np.isnan(pdl)
                    and c[i] < pdl and c[i - 1] >= pdl
                    and (pdl - c[i]) >= params.min_breakout_atr_mult * atr[i]):
                state = 2
                breakout_level = pdl
                bars_in_state = 0

        # ---- Block 2: armed long -> retest signal or cancel (can fire same bar as Block 1) ----
        long_retest_signal = False
        if state == 1:
            bars_in_state += 1
            if c[i] < breakout_level:
                state = 0
                bars_in_state = 0
            elif in_session[i] and not np.isnan(atr[i]) and lo[i] <= breakout_level + params.retest_tolerance_atr_mult * atr[i]:
                long_retest_signal = True
            elif bars_in_state >= params.max_wait_bars:
                state = 0
                bars_in_state = 0

        # ---- Block 3: armed short -> retest signal or cancel ----
        short_retest_signal = False
        if state == 2:
            bars_in_state += 1
            if c[i] > breakout_level:
                state = 0
                bars_in_state = 0
            elif in_session[i] and not np.isnan(atr[i]) and hi[i] >= breakout_level - params.retest_tolerance_atr_mult * atr[i]:
                short_retest_signal = True
            elif bars_in_state >= params.max_wait_bars:
                state = 0
                bars_in_state = 0

        # ---- Block 4/5: entry decision (schedules a fill for the NEXT bar's open) ----
        if long_retest_signal:
            if position == 0 and pending is None and in_session[i]:
                stop_candidate = lo[i] - params.stop_buffer_atr_mult * atr[i]
                risk_per_unit = c[i] - stop_candidate
                if risk_per_unit > 0:
                    trade_qty = (equity * params.risk_percent_per_trade / 100.0) / risk_per_unit
                    pending = {
                        "side": "long", "stop": stop_candidate,
                        "target": c[i] + params.reward_multiple * risk_per_unit,
                        "qty": trade_qty, "signal_time": ts.iloc[i],
                    }
            state = 0
            bars_in_state = 0

        if short_retest_signal:
            if position == 0 and pending is None and in_session[i]:
                stop_candidate = hi[i] + params.stop_buffer_atr_mult * atr[i]
                risk_per_unit = stop_candidate - c[i]
                if risk_per_unit > 0:
                    trade_qty = (equity * params.risk_percent_per_trade / 100.0) / risk_per_unit
                    pending = {
                        "side": "short", "stop": stop_candidate,
                        "target": c[i] - params.reward_multiple * risk_per_unit,
                        "qty": trade_qty, "signal_time": ts.iloc[i],
                    }
            state = 0
            bars_in_state = 0

    return trades
