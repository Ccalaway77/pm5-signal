"""
poly.py — find the current 5-minute market and its best ask on Polymarket.

HONESTY NOTE: I could not make live calls to Gamma or CLOB from this
sandbox (no network access here), so the request shapes below are my best
understanding of Polymarket's public API, not verified against a live
response. Failures are printed so the Actions log shows exactly what came
back instead of failing silently — paste that back to me and it's usually
a quick fix.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

GAMMA_URL = "https://gamma-api.polymarket.com/markets"
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
TIMEOUT = 5
HEADERS = {"User-Agent": "Mozilla/5.0 (pm5-signal data collector)"}


def current_slot_start(now: Optional[float] = None) -> int:
    now = now or time.time()
    return int(now // 300) * 300  # 300s = 5-minute slot


def get_current_market(market_config, now: Optional[float] = None) -> Optional[dict]:
    """Returns the raw Gamma market dict for the current 5m slot, or None."""
    slot_start = current_slot_start(now)
    slug = market_config.slug_for(slot_start)
    try:
        r = requests.get(GAMMA_URL, params={"slug": slug}, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[poly] get_current_market({slug}) FAILED — {type(e).__name__}: {e}")
        return None
    if not data:
        print(f"[poly] get_current_market({slug}): Gamma returned no market for this slug")
        return None
    return data[0] if isinstance(data, list) else data


def get_best_ask(token_id: str) -> Optional[float]:
    try:
        r = requests.get(CLOB_BOOK_URL, params={"token_id": token_id}, timeout=TIMEOUT, headers=HEADERS)
        r.raise_for_status()
        book = r.json()
    except Exception as e:
        print(f"[poly] get_best_ask({token_id}) FAILED — {type(e).__name__}: {e}")
        return None
    asks = book.get("asks") or []
    if not asks:
        print(f"[poly] get_best_ask({token_id}): no asks in book")
        return None
    # CLOB order books are typically sorted worst-to-best or best-to-worst
    # depending on side — verify against a live response and adjust the
    # key below if the true best ask isn't the minimum price here.
    return float(min(asks, key=lambda a: float(a["price"]))["price"])
