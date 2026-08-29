"""Thin wrapper around ccxt's Kraken client.

Public methods (get_price) work with no API keys and are used in both paper
and live mode, since paper mode simulates fills against real live prices.
Private methods (market_buy/market_sell/get_balance) only run when
config.LIVE_TRADING is true and require KRAKEN_API_KEY/KRAKEN_API_SECRET.
"""
import ccxt

from bot import config


class KrakenClient:
    def __init__(self):
        self._exchange = ccxt.kraken({
            "apiKey": config.KRAKEN_API_KEY,
            "secret": config.KRAKEN_API_SECRET,
            "enableRateLimit": True,
        })

    def get_price(self, symbol: str) -> float:
        """Last traded price for a ccxt unified symbol, e.g. 'BTC/USD'."""
        ticker = self._exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    def get_usd_balance(self) -> float:
        if not config.LIVE_TRADING:
            raise RuntimeError("get_usd_balance() requires LIVE_TRADING=true")
        balance = self._exchange.fetch_balance()
        return float(balance.get("USD", {}).get("free", 0.0))

    def market_buy(self, symbol: str, usd_amount: float) -> dict:
        """Spend usd_amount USD buying `symbol` at market. Returns the filled order."""
        if not config.LIVE_TRADING:
            raise RuntimeError("market_buy() requires LIVE_TRADING=true")
        price = self.get_price(symbol)
        amount = usd_amount / price
        return self._exchange.create_order(symbol, "market", "buy", amount)

    def market_sell(self, symbol: str, amount: float) -> dict:
        """Sell `amount` units of the base asset at market. Returns the filled order."""
        if not config.LIVE_TRADING:
            raise RuntimeError("market_sell() requires LIVE_TRADING=true")
        return self._exchange.create_order(symbol, "market", "sell", amount)
