"""
db.py — durable storage for pm5-signal.

Deliberately SQLite in a single file, not GitHub Actions cache/artifacts.
Cache entries get evicted and artifacts expire at 14 days — bad properties
for something that's supposed to get smarter the longer it runs. The
harvest.yml workflow commits data/pm5.db to a dedicated `data` branch after
every run, which is what actually makes this durable (see workflow file).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS windows (
    slug TEXT PRIMARY KEY,
    market_key TEXT NOT NULL,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    start_spot REAL,
    end_spot REAL,
    resolved INTEGER DEFAULT 0,
    outcome TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    market_key TEXT NOT NULL,
    side TEXT NOT NULL,
    fill_price REAL NOT NULL,
    stake REAL NOT NULL,
    fee REAL NOT NULL,
    ts REAL NOT NULL,
    settled INTEGER DEFAULT 0,
    pnl REAL
);

CREATE TABLE IF NOT EXISTS feat_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL,
    market_key TEXT NOT NULL,
    features_json TEXT NOT NULL,
    label INTEGER,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bankroll (
    market_key TEXT PRIMARY KEY,
    balance REAL NOT NULL
);
"""


def get_conn(path: str = "data/pm5.db") -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_bankroll(conn, market_key: str, starting: float) -> float:
    # NOTE: kept for backward compatibility but no longer used for the
    # live bankroll figure — see compute_bankroll() below.
    row = conn.execute("SELECT balance FROM bankroll WHERE market_key=?", (market_key,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO bankroll(market_key, balance) VALUES (?, ?)", (market_key, starting))
        conn.commit()
        return starting
    return row["balance"]


def adjust_bankroll(conn, market_key: str, delta: float):
    # NOTE: no longer called anywhere — see compute_bankroll() below for why.
    conn.execute(
        "UPDATE bankroll SET balance = balance + ? WHERE market_key=?", (delta, market_key)
    )
    conn.commit()


def compute_bankroll(conn, market_key: str, starting: float) -> float:
    """
    Bankroll is DERIVED fresh from settled trade history every time it's
    needed, instead of being tracked as separately mutated state.

    The old approach called adjust_bankroll() once when a trade opened
    (subtracting stake+fee) AND once when it settled (adding the full pnl
    — which risk.settle_pnl already computes net of stake and fee). That
    silently charged every trade's stake twice, draining the balance about
    twice as fast as reality and eventually toward zero.

    Deriving it fresh from SUM(pnl) of settled trades means there's no
    running counter left to drift or double-count — and it self-corrects
    any past corruption in the old `bankroll` table automatically, since
    that table is simply no longer read.
    """
    row = conn.execute(
        "SELECT SUM(pnl) s FROM trades WHERE market_key=? AND settled=1", (market_key,)
    ).fetchone()
    settled_pnl = row["s"] if row["s"] is not None else 0.0
    return starting + settled_pnl


def upsert_window(conn, slug: str, market_key: str, start_ts: float, end_ts: float, start_spot: Optional[float]):
    conn.execute(
        """INSERT INTO windows(slug, market_key, start_ts, end_ts, start_spot)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(slug) DO UPDATE SET start_spot=COALESCE(windows.start_spot, excluded.start_spot)""",
        (slug, market_key, start_ts, end_ts, start_spot),
    )
    conn.commit()


def due_unresolved_windows(conn, now: Optional[float] = None):
    now = now or time.time()
    return conn.execute(
        "SELECT * FROM windows WHERE resolved=0 AND end_ts <= ?", (now,)
    ).fetchall()


def resolve_window(conn, slug: str, end_spot: float, outcome: str):
    conn.execute(
        "UPDATE windows SET resolved=1, end_spot=?, outcome=? WHERE slug=?",
        (end_spot, outcome, slug),
    )
    conn.commit()


def insert_trade(conn, slug, market_key, side, fill_price, stake, fee, ts=None):
    ts = ts or time.time()
    cur = conn.execute(
        """INSERT INTO trades(slug, market_key, side, fill_price, stake, fee, ts, settled)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (slug, market_key, side, fill_price, stake, fee, ts),
    )
    conn.commit()
    return cur.lastrowid


def open_trades_for_slug(conn, slug: str):
    return conn.execute("SELECT * FROM trades WHERE slug=? AND settled=0", (slug,)).fetchall()


def has_any_trade_for_slug(conn, slug: str) -> bool:
    """
    Used to prevent placing a second trade on the same window. This matters
    because two independent triggers (GitHub's own schedule + the
    cron-job.org backup ping) can occasionally land close enough together
    that both process the same 5-minute slot — without this check, that
    would double the stake exposed to a single window's outcome.
    """
    row = conn.execute("SELECT 1 FROM trades WHERE slug=? LIMIT 1", (slug,)).fetchone()
    return row is not None


def settle_trade(conn, trade_id: int, pnl: float):
    conn.execute("UPDATE trades SET settled=1, pnl=? WHERE id=?", (pnl, trade_id))
    conn.commit()


def insert_feat_row(conn, slug, market_key, features: dict, ts=None):
    ts = ts or time.time()
    conn.execute(
        "INSERT INTO feat_rows(slug, market_key, features_json, ts) VALUES (?, ?, ?, ?)",
        (slug, market_key, json.dumps(features), ts),
    )
    conn.commit()


def label_feat_rows_for_slug(conn, slug: str, label: int):
    conn.execute("UPDATE feat_rows SET label=? WHERE slug=? AND label IS NULL", (label, slug))
    conn.commit()


def unlabeled_feat_row_for_slug(conn, slug: str):
    return conn.execute(
        "SELECT * FROM feat_rows WHERE slug=? AND label IS NULL ORDER BY id DESC LIMIT 1", (slug,)
    ).fetchone()


def stats_for_market(conn, market_key: str):
    settled = conn.execute(
        "SELECT * FROM trades WHERE market_key=? AND settled=1", (market_key,)
    ).fetchall()
    open_ = conn.execute(
        "SELECT COUNT(*) c FROM trades WHERE market_key=? AND settled=0", (market_key,)
    ).fetchone()["c"]
    wins = sum(1 for t in settled if t["pnl"] and t["pnl"] > 0)
    losses = sum(1 for t in settled if t["pnl"] is not None and t["pnl"] <= 0)
    pnl = sum(t["pnl"] for t in settled if t["pnl"] is not None)
    fees = sum(t["fee"] for t in settled)
    avg_fill = sum(t["fill_price"] for t in settled) / len(settled) if settled else None
    resolved_windows = conn.execute(
        "SELECT COUNT(*) c FROM windows WHERE market_key=? AND resolved=1", (market_key,)
    ).fetchone()["c"]
    labeled_feat = conn.execute(
        "SELECT COUNT(*) c FROM feat_rows WHERE market_key=? AND label IS NOT NULL", (market_key,)
    ).fetchone()["c"]
    return {
        "settle_count": len(settled),
        "open_count": open_,
        "wins": wins,
        "losses": losses,
        "hit_rate": (wins / len(settled)) if settled else None,
        "pnl": pnl,
        "fees": fees,
        "avg_fill": avg_fill,
        "resolved_windows": resolved_windows,
        "labeled_feat": labeled_feat,
    }


def recent_trades(conn, market_key: str, limit: int = 12):
    rows = conn.execute(
        "SELECT * FROM trades WHERE market_key=? ORDER BY ts DESC LIMIT ?", (market_key, limit)
    ).fetchall()
    return [dict(r) for r in rows]
