"""
market_adapter.py — config-driven definitions for each 5-minute market
pm5-signal tracks. Adding a new asset means editing markets.yaml, not code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass(frozen=True)
class SpotSymbol:
    venue: str
    symbol: str


@dataclass(frozen=True)
class MarketConfig:
    key: str
    label: str
    enabled: bool
    slug_prefix: str
    spot_symbols: List[SpotSymbol]
    settle_rule: str = "start_vs_end_spot"

    def slug_for(self, unix_start_of_5m_slot: int) -> str:
        return f"{self.slug_prefix}{unix_start_of_5m_slot}"


def load_markets(path: str | Path = "markets.yaml") -> List[MarketConfig]:
    raw = yaml.safe_load(Path(path).read_text())
    out = []
    for m in raw.get("markets", []):
        out.append(
            MarketConfig(
                key=m["key"],
                label=m["label"],
                enabled=bool(m.get("enabled", False)),
                slug_prefix=m["slug_prefix"],
                spot_symbols=[SpotSymbol(**s) for s in m["spot_symbols"]],
                settle_rule=m.get("settle_rule", "start_vs_end_spot"),
            )
        )
    return out


def enabled_markets(path: str | Path = "markets.yaml") -> List[MarketConfig]:
    return [m for m in load_markets(path) if m.enabled]


if __name__ == "__main__":
    for m in load_markets():
        status = "ENABLED" if m.enabled else "disabled"
        print(f"[{status}] {m.key:>4} — {m.label} — {m.slug_prefix}")
