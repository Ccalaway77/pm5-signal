import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db
import engine
import risk
from market_adapter import enabled_markets, load_markets


def test_markets_load(tmp_path):
    markets = load_markets(str(Path(__file__).parent.parent / "markets.yaml"))
    keys = {m.key for m in markets}
    assert "btc" in keys
    btc = next(m for m in markets if m.key == "btc")
    assert btc.enabled is True
    assert btc.slug_for(1700000000) == "btc-updown-5m-1700000000"


def test_only_btc_enabled_by_default():
    on = enabled_markets(str(Path(__file__).parent.parent / "markets.yaml"))
    assert [m.key for m in on] == ["btc"]


def test_decide_size_skips_expensive_ask():
    cfg = {"paper": {
        "min_stake_pct": 0.01, "max_stake_pct": 0.03,
        "ask_price_cutoff": 0.70, "ask_price_cutoff_high_conf": 0.80,
        "high_conf_threshold": 0.80, "slippage_ticks": 1, "tick_size": 0.01,
        "fee_rate": 0.07,
    }}
    assert risk.decide_size(0.85, confidence=0.6, bankroll=1000, cfg=cfg) is None
    result = risk.decide_size(0.75, confidence=0.9, bankroll=1000, cfg=cfg)
    assert result is not None
    assert result["fill_price"] > 0.75  # slippage applied


def test_decide_size_scales_with_confidence():
    cfg = {"paper": {
        "min_stake_pct": 0.01, "max_stake_pct": 0.03,
        "ask_price_cutoff": 0.70, "ask_price_cutoff_high_conf": 0.80,
        "high_conf_threshold": 0.80, "slippage_ticks": 1, "tick_size": 0.01,
        "fee_rate": 0.07,
    }}
    low = risk.decide_size(0.5, confidence=0.55, bankroll=1000, cfg=cfg)
    high = risk.decide_size(0.5, confidence=0.99, bankroll=1000, cfg=cfg)
    assert low["stake"] < high["stake"]


def test_settle_pnl_win_and_loss():
    win = risk.settle_pnl(fill_price=0.5, stake=100, fee=2, won=True)
    loss = risk.settle_pnl(fill_price=0.5, stake=100, fee=2, won=False)
    assert win == 100 / 0.5 * 1.0 - 100 - 2
    assert loss == -100 - 2


def test_engine_no_trade_below_confidence_floor():
    cfg = {"engine": {"lock_min_conf": 0.6}}
    side, conf = engine.blend("UP", 0.55, None, learner_trusted=False, cfg=cfg)
    assert side == "NO_TRADE"


def test_engine_trusts_learner_when_available():
    cfg = {"engine": {"lock_min_conf": 0.5}}
    side, conf = engine.blend("DOWN", 0.9, learner_p_up=0.8, learner_trusted=True, cfg=cfg)
    assert side == "UP"
    assert conf == 0.8


def test_compute_features_needs_minimum_history():
    short_klines = [{"ts": i, "close": 100 + i, "volume": 1} for i in range(3)]
    assert engine.compute_features(short_klines) is None


def test_compute_features_detects_uptrend():
    # steadily rising price, low noise -> positive momentum, positive z-score
    klines = [{"ts": i, "close": 100 + i * 0.5, "volume": 1} for i in range(20)]
    feats = engine.compute_features(klines)
    assert feats is not None
    assert feats["momentum_5m"] > 0
    assert feats["momentum_15m"] > 0
    assert feats["z_5m"] > 0


def test_compute_features_detects_downtrend():
    klines = [{"ts": i, "close": 100 - i * 0.5, "volume": 1} for i in range(20)]
    feats = engine.compute_features(klines)
    assert feats["momentum_5m"] < 0
    assert feats["z_5m"] < 0


def test_heuristic_signal_no_trade_without_features():
    side, conf = engine.heuristic_signal(None)
    assert side == "NO_TRADE"
    assert conf == 0.5


