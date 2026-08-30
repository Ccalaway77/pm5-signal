"""
spot.py — spot price + kline history with a venue fallback chain.

I cannot make live network calls from the sandbox this was written in, so
these endpoint shapes are written from general knowledge of each exchange's
public API, NOT verified against a live response. The very first harvest
run is the real test.

Every failure is printed (not silently swallowed) so the Actions log shows
exactly what went wrong instead of just "no data." If Actions logs show one
of these failing, paste the printed error back and it's usually a one-line
fix — the failure mode is almost always "the JSON key name moved" or "this
endpoint wants a header I didn't send."
"""

from __future__ import annotations

from typing import Optional

import requests

TIMEOUT = 5

# Some exchanges' API gateways silently reject requests carrying the default
# "python-requests/x.x" user agent (looks like a bot/script) with a 403.
# A normal browser-like header avoids that — a common cause of "every
# request just fails with no obvious reason."
HEADERS = {"User-Agent": "Mozilla/5.0 (pm5-signal data collector)"}


def fetch_coinbase_price(symbol: str) -> float:
    r = requests.get(f"https://api.coinbase.com/v2/prices/{symbol}/spot", timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    return float(r.json()["data"]["amount"])


def fetch_kraken_price(symbol: str) -> float:
    r = requests.get(f"https://api.kraken.com/0/public/Ticker", params={"pair": symbol}, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    result = r.json()["result"]
    key = next(iter(result))
    return float(result[key]["c"][0])


def fetch_bybit_price(symbol: str) -> float:
    r = requests.get(
        "https://api.bybit.com/v5/market/tickers", params={"category": "spot", "symbol": symbol},
        timeout=TIMEOUT, headers=HEADERS,
    )
    r.raise_for_status()
    return float(r.json()["result"]["list"][0]["lastPrice"])


FETCHERS = {"coinbase": fetch_coinbase_price, "kraken": fetch_kraken_price, "bybit": fetch_bybit_price}


def get_spot_price(market_config) -> tuple[Optional[float], Optional[str]]:
    for ss in market_config.spot_symbols:
        fetch = FETCHERS.get(ss.venue)
        if fetch is None:
            continue
        try:
            price = fetch(ss.symbol)
            print(f"[spot] {market_config.key}: got price {price} from {ss.venue}")
            return price, ss.venue
        except Exception as e:
            print(f"[spot] {market_config.key}: {ss.venue} FAILED — {type(e).__name__}: {e}")
            continue
    print(f"[spot] {market_config.key}: ALL venues failed, returning None")
    return None, None


# ---------------------------------------------------------------------
# Kline (candle) history — this is what powers the signal. Fetches the
# last N minutes of 1-minute candles in a single call, so the engine has
# real momentum/volatility features from the very first run instead of
# needing weeks to build up its own tick history.
# ---------------------------------------------------------------------

def fetch_coinbase_klines(symbol: str, minutes: int) -> list[dict]:
    url = f"https://api.exchange.coinbase.com/products/{symbol}/candles"
    r = requests.get(url, params={"granularity": 60}, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    rows = r.json()  # each row: [time, low, high, open, close, volume]
    rows = sorted(rows, key=lambda row: row[0])[-minutes:]
    return [{"ts": row[0], "close": float(row[4]), "volume": float(row[5])} for row in rows]


def fetch_kraken_klines(symbol: str, minutes: int) -> list[dict]:
    r = requests.get(
        "https://api.kraken.com/0/public/OHLC", params={"pair": symbol, "interval": 1},
        timeout=TIMEOUT, headers=HEADERS,
    )
    r.raise_for_status()
    result = r.json()["result"]
    key = next(k for k in result if k != "last")
    rows = result[key][-minutes:]  # each row: [time, open, high, low, close, vwap, volume, count]
    return [{"ts": row[0], "close": float(row[4]), "volume": float(row[6])} for row in rows]


def fetch_bybit_klines(symbol: str, minutes: int) -> list[dict]:
    r = requests.get(
        "https://api.bybit.com/v5/market/kline",
        params={"category": "spot", "symbol": symbol, "interval": "1", "limit": minutes},
        timeout=TIMEOUT, headers=HEADERS,
    )
    r.raise_for_status()
    rows = r.json()["result"]["list"]  # each row: [start, open, high, low, close, volume, turnover]
    rows = sorted(rows, key=lambda row: int(row[0]))
    return [{"ts": int(row[0]), "close": float(row[4]), "volume": float(row[5])} for row in rows]


KLINE_FETCHERS = {
    "coinbase": fetch_coinbase_klines,
    "kraken": fetch_kraken_klines,
    "bybit": fetch_bybit_klines,
}


def get_recent_klines(market_config, minutes: int = 20) -> list[dict]:
    """Ascending-by-time list of {ts, close, volume} dicts, or [] if every venue fails."""
    for ss in market_config.spot_symbols:
        fetch = KLINE_FETCHERS.get(ss.venue)
        if fetch is None:
            continue
        try:
            klines = fetch(ss.symbol, minutes)
            if klines:
                print(f"[klines] {market_config.key}: got {len(klines)} bars from {ss.venue}")
                return klines
        except Exception as e:
            print(f"[klines] {market_config.key}: {ss.venue} FAILED — {type(e).__name__}: {e}")
            continue
    print(f"[klines] {market_config.key}: ALL venues failed, returning []")
    return []
