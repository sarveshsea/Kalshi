#!/usr/bin/env python3
"""
Deprecated leaderboard tracker shim.

This script now performs market-flow scans from public tape/orderbook data.
"""
from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.build_flow_alpha import build_signals, write_outputs


def run_scan(top_k: int) -> None:
    args = Namespace(
        env="prod",
        markets_limit=200,
        trade_limit=120,
        book_depth=5,
        top_k=top_k,
        min_market_volume=2500.0,
        min_trades=15,
        max_spread=0.08,
        min_confidence=0.6,
        source_tag="smart_money_flow_v1",
        alpha_out="data/alpha_signals.json",
        csv_out="data/flow_signals_latest.csv",
    )
    signals = build_signals(args)
    if not signals:
        print("No eligible market-flow signals.")
        return
    write_outputs(
        signals,
        alpha_out=Path(args.alpha_out),
        csv_out=Path(args.csv_out),
        source_tag=args.source_tag,
    )
    print(f"Saved {len(signals)} market-flow signals.")
    for idx, signal in enumerate(signals[:5], start=1):
        bias = "YES" if float(signal["fair_yes_probability"]) >= 0.5 else "NO"
        print(
            f"{idx}. {signal['ticker']} | bias={bias} | "
            f"conf={float(signal['confidence']) * 100:.0f}% | "
            f"edge={float(signal['edge_magnitude']) * 100:.2f}%"
        )


if __name__ == "__main__":
    parser = ArgumentParser(description="Market-flow tracker")
    parser.add_argument("--top-k", type=int, default=20)
    parsed = parser.parse_args()
    run_scan(top_k=parsed.top_k)
