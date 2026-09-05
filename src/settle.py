"""
settle.py — resolve windows whose 5 minutes are up, pay out open trades,
and label the corresponding feature row for the learner.
"""

from __future__ import annotations

import time

import db
import risk
from online_learner import OnlineLearner


def settle_due(conn, market_config, cfg, spot_fetcher):
    """
    spot_fetcher: callable(market_config) -> (price, venue) — pass
    spot.get_spot_price. Kept as a parameter so tests can inject a fake.
    """
    due = db.due_unresolved_windows(conn, now=time.time())
    for w in due:
        if w["market_key"] != market_config.key:
            continue
        end_spot, _venue = spot_fetcher(market_config)
        if end_spot is None:
            continue  # try again next tick rather than resolving on bad data
        outcome = "UP" if end_spot > w["start_spot"] else "DOWN"
        db.resolve_window(conn, w["slug"], end_spot, outcome)

        label = 1 if outcome == "UP" else 0
        db.label_feat_rows_for_slug(conn, w["slug"], label)

        _settle_trades_for_slug(conn, market_config, cfg, w["slug"], outcome)
        _train_learner_for_slug(conn, market_config, cfg, w["slug"], label)


def _settle_trades_for_slug(conn, market_config, cfg, slug, outcome):
    for t in db.open_trades_for_slug(conn, slug):
        won = t["side"] == outcome
        pnl = risk.settle_pnl(t["fill_price"], t["stake"], t["fee"], won)
        db.settle_trade(conn, t["id"], pnl)


def _train_learner_for_slug(conn, market_config, cfg, slug, label):
    feat_row = conn.execute(
        "SELECT * FROM feat_rows WHERE slug=? ORDER BY id DESC LIMIT 1", (slug,)
    ).fetchone()
    if feat_row is None:
        return
    import json

    features = json.loads(feat_row["features_json"])
    learner = OnlineLearner(
        model_path=f"data/model_{market_config.key}.json",
        metrics_path="data/metrics.jsonl",
        min_rows_before_trusted=cfg["learner"]["min_rows_before_trusted"],
    )
    learner.observe(features, label, market_key=market_config.key)
