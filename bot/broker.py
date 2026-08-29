"""Order execution: paper (simulated, default) vs live (real Kraken orders).

Both implement the same tiny interface so trading.py doesn't need to care
which one it's talking to: get_price, buy, sell.
"""
import logging

from bot import config
from bot.kraken_client import KrakenClient

log = logging.getLogger("broker")


class PaperBroker:
    """Simulates fills at the live market price with no real orders sent."""

    def __init__(self, kraken: KrakenClient):
        self._kraken = kraken

    def get_price(self, symbol: str) -> float:
        return self._kraken.get_price(symbol)

    def buy(self, symbol: str, usd_amount: float) -> tuple[float, float]:
        price = self.get_price(symbol)
        qty = usd_amount / price
        log.info("[PAPER] simulated buy %.6f %s @ %.2f (%.2f USD)", qty, symbol, price, usd_amount)
        return qty, price

    def sell(self, symbol: str, qty: float) -> float:
        price = self.get_price(symbol)
        log.info("[PAPER] simulated sell %.6f %s @ %.2f", qty, symbol, price)
        return price


class LiveBroker:
    """Places real market orders on Kraken. Only used when LIVE_TRADING=true."""

    def __init__(self, kraken: KrakenClient):
        self._kraken = kraken

    def get_price(self, symbol: str) -> float:
        return self._kraken.get_price(symbol)

    def buy(self, symbol: str, usd_amount: float) -> tuple[float, float]:
        order = self._kraken.market_buy(symbol, usd_amount)
        qty = float(order.get("filled") or order.get("amount"))
        price = float(order.get("average") or order.get("price") or self.get_price(symbol))
        log.warning("[LIVE] bought %.6f %s @ %.2f (%.2f USD)", qty, symbol, price, usd_amount)
        return qty, price

    def sell(self, symbol: str, qty: float) -> float:
        order = self._kraken.market_sell(symbol, qty)
        price = float(order.get("average") or order.get("price") or self.get_price(symbol))
        log.warning("[LIVE] sold %.6f %s @ %.2f", qty, symbol, price)
        return price


def get_broker() -> "PaperBroker | LiveBroker":
    kraken = KrakenClient()
    if config.LIVE_TRADING:
        return LiveBroker(kraken)
    return PaperBroker(kraken)
