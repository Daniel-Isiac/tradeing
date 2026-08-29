"""Configuration loaded from environment variables (see .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# TradingView alerts hit /webhook/<WEBHOOK_SECRET> -- generate a long random
# value (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
# and put the same value in the webhook URL you paste into TradingView.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Maps the TradingView ticker (syminfo.ticker, e.g. "BTCUSD") to the ccxt
# unified symbol Kraken expects (e.g. "BTC/USD").
SYMBOL_MAP = {
    "BTCUSD": "BTC/USD",
    "ETHUSD": "ETH/USD",
}

# Master switch. False (default) = paper trading only, no real orders ever
# reach Kraken. Only set to true once you're confident in paper results.
LIVE_TRADING = _bool("LIVE_TRADING", False)

KRAKEN_API_KEY = os.getenv("KRAKEN_API_KEY", "")
KRAKEN_API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

# Starting balance for the paper-trading simulator (USD).
PAPER_STARTING_BALANCE = float(os.getenv("PAPER_STARTING_BALANCE", "1000"))

# Kraken Spot has no margin/short-selling in this bot -- "short" entry alerts
# are logged and skipped rather than acted on. Flip this only if you've set
# up a Kraken margin-enabled account and understand the added risk (margin
# calls, borrow costs, liquidation).
ALLOW_SHORTS = _bool("ALLOW_SHORTS", False)

# Sizing: one open position at a time, shared across every symbol, sized at
# this fraction of current account equity. 1.0 = 100% of the account per
# trade, matching the strategy's own single-slot (pyramiding=1) design --
# NOTE this is much higher risk than the 12%-of-capital sizing the strategy
# was actually backtested with; the backtest's drawdown/win-rate numbers
# don't directly transfer at 100% sizing.
POSITION_SIZE_FRACTION = float(os.getenv("POSITION_SIZE_FRACTION", "1.0"))

# ATR bracket, matching the Pine strategy's own defaults.
STOP_ATR_MULT = float(os.getenv("STOP_ATR_MULT", "1.5"))
TARGET_ATR_MULT = float(os.getenv("TARGET_ATR_MULT", "2.0"))
BREAKEVEN_ATR_MULT = float(os.getenv("BREAKEVEN_ATR_MULT", "1.0"))
USE_BREAKEVEN = _bool("USE_BREAKEVEN", True)

# The Pine strategy's timeframe is 1 minute; "12 bars" time-stop == 12 minutes.
BAR_MINUTES = float(os.getenv("BAR_MINUTES", "1"))
MAX_BARS_IN_TRADE = float(os.getenv("MAX_BARS_IN_TRADE", "12"))

# How often the monitor loop polls Kraken's live price for the open position.
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "5"))

STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")
TRADE_LOG_FILE = os.getenv("TRADE_LOG_FILE", "trade_log.csv")
