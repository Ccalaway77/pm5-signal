"""
engine.py — turns kline history into features, then a side + confidence.

IMPORTANT: `heuristic_signal` below is a placeholder vol-normalized
momentum rule, not a validated strategy. Its only job is to generate SOME
signal so the system can start collecting labeled outcomes and training the
online learner. Do not read early win rates from this heuristic as "edge"
— that's exactly the mistake the original handoff's honest-fills fix was
correcting for. Treat everything before ~30 labeled rows / ~50 settled
trades as data collection, not performance.

These features are built ONLY from exchange spot/kline data (Coinbase /
Kraken / Bybit) — never from Polymarket's own contract price. Conditioning
the prediction on the market's own price would be circular (the market
price already reflects what everyone thinks will happen) and by the time
a strong Polymarket-price-based signal appeared, the contract would
already be too expensive to be worth buying. Polymarket's price is only
ever consulted once, at the very end, purely to decide whether the current
ask is cheap enough to fill (see risk.py / harvest.py) — it never reaches
the model.
"""

from __future__ import annotations

import statistics
from typing import Optional


def compute_features(klines: list[dict]) -> Optional[dict]:
    """
    klines: ascending-by-time list of {ts, close, volume} from spot.get_recent_klines.
    Returns None if there isn't enough history yet to compute anything meaningful.
    """
    closes = [k["close"] for k in klines]
    if len(closes) < 6:
        return None

    last = closes[-1]

    def n_bars_ago(n: int) -> Optional[float]:
        idx = -1 - n
        if -idx > len(closes):
            return None
        return closes[idx]

    p5 = n_bars_ago(5)
    p15 = n_bars_ago(15) or closes[0]  # fall back to oldest bar available if <15 min of history

    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    realized_vol = statistics.pstdev(returns) if len(returns) > 1 else 0.0

    momentum_5m = (last - p5) / p5 if p5 else 0.0
    momentum_15m = (last - p15) / p15 if p15 else 0.0
    # A rough Sharpe-like z-score: how big is the recent move relative to
    # how noisy this asset has been over the same window.
    z_5m = momentum_5m / realized_vol if realized_vol > 1e-9 else 0.0

    return {
        "momentum_5m": momentum_5m,
        "momentum_15m": momentum_15m,
        "realized_vol": realized_vol,
        "z_5m": z_5m,
    }


def heuristic_signal(feats: Optional[dict]) -> tuple[str, float]:
    if feats is None:
        return "NO_TRADE", 0.5
    z = feats["z_5m"]
    # Unvalidated squashing of the z-score into a confidence score — a
    # starting point for the heuristic, not a tuned model.
    conf = min(0.95, 0.5 + min(abs(z), 3.0) * 0.15)
    side = "UP" if z >= 0 else "DOWN"
    return side, conf


def blend(
    engine_side: str,
    engine_conf: float,
    learner_p_up: Optional[float],
    learner_trusted: bool,
    cfg: dict,
) -> tuple[str, float]:
    """
    Cold-start: use the heuristic so we still collect labeled data.

    Once trusted: soft-blend learner P(up) with the heuristic instead of a
    hard override, then cap confidence so ~1.0 SGD outputs cannot always
    max stake / raise the high-conf ask cutoff.
    """
    eng = cfg.get("engine", {})
    if learner_trusted and learner_p_up is not None:
        # Heuristic as a rough P(up): conf above 0.5 on UP, below on DOWN.
        if engine_side == "UP":
            heur_p_up = 0.5 + 0.5 * max(0.0, min(1.0, (engine_conf - 0.5) / 0.5))
        elif engine_side == "DOWN":
            heur_p_up = 0.5 - 0.5 * max(0.0, min(1.0, (engine_conf - 0.5) / 0.5))
        else:
            heur_p_up = 0.5
        w = float(eng.get("learner_blend_weight", 0.7))
        w = max(0.0, min(1.0, w))
        p_up = w * float(learner_p_up) + (1.0 - w) * heur_p_up
        side = "UP" if p_up >= 0.5 else "DOWN"
        conf = max(p_up, 1.0 - p_up)
        cap = float(eng.get("learner_conf_cap", 0.85))
        conf = min(conf, cap)
    else:
        side, conf = engine_side, engine_conf

    if conf < eng["lock_min_conf"]:
        return "NO_TRADE", conf
    return side, conf
