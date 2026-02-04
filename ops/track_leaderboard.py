"""
Legacy command name retained.

Tracks public market-flow consensus (not named-trader leaderboards).
"""
from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.build_flow_alpha import build_signals, write_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Track public market-flow consensus")
    parser.add_argument("--top", type=int, default=10, help="Number of signals to output")
    parser.add_argument("--min-confidence", type=float, default=0.6)
    args = parser.parse_args()

    flow_args = Namespace(
        env="prod",
        markets_limit=200,
        trade_limit=120,
        book_depth=5,
        top_k=args.top,
        min_market_volume=2500.0,
        min_trades=15,
        max_spread=0.08,
        min_confidence=args.min_confidence,
        source_tag="smart_money_flow_v1",
        alpha_out="data/alpha_signals.json",
        csv_out="data/flow_signals_latest.csv",
    )
    signals = build_signals(flow_args)
    if not signals:
        print("No consensus flow signals found.")
        return

    write_outputs(
        signals,
        alpha_out=Path(flow_args.alpha_out),
        csv_out=Path(flow_args.csv_out),
        source_tag=flow_args.source_tag,
    )

    print(f"Generated {len(signals)} market-flow signals:")
    for i, signal in enumerate(signals, 1):
        side = "YES" if float(signal["fair_yes_probability"]) >= 0.5 else "NO"
        print(
            f"{i}. {signal['ticker']} | side={side} | "
            f"conf={float(signal['confidence']) * 100:.0f}% | "
            f"edge={float(signal['edge_magnitude']) * 100:.2f}%"
        )


if __name__ == "__main__":
    main()
