"""
board.py — write data/status.json and data/stats.json from the database.
dashboard.html (copied to docs/ by the workflow) reads status.json directly.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import db


def write_outputs(conn, market_config, current_pick: dict, out_dir: str = "data"):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stats = db.stats_for_market(conn, market_config.key)
    bankroll = db.get_bankroll(conn, market_config.key, starting=0.0)

    status = {
        "ok": True,
        "market": market_config.key,
        "slug": current_pick.get("slug"),
        "signal_side": current_pick.get("side", "NO_TRADE"),
        "confidence": current_pick.get("confidence", 0.0),
        "spot": current_pick.get("spot"),
        "tte": current_pick.get("tte"),
        "updated": _iso_now(),
        "bankroll": bankroll,
        **stats,
        "recent_trades": db.recent_trades(conn, market_config.key),
    }

    Path(out_dir, "status.json").write_text(json.dumps(status, indent=2))
    Path(out_dir, "stats.json").write_text(json.dumps(stats, indent=2))
    return status


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
