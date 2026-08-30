"""
poly.py — find the current 5-minute market and its best ask on Polymarket.

HONESTY NOTE: I could not make live calls to Gamma or CLOB from this
sandbox (no network access here), so the request shapes below are my best
understanding of Polymarket's public API, not verified against a live
response. This file is the single most likely thing to need a fix after
your first real harvest run — if it errors, run the same request with curl
from your laptop, paste me the actual JSON you get back, and I'll correct
the field names in minutes. Everything else in this project (db, risk,
engine, learner) is independent of this file being perfect on day one.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
TIMEOUT = 5


def current_slot_start(now: Optional[float] = None) -> int:
    now = now or time.time()
    return int(now // 300) * 300  # 300s = 5-minute slot


def get_current_market(market_config, now: Optional[float] = None) -> Optional[dict]:
    """Returns the raw Gamma market dict for the current 5m slot, or None."""
    slot_start = current_slot_start(now)
    slug = market_config.slug_for(slot_start)
    r = requests.get(GAMMA_URL, params={"slug": slug}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return data[0] if isinstance(data, list) else data


def get_best_ask(token_id: str) -> Optional[float]:
    r = requests.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=TIMEOUT)
    r.raise_for_status()
    book = r.json()
    asks = book.get("asks") or []
    if not asks:
        return None
    # CLOB order books are typically sorted worst-to-best or best-to-worst
    # depending on side — verify against a live response and adjust the
    # min()/max()/index below if the first element isn't the best ask.
    return float(min(asks, key=lambda a: float(a["price"]))["price"])
