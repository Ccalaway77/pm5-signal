"""
harvest.py — one full tick: settle due windows, then for every enabled
market, open a window if needed, get a signal, size it, paper-fill it.

Run every 5 minutes by .github/workflows/harvest.yml. Also runnable by hand:
    python src/harvest.py
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

import board
import db
import engine
import poly
import risk
import settle
import spot
from market_adapter import enabled_markets
from online_learner import OnlineLearner


def load_config(path: str = "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def run_market_tick(conn, market_config, cfg):
    slot_start = poly.current_slot_start()
    slug = market_config.slug_for(slot_start)
    window_end = slot_start + 300

    spot_now, _venue = spot.get_spot_price(market_config)
    if spot_now is None:
        return {"slug": slug, "side": "NO_TRADE", "confidence": 0.0, "error": "no_spot_price"}

    db.upsert_window(conn, slug, market_config.key, slot_start, window_end, spot_now)

    # Real short-term price history — this is what the signal is built
    # from, fetched fresh each tick from the exchange (never from
    # Polymarket's own price).
    lookback_min = cfg["engine"].get("kline_lookback_minutes", 20)
    klines = spot.get_recent_klines(market_config, minutes=lookback_min)
    features = engine.compute_features(klines)
    engine_side, engine_conf = engine.heuristic_signal(features)

    learner = OnlineLearner(
        model_path=f"data/model_{market_config.key}.json",
        metrics_path="data/metrics.jsonl",
        min_rows_before_trusted=cfg["learner"]["min_rows_before_trusted"],
    )
    p_up = learner.predict_proba(features) if features else None
    side, conf = engine.blend(engine_side, engine_conf, p_up, learner.is_trusted() and features is not None, cfg)

    tte = window_end - time.time()
    pick = {"slug": slug, "side": side, "confidence": conf, "spot": spot_now, "tte": tte}

    if side != "NO_TRADE" and tte > cfg["engine"]["paper_cutoff_sec"]:
        market_dict = poly.get_current_market(market_config)
        ask_price = None
        if market_dict:
            token_id = market_dict.get("clobTokenIds", [None])[0]  # VERIFY field name against real Gamma response
            if token_id:
                ask_price = poly.get_best_ask(token_id)

        if ask_price is not None:
            bankroll = db.get_bankroll(conn, market_config.key, cfg["paper"]["starting_bankroll"])
            sized = risk.decide_size(ask_price, conf, bankroll, cfg)
            if sized:
                db.insert_trade(
                    conn, slug, market_config.key, side,
                    sized["fill_price"], sized["stake"], sized["fee"],
                )
                db.adjust_bankroll(conn, market_config.key, -sized["stake"] - sized["fee"])

    if features is not None:
        db.insert_feat_row(conn, slug, market_config.key, features)
    return pick


def main():
    cfg = load_config()
    conn = db.get_conn()

    for market_config in enabled_markets():
        try:
            settle.settle_due(conn, market_config, cfg, spot.get_spot_price)
        except Exception:
            print(f"[settle:{market_config.key}] error:\n{traceback.format_exc()}")

    for market_config in enabled_markets():
        try:
            pick = run_market_tick(conn, market_config, cfg)
        except Exception:
            print(f"[tick:{market_config.key}] error:\n{traceback.format_exc()}")
            pick = {"slug": None, "side": "NO_TRADE", "confidence": 0.0, "error": "exception"}
        try:
            board.write_outputs(conn, market_config, pick)
        except Exception:
            print(f"[board:{market_config.key}] error:\n{traceback.format_exc()}")

    conn.close()


if __name__ == "__main__":
    main()
