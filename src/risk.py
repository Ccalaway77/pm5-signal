"""
risk.py — position sizing and the "don't chase price" guardrails.

Binary-market payout math: buying `stake` dollars of a side at price `p`
gets you `stake / p` shares; a winning share pays $1.
    win:  pnl = stake/p * 1.0 - stake - fee
    lose: pnl = -stake - fee

Expected value per $1 staked, after the taker fee:
    EV = p_side / fill - 1 - fee_rate * fill * (1 - fill)

If EV is not clearly positive, skip. Confidence alone is not edge —
that is what bled the Sep-6 peak (buying 0.50-0.70 coins at ~50% hit).
Polymarket's ask is a VALUE filter here, never a model feature.
"""

from __future__ import annotations

from typing import Optional


def compute_fee(fill_price: float, stake: float, fee_rate: float) -> float:
    p = fill_price
    return fee_rate * p * (1 - p) * stake


def ev_per_stake(p_side: float, fill_price: float, fee_rate: float) -> float:
    """Expected PnL per $1 of stake if p_side is P(this side wins)."""
    if fill_price <= 0 or fill_price >= 1:
        return -1.0
    fee_frac = fee_rate * fill_price * (1.0 - fill_price)
    return (p_side / fill_price) - 1.0 - fee_frac


def decide_size(
    ask_price: float,
    confidence: float,
    bankroll: float,
    cfg: dict,
    p_side: Optional[float] = None,
) -> Optional[dict]:
    """Returns None if the trade should be skipped, else a sizing dict."""
    p_cfg = cfg["paper"]
    cutoff = (
        p_cfg["ask_price_cutoff_high_conf"]
        if confidence >= p_cfg["high_conf_threshold"]
        else p_cfg["ask_price_cutoff"]
    )
    if ask_price is None or ask_price > cutoff:
        return None

    fill_price = min(0.99, ask_price + p_cfg["slippage_ticks"] * p_cfg["tick_size"])

    min_ev = float(p_cfg.get("min_ev_per_stake", 0.0))
    if min_ev > 0 and p_side is not None:
        if ev_per_stake(float(p_side), fill_price, p_cfg["fee_rate"]) < min_ev:
            return None

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
