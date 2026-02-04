#!/usr/bin/env python3
"""
Deprecated name retained for compatibility.

Named-trader copy-trading is not supported. This command now emits public
market-flow signals.
"""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.build_flow_alpha import build_signals, write_outputs


def main() -> None:
    args = Namespace(
        env="prod",
        markets_limit=200,
        trade_limit=120,
        book_depth=5,
        top_k=10,
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
    print(
        "Named-trader copy-trading removed. "
        f"Saved {len(signals)} market-flow signals to {args.csv_out} and {args.alpha_out}."
    )


if __name__ == "__main__":
    main()
