"""Core trading logic: turns a TradingView entry alert into a sized order,
then manages the resulting position's ATR stop/target/breakeven/time-stop
bracket against live prices. Long-only (see config.ALLOW_SHORTS) since this
runs against Kraken Spot, which can't short.

Only one position is open at a time, shared across every symbol -- if BTCUSD
and ETHUSD both signal, whichever gets here first takes the (up to) full
account; the other is skipped until it's flat again. This matches the Pine
strategy's own single-slot (pyramiding=1) design.
"""
import logging
from datetime import datetime, timedelta, timezone

from bot import config, state
from bot.broker import get_broker

log = logging.getLogger("trading")

_broker = get_broker()


def _equity(current_state: dict) -> float:
    return current_state["equity"]


def handle_entry_signal(payload: dict) -> dict:
    """payload: {"event": "entry", "side": "long"|"short", "symbol": "BTCUSD",
    "price": float, "atr": float, "time": str}. Returns a status dict describing
    what happened (for the webhook response / logs).
    """
    side = payload.get("side")
    ticker = payload.get("symbol")
    signal_price = float(payload.get("price"))
    atr = float(payload.get("atr"))

    symbol = config.SYMBOL_MAP.get(ticker)
    if symbol is None:
        msg = f"unknown symbol '{ticker}', not in SYMBOL_MAP -- ignoring"
        log.warning(msg)
        return {"status": "ignored", "reason": msg}

    if side == "short" and not config.ALLOW_SHORTS:
        msg = f"short signal on {ticker} ignored -- Kraken Spot can't short (ALLOW_SHORTS=false)"
        log.info(msg)
        return {"status": "ignored", "reason": msg}

    if side == "short" and config.ALLOW_SHORTS:
        # Shorting spot requires Kraken margin orders, not implemented here.
        msg = "ALLOW_SHORTS=true but margin order execution isn't implemented -- ignoring short"
        log.error(msg)
        return {"status": "ignored", "reason": msg}

    current_state = state.load()
    if current_state.get("position") is not None:
        msg = f"long signal on {ticker} ignored -- already in a position ({current_state['position']['symbol']})"
        log.info(msg)
        return {"status": "ignored", "reason": msg}

    equity = _equity(current_state)
    usd_amount = equity * config.POSITION_SIZE_FRACTION
    if usd_amount <= 0:
        msg = "usd_amount <= 0, refusing to trade"
        log.error(msg)
        return {"status": "error", "reason": msg}

    qty, fill_price = _broker.buy(symbol, usd_amount)

    stop_price = fill_price - atr * config.STOP_ATR_MULT
    target_price = fill_price + atr * config.TARGET_ATR_MULT
    deadline = datetime.now(timezone.utc) + timedelta(
        minutes=config.BAR_MINUTES * config.MAX_BARS_IN_TRADE
    )

    state.open_position(
        current_state,
        symbol=symbol,
        side="long",
        qty=qty,
        entry_price=fill_price,
        atr=atr,
        stop_price=stop_price,
        target_price=target_price,
        deadline_iso=deadline.isoformat(),
    )
    log.info(
        "OPENED long %.6f %s @ %.2f | stop %.2f target %.2f deadline %s",
        qty, symbol, fill_price, stop_price, target_price, deadline.isoformat(),
    )
    return {"status": "opened", "symbol": symbol, "qty": qty, "entry_price": fill_price,
            "stop_price": stop_price, "target_price": target_price}


def check_open_position() -> dict | None:
    """Called periodically by the monitor loop. Checks the open position (if
    any) against its stop/target/breakeven/time-stop and closes it if
    triggered. Returns a status dict if something happened, else None.
    """
    current_state = state.load()
    position = current_state.get("position")
    if position is None:
        return None

    symbol = position["symbol"]
    price = _broker.get_price(symbol)
    atr = position["atr"]

    # Breakeven: once price has moved favorably by BREAKEVEN_ATR_MULT x ATR,
    # move the stop up to the entry price (locks in a scratch, not a loss).
    if (
        config.USE_BREAKEVEN
        and not position["breakeven_triggered"]
        and price >= position["entry_price"] + atr * config.BREAKEVEN_ATR_MULT
    ):
        position["breakeven_triggered"] = True
        position["stop_price"] = position["entry_price"]
        state.save(current_state)
        log.info("Breakeven triggered on %s, stop moved to %.2f", symbol, position["stop_price"])

    exit_reason = None
    if price <= position["stop_price"]:
        exit_reason = "stop"
    elif price >= position["target_price"]:
        exit_reason = "target"
    elif datetime.now(timezone.utc) >= datetime.fromisoformat(position["deadline"]):
        exit_reason = "time_stop"

    if exit_reason is None:
        return None

    fill_price = _broker.sell(symbol, position["qty"])
    pnl = (fill_price - position["entry_price"]) * position["qty"]
    current_state["equity"] += pnl
    state.clear_position(current_state)

    state.log_trade({
        "symbol": symbol,
        "side": position["side"],
        "qty": position["qty"],
        "entry_price": position["entry_price"],
        "exit_price": fill_price,
        "exit_reason": exit_reason,
        "pnl": round(pnl, 2),
        "equity_after": round(current_state["equity"], 2),
        "opened_at": position["opened_at"],
        "closed_at": state.now_iso(),
    })
    log.info(
        "CLOSED %s %.6f %s @ %.2f (%s) | pnl %.2f | equity %.2f",
        position["side"], position["qty"], symbol, fill_price, exit_reason, pnl, current_state["equity"],
    )
    return {"status": "closed", "symbol": symbol, "exit_reason": exit_reason, "pnl": pnl}
