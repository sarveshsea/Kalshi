#!/usr/bin/env python3
"""
Legacy entrypoint retained for compatibility.

Named-trader leaderboard copy logic has been removed. This monitor now runs
public market-flow detection and updates alpha_signals.json.
"""
from __future__ import annotations

from argparse import ArgumentParser, Namespace
from datetime import datetime
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.build_flow_alpha import build_signals, write_outputs


def monitor_flow(interval_minutes: int = 30, top_k: int = 20) -> None:
    cycle = 0
    while True:
        cycle += 1
        now = datetime.utcnow().strftime("%H:%M UTC")
        print(f"[{now}] Flow monitor cycle #{cycle}")
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
        if signals:
            write_outputs(
                signals,
                alpha_out=Path(args.alpha_out),
                csv_out=Path(args.csv_out),
                source_tag=args.source_tag,
            )
            print(f"Generated {len(signals)} market-flow signals")
        else:
            print("No eligible flow signals")
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    parser = ArgumentParser(description="Public market-flow monitor")
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()
    try:
        monitor_flow(interval_minutes=args.interval_minutes, top_k=args.top_k)
    except KeyboardInterrupt:
        print("\nStopped.")
