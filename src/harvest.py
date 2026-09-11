"""
harvest.py — one full tick: settle due windows, then for every enabled
market, open a window if needed, get a signal, size it, paper-fill it.

Run every 5 minutes by .github/workflows/harvest.yml. Also runnable by hand:
    python src/harvest.py
"""

from __future__ import annotations

import sys
import time
import json
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
from online_learner import OnlineLearner, learner_from_cfg


def load_config(path: str = "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def _parse_gamma_list(raw):
    """Gamma often returns list fields as JSON-encoded strings."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(raw, list):
        return raw
    return None


def token_id_for_side(market_dict: dict, side: str) -> str | None:
    """
    Map signal side UP/DOWN to the matching CLOB token id using Gamma
    outcomes + clobTokenIds. Refuse (return None) if unmapped.
    """
    if side not in ("UP", "DOWN"):
        return None
    tokens = _parse_gamma_list(market_dict.get("clobTokenIds"))
    outcomes = _parse_gamma_list(market_dict.get("outcomes"))
    if not tokens or not outcomes or len(tokens) != len(outcomes):
        return None
    want = side.upper()
    for outcome, token_id in zip(outcomes, tokens):
        if str(outcome).strip().upper() == want:
            return str(token_id) if token_id is not None else None
    return None


def _extract_first_token_id(market_dict: dict) -> str | None:
    """Deprecated helper kept for older tests; prefer token_id_for_side."""
    tokens = _parse_gamma_list(market_dict.get("clobTokenIds"))
    if tokens:
        return str(tokens[0])
    return None


def run_market_tick(conn, market_config, cfg):
    slot_start = poly.current_slot_start()
    slug = market_config.slug_for(slot_start)
    window_end = slot_start + 300

    spot_now, _venue = spot.get_spot_price(market_config)
    if spot_now is None:
        return {
            "slug": slug, "side": "NO_TRADE", "confidence": 0.0, "error": "no_spot_price",
            "tape_action": "SKIP", "tape_reason": "no spot price", "tape_ask": None, "tape_fill": None,
        }

    db.upsert_window(conn, slug, market_config.key, slot_start, window_end, spot_now)

    lookback_min = cfg["engine"].get("kline_lookback_minutes", 20)
    klines = spot.get_recent_klines(market_config, minutes=lookback_min)
    features = engine.compute_features(klines)
    engine_side, engine_conf = engine.heuristic_signal(features)

    v1 = learner_from_cfg(market_config.key, cfg, suffix="")
    v2_suffix = cfg.get("learner", {}).get("v2_suffix", "_v2")
    v2 = learner_from_cfg(market_config.key, cfg, suffix=v2_suffix)
    if features is None:
        p_model = None
        trusted = False
        which = "none"
    elif v2.is_trusted():
        p_model = v2.predict_proba(features)
        trusted = True
        which = "v2"
    else:
        p_model = v1.predict_proba(features) if v1.is_trusted() else None
        trusted = v1.is_trusted()
        which = "v1" if trusted else "heur"
    p_up = p_model
    side, conf = engine.blend(engine_side, engine_conf, p_up, trusted and features is not None, cfg)
    p_up_blend = engine.blended_p_up(engine_side, engine_conf, p_up, trusted and features is not None, cfg)

    tte = window_end - time.time()
    pick = {
        "slug": slug, "side": side, "confidence": conf, "spot": spot_now, "tte": tte,
        "tape_action": "SKIP", "tape_reason": "waiting", "tape_ask": None, "tape_fill": None,
    }
    print(f"[harvest] {market_config.key} {slug}: signal={side} conf={conf:.3f} spot={spot_now} tte={tte:.0f}s "
          f"learner={which} trusted={trusted}")

    if side == "NO_TRADE":
        pick["tape_reason"] = "no trade — confidence below lock"
        print(f"[harvest] {market_config.key}: NO_TRADE this tick, skipping Polymarket lookup")
    elif tte <= cfg["engine"]["paper_cutoff_sec"]:
        pick["tape_reason"] = f"too late — {tte:.0f}s left"
        print(f"[harvest] {market_config.key}: only {tte:.0f}s left in window, too late to enter, skipping")
    else:
        market_dict = poly.get_current_market(market_config)
        ask_price = None
        if market_dict:
            token_id = token_id_for_side(market_dict, side)
            if token_id:
                ask_price = poly.get_best_ask(token_id)
            else:
                pick["tape_reason"] = f"no token mapped for {side}"
                print(f"[harvest] {market_config.key}: no token mapped for side={side} on {slug} — refusing trade")

        if ask_price is not None:
            pick["tape_ask"] = ask_price
            if db.has_any_trade_for_slug(conn, slug):
                pick["tape_action"] = "TAKE"
                pick["tape_reason"] = f"paper already filled this window — {side} ask {ask_price:.2f}"
                print(f"[harvest] {market_config.key}: already traded {slug} this window — skipping duplicate")
            else:
                bankroll = db.compute_bankroll(conn, market_config.key, cfg["paper"]["starting_bankroll"])
                p_side = p_up_blend if side == "UP" else (1.0 - p_up_blend)
                sized = risk.decide_size(ask_price, conf, bankroll, cfg, p_side=p_side)
                if sized:
                    db.insert_trade(
                        conn, slug, market_config.key, side,
                        sized["fill_price"], sized["stake"], sized["fee"],
                    )
                    pick["tape_action"] = "TAKE"
                    pick["tape_fill"] = sized["fill_price"]
                    pick["tape_reason"] = f"{side} @ {sized['fill_price']:.2f} (ask {ask_price:.2f})"
                    print(f"[harvest] {market_config.key}: TRADE placed — {side} @ {sized['fill_price']:.3f}, "
                          f"stake ${sized['stake']:.2f}")
                else:
                    pick["tape_reason"] = f"SKIP {side} — ask {ask_price:.2f} failed EV or cutoff"
                    print(f"[harvest] {market_config.key}: ask {ask_price} rejected by risk.decide_size (no edge or too expensive)")
        elif pick["tape_reason"] == "waiting":
            pick["tape_reason"] = "no ask on the book"

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
            pick = {
                "slug": None, "side": "NO_TRADE", "confidence": 0.0, "error": "exception",
                "tape_action": "SKIP", "tape_reason": "harvest error", "tape_ask": None, "tape_fill": None,
            }
        try:
            board.write_outputs(conn, market_config, pick, cfg)
        except Exception:
            print(f"[board:{market_config.key}] error:\n{traceback.format_exc()}")

    conn.close()


if __name__ == "__main__":
    main()
