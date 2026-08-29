"""Entrypoint: runs the webhook server and the position-monitor loop together.

Usage: python -m bot.main
"""
import logging
import os
import threading

import uvicorn

from bot import config
from bot.monitor import run_forever
from bot.webhook_server import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")


def main():
    if not config.WEBHOOK_SECRET:
        raise SystemExit("WEBHOOK_SECRET is not set -- copy .env.example to .env and fill it in")

    log.warning(
        "Starting in %s mode | position size = %.0f%% of equity per trade | shorts %s",
        "LIVE" if config.LIVE_TRADING else "PAPER",
        config.POSITION_SIZE_FRACTION * 100,
        "ENABLED" if config.ALLOW_SHORTS else "disabled (spot long-only)",
    )

    monitor_thread = threading.Thread(target=run_forever, daemon=True)
    monitor_thread.start()

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    main()
