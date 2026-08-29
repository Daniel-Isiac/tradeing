"""Persistent bot state: current equity, the one open position (if any), and
a CSV trade log. JSON-file-backed so a restart doesn't lose an open position.
"""
import csv
import json
import os
import threading
from datetime import datetime, timezone

from bot import config

_lock = threading.Lock()


def _default_state() -> dict:
    return {
        "equity": config.PAPER_STARTING_BALANCE,
        "position": None,  # dict when open: see open_position()
    }


def load() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE) as f:
            return json.load(f)
    return _default_state()


def save(state: dict) -> None:
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_position(state: dict, *, symbol: str, side: str, qty: float, entry_price: float,
                   atr: float, stop_price: float, target_price: float, deadline_iso: str) -> None:
    with _lock:
        state["position"] = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": entry_price,
            "atr": atr,
            "stop_price": stop_price,
            "target_price": target_price,
            "breakeven_triggered": False,
            "opened_at": now_iso(),
            "deadline": deadline_iso,
        }
        save(state)


def clear_position(state: dict) -> None:
    with _lock:
        state["position"] = None
        save(state)


def log_trade(row: dict) -> None:
    file_exists = os.path.exists(config.TRADE_LOG_FILE)
    with open(config.TRADE_LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