def test_heuristic_signal_matches_feature_direction():
    up_feats = {"z_5m": 1.5}
    down_feats = {"z_5m": -1.5}
    up_side, up_conf = engine.heuristic_signal(up_feats)
    down_side, down_conf = engine.heuristic_signal(down_feats)
    assert up_side == "UP"
    assert down_side == "DOWN"
    assert up_conf > 0.5 and down_conf > 0.5


def test_extract_first_token_id_handles_gamma_string_encoding():
    import harvest
    # Gamma actually returns this field as a JSON-encoded STRING, not a
    # real list — this is the exact shape that caused the token_id="[" bug.
    market = {"clobTokenIds": '["71234567890123", "88765432109876"]'}
    assert harvest._extract_first_token_id(market) == "71234567890123"


def test_extract_first_token_id_handles_missing_field():
    import harvest
    assert harvest._extract_first_token_id({}) is None


def test_has_any_trade_for_slug(tmp_path):
    conn = db.get_conn(str(tmp_path / "test2.db"))
    assert db.has_any_trade_for_slug(conn, "slug-x") is False
    db.insert_trade(conn, "slug-x", "btc", "UP", 0.5, 20, 0.5, ts=1)
    assert db.has_any_trade_for_slug(conn, "slug-x") is True
    # a settled trade should still count — the guard is "any trade ever", not "any open trade"
    trades = db.open_trades_for_slug(conn, "slug-x")
    db.settle_trade(conn, trades[0]["id"], pnl=5.0)
    assert db.has_any_trade_for_slug(conn, "slug-x") is True


def test_recent_trades_includes_fill_price_field(tmp_path):
    conn = db.get_conn(str(tmp_path / "test3.db"))
    db.insert_trade(conn, "slug-y", "btc", "DOWN", 0.61, 25, 0.4, ts=1)
    trades = db.recent_trades(conn, "btc")
    assert len(trades) == 1
    # dashboard.html reads t.fill_price — this locks that field name in place
    assert "fill_price" in trades[0]
    assert trades[0]["fill_price"] == 0.61


def test_compute_bankroll_matches_pnl_exactly(tmp_path):
    """
    Regression test for the double-counting bug: bankroll used to be
    adjusted once at trade-open (-stake-fee) AND once at settlement
    (+pnl, which already nets out stake and fee), silently charging every
    trade's stake twice. compute_bankroll derives the balance fresh from
    settled trade history instead, so it can never drift from starting + pnl.
    """
    conn = db.get_conn(str(tmp_path / "bankroll_test.db"))
    starting = 1000.0

    db.insert_trade(conn, "s1", "btc", "UP", 0.5, 30, 1.0, ts=1)
    t1 = db.open_trades_for_slug(conn, "s1")[0]
    pnl1 = risk.settle_pnl(t1["fill_price"], t1["stake"], t1["fee"], won=True)
    db.settle_trade(conn, t1["id"], pnl1)

    db.insert_trade(conn, "s2", "btc", "DOWN", 0.4, 20, 0.8, ts=2)
    t2 = db.open_trades_for_slug(conn, "s2")[0]
    pnl2 = risk.settle_pnl(t2["fill_price"], t2["stake"], t2["fee"], won=False)
    db.settle_trade(conn, t2["id"], pnl2)

    stats = db.stats_for_market(conn, "btc")
    bankroll = db.compute_bankroll(conn, "btc", starting)
    assert abs(bankroll - (starting + stats["pnl"])) < 1e-9
    assert abs(bankroll - (starting + pnl1 + pnl2)) < 1e-9


def test_db_roundtrip(tmp_path):
    conn = db.get_conn(str(tmp_path / "test.db"))
    db.upsert_window(conn, "slug-1", "btc", 0, 300, start_spot=100.0)
    trade_id = db.insert_trade(conn, "slug-1", "btc", "UP", 0.5, 20, 0.5, ts=1)
    db.resolve_window(conn, "slug-1", end_spot=110.0, outcome="UP")
    db.settle_trade(conn, trade_id, pnl=19.5)
    stats = db.stats_for_market(conn, "btc")
    assert stats["settle_count"] == 1
    assert stats["wins"] == 1
    assert stats["resolved_windows"] == 1
