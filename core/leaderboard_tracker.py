"""
Compatibility wrapper for legacy leaderboard workflows.

Trader-identity copy-trading is intentionally removed. This module now exposes
market-level flow consensus derived from public tape + orderbook data.
"""
from __future__ import annotations

from argparse import Namespace
from typing import Dict, List

from ops.build_flow_alpha import build_signals


class KalshiLeaderboardTracker:
    """
    Legacy API shim: provides consensus picks without any named-trader data.
    """

    def __init__(self) -> None:
        self.mode = "public_market_flow"

    def get_leaderboard(self, period: str = "month") -> List[Dict]:
        return []

    def get_trader_positions(self, username: str) -> List[Dict]:
        return []

    def detect_new_positions(self, username: str) -> List[Dict]:
        return []

    def analyze_trader_edge(self, username: str, days: int = 30) -> Dict:
        return {
            "username": username,
            "period_days": days,
            "note": "Named-trader position tracking is not supported.",
        }

    def get_consensus_picks(self, min_traders: int = 3) -> List[Dict]:
        args = Namespace(
            env="prod",
            markets_limit=200,
            trade_limit=120,
            book_depth=5,
            top_k=20,
            min_market_volume=2500.0,
            min_trades=max(10, min_traders * 3),
            max_spread=0.08,
            min_confidence=0.6,
            source_tag="smart_money_flow_v1",
            alpha_out="data/alpha_signals.json",
            csv_out=None,
        )
        flow_signals = build_signals(args)

        consensus: List[Dict] = []
        for row in flow_signals:
            fair_yes = float(row["fair_yes_probability"])
            side = "yes" if fair_yes >= 0.5 else "no"
            consensus.append(
                {
                    "ticker": row["ticker"],
                    "side": side,
                    "confidence": float(row["confidence"]),
                    "flow_score": float(row["flow_score"]),
                    "avg_entry_price": float(row["mid_probability"]),
                    "trader_count": 0,
                    "traders": [],
                    "source": "public_market_flow",
                }
            )
        return consensus
