#!/usr/bin/env python3
"""
Deterministic replay harness for captured /markets/trades snapshots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from automation.auto_trader import KalshiAutoTrader, TraderConfig
from core.trading import AlphaSignal, MarketQuote, compute_performance_metrics
from ops.build_flow_alpha import compute_trade_features, orderbook_imbalance, score_market


class SnapshotReplayTrader(KalshiAutoTrader):
    def __init__(self, config: TraderConfig):
        self.current_markets: List[Dict[str, Any]] = []
        super().__init__(config)

    def _print_startup_banner(self) -> None:
        print("Replay trader initialized.")

    def _submit_order(self, action: str, ticker: str, side: str, count: int):
        return True, f"replay-{action}-{ticker}-{count}"

    def _fetch_quotes(self):
        quotes: List[MarketQuote] = []
        for market in self.current_markets:
            quote = MarketQuote.from_market(market)
            if quote:
                quotes.append(quote)
        return quotes


def load_snapshots(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Snapshot file not found: {path}")
    snapshots: List[Dict[str, Any]] = []
    if path.suffix == ".jsonl":
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            snapshots.append(json.loads(line))
    else:
        payload = json.loads(path.read_text())
        if isinstance(payload, list):
            snapshots = payload
        else:
            raise SystemExit("Snapshot JSON must be a list for non-jsonl files.")
    if not snapshots:
        raise SystemExit("No snapshots found.")
    return snapshots


def build_snapshot_signals(snapshot: Dict[str, Any], min_confidence: float) -> Dict[str, AlphaSignal]:
    trades_by_ticker = snapshot.get("trades", {})
    books_by_ticker = snapshot.get("orderbooks", {})
    signals: Dict[str, AlphaSignal] = {}

    for market in snapshot.get("markets", []):
        quote = MarketQuote.from_market(market)
        if not quote:
            continue
        ticker = quote.ticker
        trades = trades_by_ticker.get(ticker, [])
        if not trades:
            continue
        features = compute_trade_features(trades)
        if features["trade_count"] <= 0:
            continue
        imbalance = orderbook_imbalance(books_by_ticker.get(ticker), depth=5)
        scored = score_market(quote, features, imbalance)
        confidence = float(scored["confidence"])
        if confidence < min_confidence:
            continue
        signals[ticker] = AlphaSignal(
            fair_yes_probability=float(scored["fair_yes_probability"]),
            confidence=confidence,
            source="replay_flow_v1",
        )
    return signals


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay backtest from trades snapshots")
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--state-out", default="data/replay_state.json")
    parser.add_argument("--paper-bankroll", type=float, default=250.0)
    parser.add_argument("--max-position", type=float, default=20.0)
    parser.add_argument("--min-position", type=float, default=5.0)
    parser.add_argument("--max-trades", type=int, default=100000)
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshots = load_snapshots(Path(args.snapshot_file))

    config = TraderConfig(
        env="prod",
        enabled=True,
        paper_mode=True,
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
        scan_interval_seconds=0,
        markets_limit=500,
        state_file=args.state_out,
        alpha_file="data/alpha_signals.json",
    )
    trader = SnapshotReplayTrader(config)

    for idx, snapshot in enumerate(snapshots, start=1):
        trader.current_markets = list(snapshot.get("markets", []))
        signals = build_snapshot_signals(snapshot, min_confidence=args.min_confidence)
        if signals:
            trader.check_exits(signals)
            candidates = trader._scan_candidates(signals)
            if candidates:
                trader._open_position(candidates[0])
        trader.save_state()
        if idx % 25 == 0:
            print(f"Replayed {idx}/{len(snapshots)} snapshots...")

    metrics = compute_performance_metrics(trader.closed_positions)
    print("Replay complete")
    print(f"Snapshots: {len(snapshots)}")
    print(f"Trades: {int(metrics['trades'])}")
    print(f"Win rate: {metrics['win_rate'] * 100:.2f}%")
    print(f"Expectancy: {metrics['expectancy_pct']:.4f}%")
    print(f"Profit factor: {metrics['profit_factor']:.4f}")
    print(f"Total PnL: ${metrics['total_pnl_cents'] / 100:+.2f}")
    print(f"State: {args.state_out}")


if __name__ == "__main__":
    main()
