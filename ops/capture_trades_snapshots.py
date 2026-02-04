#!/usr/bin/env python3
"""
Capture deterministic replay snapshots from public markets/trades/orderbooks.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Dict, List

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client import KalshiClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture /markets/trades snapshots for replay")
    parser.add_argument("--env", default="prod", choices=["demo", "prod"])
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--markets-limit", type=int, default=200)
    parser.add_argument("--top-markets", type=int, default=30)
    parser.add_argument("--min-volume", type=float, default=2500.0)
    parser.add_argument("--trade-limit", type=int, default=120)
    parser.add_argument("--out", default="data/trades_snapshots.jsonl")
    return parser.parse_args()


def compact_market(market: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticker": market.get("ticker"),
        "title": market.get("title", ""),
        "category": market.get("category", "unknown"),
        "volume": market.get("volume", 0),
        "yes_bid": market.get("yes_bid"),
        "yes_ask": market.get("yes_ask"),
        "no_bid": market.get("no_bid"),
        "no_ask": market.get("no_ask"),
        "last_price": market.get("last_price"),
    }


def main() -> None:
    args = parse_args()
    client = KalshiClient(env=args.env)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for idx in range(args.cycles):
        markets = client.get_markets(status="open", limit=args.markets_limit)
        markets = [m for m in markets if float(m.get("volume", 0) or 0) >= args.min_volume]
        markets.sort(key=lambda m: float(m.get("volume", 0) or 0), reverse=True)
        markets = markets[: args.top_markets]

        snapshot_markets: List[Dict[str, Any]] = []
        trades_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        books_by_ticker: Dict[str, Dict[str, Any]] = {}

        for market in markets:
            ticker = str(market.get("ticker", "")).strip()
            if not ticker:
                continue
            snapshot_markets.append(compact_market(market))
            trades_by_ticker[ticker] = client.get_market_trades(ticker=ticker, limit=args.trade_limit)
            books_by_ticker[ticker] = client.get_public_orderbook(ticker) or {"yes_bids": [], "no_bids": []}

        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sequence": idx + 1,
            "markets": snapshot_markets,
            "trades": trades_by_ticker,
            "orderbooks": books_by_ticker,
        }
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(snapshot) + "\n")
        print(
            f"Captured snapshot {idx + 1}/{args.cycles} | "
            f"markets={len(snapshot_markets)} | out={out_path}"
        )
        if idx + 1 < args.cycles:
            time.sleep(args.interval_seconds)


if __name__ == "__main__":
    main()
