"""
risk.py — position sizing and the "don't chase price" guardrails.

Binary-market payout math: buying `stake` dollars of a side at price `p`
gets you `stake / p` shares; a winning share pays $1.
    win:  pnl = stake/p * 1.0 - stake - fee
    lose: pnl = -stake - fee
"""

from __future__ import annotations

from typing import Optional


def compute_fee(fill_price: float, stake: float, fee_rate: float) -> float:
    p = fill_price
    return fee_rate * p * (1 - p) * stake


def decide_size(ask_price: float, confidence: float, bankroll: float, cfg: dict) -> Optional[dict]:
    """Returns None if the trade should be skipped, else a sizing dict."""
    p_cfg = cfg["paper"]
    cutoff = (
        p_cfg["ask_price_cutoff_high_conf"]
        if confidence >= p_cfg["high_conf_threshold"]
        else p_cfg["ask_price_cutoff"]
    )
    if ask_price is None or ask_price > cutoff:
        return None

    # Add slippage: assume you pay one tick worse than the quoted ask.
    fill_price = min(0.99, ask_price + p_cfg["slippage_ticks"] * p_cfg["tick_size"])

    # Scale stake linearly with confidence, clamped to [min_pct, max_pct].
    span = p_cfg["max_stake_pct"] - p_cfg["min_stake_pct"]
    pct = p_cfg["min_stake_pct"] + span * max(0.0, min(1.0, confidence))
    pct = max(p_cfg["min_stake_pct"], min(p_cfg["max_stake_pct"], pct))

    stake = bankroll * pct
    fee = compute_fee(fill_price, stake, p_cfg["fee_rate"])
    return {"fill_price": fill_price, "stake": stake, "fee": fee}


def settle_pnl(fill_price: float, stake: float, fee: float, won: bool) -> float:
    if won:
        shares = stake / fill_price
        return shares * 1.0 - stake - fee
    return -stake - fee
