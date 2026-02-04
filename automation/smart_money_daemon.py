#!/usr/bin/env python3
"""
Smart-money daemon built on market-flow alpha + net-edge auto-trader.
"""
from __future__ import annotations

import argparse
from argparse import Namespace
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent.parent))

from automation.auto_trader import KalshiAutoTrader, TraderConfig
from ops.build_flow_alpha import build_signals, write_outputs


def run_once(args: argparse.Namespace) -> None:
    flow_args = Namespace(
        env=args.env,
        markets_limit=args.markets_limit,
        trade_limit=args.trade_limit,
        book_depth=args.book_depth,
        top_k=args.top_k,
        min_market_volume=args.min_market_volume,
        min_trades=args.min_trades,
        max_spread=args.max_spread,
        min_confidence=args.min_confidence,
        source_tag="smart_money_flow_v1",
        alpha_out=args.alpha_file,
        csv_out=args.csv_out,
    )
    signals = build_signals(flow_args)
    if not signals:
        print("No flow signals this cycle.")
        return

    write_outputs(
        signals,
        alpha_out=Path(flow_args.alpha_out),
        csv_out=Path(flow_args.csv_out) if flow_args.csv_out else None,
        source_tag=flow_args.source_tag,
    )
    print(f"Built {len(signals)} flow signals.")

    config = TraderConfig(
        env=args.env,
        enabled=not args.disabled,
        paper_mode=not args.live,
        paper_bankroll_usd=args.paper_bankroll,
        max_position_usd=args.max_position,
        min_position_usd=args.min_position,
        max_daily_trades=args.max_trades,
        max_total_exposure_usd=args.max_exposure,
        min_signal_confidence=args.min_confidence,
        min_edge=args.min_edge,
        min_net_edge=args.min_net_edge,
        max_spread=args.max_spread,
        min_volume=args.min_volume,
        fee_per_contract_prob=args.fee_per_contract,
        slippage_spread_factor=args.slippage_factor,
        kelly_fraction=args.kelly_fraction,
        take_profit_pct=args.take_profit,
        stop_loss_pct=args.stop_loss,
        max_holding_minutes=args.max_holding_minutes,
        scan_interval_seconds=args.interval_seconds,
        markets_limit=args.markets_limit,
        state_file=args.state_file,
        alpha_file=args.alpha_file,
    )
    trader = KalshiAutoTrader(config)
    trader.run_cycle()
    trader.print_performance_summary()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Market-flow smart-money daemon")
    parser.add_argument("--env", default="prod", choices=["demo", "prod"])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--run-once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)

    parser.add_argument("--markets-limit", type=int, default=200)
    parser.add_argument("--trade-limit", type=int, default=120)
    parser.add_argument("--book-depth", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-market-volume", type=float, default=2500.0)
    parser.add_argument("--min-trades", type=int, default=15)

    parser.add_argument("--paper-bankroll", type=float, default=250.0)
    parser.add_argument("--max-position", type=float, default=20.0)
    parser.add_argument("--min-position", type=float, default=5.0)
    parser.add_argument("--max-trades", type=int, default=12)
    parser.add_argument("--max-exposure", type=float, default=150.0)
    parser.add_argument("--min-confidence", type=float, default=0.6)
    parser.add_argument("--min-edge", type=float, default=0.03)
    parser.add_argument("--min-net-edge", type=float, default=0.015)
    parser.add_argument("--max-spread", type=float, default=0.08)
    parser.add_argument("--min-volume", type=float, default=500.0)
    parser.add_argument("--fee-per-contract", type=float, default=0.008)
    parser.add_argument("--slippage-factor", type=float, default=0.35)
    parser.add_argument("--kelly-fraction", type=float, default=0.25)
    parser.add_argument("--take-profit", type=float, default=0.20)
    parser.add_argument("--stop-loss", type=float, default=0.12)
    parser.add_argument("--max-holding-minutes", type=int, default=240)

    parser.add_argument("--alpha-file", default="data/alpha_signals.json")
    parser.add_argument("--csv-out", default="data/flow_signals_latest.csv")
    parser.add_argument("--state-file", default="data/auto_trader_state.json")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.run_once:
        run_once(args)
    else:
        try:
            while True:
                run_once(args)
                time.sleep(args.interval_seconds)
        except KeyboardInterrupt:
            print("\nStopped.")
