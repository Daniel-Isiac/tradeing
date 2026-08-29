"""Background loop that polls the open position (if any) against its
stop/target/breakeven/time-stop bracket. Runs continuously alongside the
webhook server -- this is what actually manages exits, since TradingView
alerts only tell us about entries.
"""
import logging
import time

from bot import config, trading

log = logging.getLogger("monitor")


def run_forever():
    log.info("Monitor loop starting (poll every %.0fs)", config.POLL_INTERVAL_SECONDS)
    while True:
        try:
            trading.check_open_position()
        except Exception:
            log.exception("Error while checking open position")
        time.sleep(config.POLL_INTERVAL_SECONDS)
