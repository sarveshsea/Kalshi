#!/usr/bin/env python3
"""
Build alpha_signals.json from public market tape + orderbook flow.

Signals are market-level "smart money flow follower" estimates:
- public trades (/markets/trades)
- orderbook imbalance
- short-horizon volume acceleration
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client import KalshiClient
from core.trading import (
    AlphaSignal,
    MarketQuote,
    apply_probability_calibration,
    load_probability_calibration,
    parse_timestamp,
    to_probability,
    write_alpha_signals,
)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(value) or math.isinf(value):
        return default
    return value


def parse_side_signal(raw_side: Any) -> int:
    side = str(raw_side or "").strip().lower()
    if not side:
        return 0
    if "no" in side:
        return -1
    if "yes" in side:
        return 1
    return 0


def trade_yes_probability(trade: Dict[str, Any]) -> Optional[float]:
    yes_price = to_probability(trade.get("yes_price"))
    if yes_price is not None:
        return yes_price
    no_price = to_probability(trade.get("no_price"))
    if no_price is not None:
        return clamp(1.0 - no_price)
    return to_probability(trade.get("price"))


def orderbook_imbalance(orderbook: Optional[Dict[str, List[Dict[str, float]]]], depth: int = 5) -> float:
    if not orderbook:
        return 0.0
    yes_levels = orderbook.get("yes_bids", [])[:depth]
    no_levels = orderbook.get("no_bids", [])[:depth]
    yes_qty = sum(max(0.0, safe_float(level.get("quantity"))) for level in yes_levels)
    no_qty = sum(max(0.0, safe_float(level.get("quantity"))) for level in no_levels)
    total = yes_qty + no_qty
    if total <= 0:
        return 0.0
    return (yes_qty - no_qty) / total


def compute_trade_features(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    if not trades:
        return {
            "trade_count": 0.0,
            "signed_pressure": 0.0,
            "volume_accel": 0.0,
            "price_momentum": 0.0,
        }

    indexed = []
    for trade in trades:
        dt = parse_timestamp(trade.get("created_time")) or datetime.min.replace(tzinfo=timezone.utc)
        indexed.append((dt, trade))
    indexed.sort(key=lambda x: x[0])
    ordered = [trade for _, trade in indexed]

    quantities = [max(0.0, safe_float(t.get("count"))) for t in ordered]
    yes_prices = [trade_yes_probability(t) for t in ordered]
    signs = [parse_side_signal(t.get("side")) for t in ordered]

    total_qty = sum(quantities)
    signed_qty = sum(sign * qty for sign, qty in zip(signs, quantities))
    signed_pressure = (signed_qty / total_qty) if total_qty > 0 else 0.0

    window = max(3, len(ordered) // 3)
    recent_qty = sum(quantities[-window:])
    prior_qty = sum(quantities[-2 * window : -window]) if len(ordered) >= 2 * window else sum(quantities[:-window])
    volume_accel = ((recent_qty - prior_qty) / prior_qty) if prior_qty > 0 else 0.0

    recent_prices = [p for p in yes_prices[-window:] if p is not None]
    prior_prices = [p for p in yes_prices[-2 * window : -window] if p is not None]
    if not prior_prices:
        prior_prices = [p for p in yes_prices[:-window] if p is not None]
    price_momentum = 0.0
    if recent_prices and prior_prices:
        price_momentum = (sum(recent_prices) / len(recent_prices)) - (sum(prior_prices) / len(prior_prices))

    return {
        "trade_count": float(len(ordered)),
        "signed_pressure": signed_pressure,
        "volume_accel": volume_accel,
        "price_momentum": price_momentum,
    }


def score_market(
    quote: MarketQuote,
    trade_features: Dict[str, float],
    imbalance: float,
) -> Dict[str, float]:
    mid = None
    if quote.yes_bid is not None and quote.yes_ask is not None:
        mid = (quote.yes_bid + quote.yes_ask) / 2.0
    elif quote.yes_bid is not None:
        mid = quote.yes_bid
    elif quote.yes_ask is not None:
        mid = quote.yes_ask
    else:
        mid = 0.5

    signed_pressure = trade_features["signed_pressure"]
    volume_accel = math.tanh(trade_features["volume_accel"])
    price_momentum = math.tanh(trade_features["price_momentum"] * 10.0)

    flow_score = (
        0.42 * signed_pressure
        + 0.25 * imbalance
        + 0.20 * volume_accel
        + 0.13 * price_momentum
    )
    flow_score = max(-1.0, min(1.0, flow_score))

    fair_yes = clamp(mid + (flow_score * 0.18), 0.02, 0.98)
    base_conf = 0.45 + 0.30 * abs(flow_score)
    trade_conf = min(0.25, trade_features["trade_count"] / 250.0)
    confidence = clamp(base_conf + trade_conf, 0.05, 0.99)

    return {
        "mid_probability": mid,
        "flow_score": flow_score,
        "fair_yes_probability": fair_yes,
        "confidence": confidence,
    }


def build_signals(args: argparse.Namespace) -> List[Dict[str, Any]]:
    client = KalshiClient(env=args.env)
    calibration_bins = (
        load_probability_calibration(Path(args.calibration))
        if args.calibration
        else []
    )
    markets = client.get_markets(status="open", limit=args.markets_limit)
    quotes: List[MarketQuote] = []
    for market in markets:
        quote = MarketQuote.from_market(market)
        if quote:
            quotes.append(quote)

    candidates: List[Dict[str, Any]] = []
    for quote in quotes:
        if quote.volume < args.min_market_volume:
            continue
        spread = quote.spread("yes")
        if spread is None or spread > args.max_spread:
            continue

        trades = client.get_market_trades(quote.ticker, limit=args.trade_limit)
        trade_features = compute_trade_features(trades)
        if trade_features["trade_count"] < args.min_trades:
            continue

        book = client.get_public_orderbook(quote.ticker)
        imbalance = orderbook_imbalance(book, depth=args.book_depth)
        scored = score_market(quote, trade_features, imbalance)
        if scored["confidence"] < args.min_confidence:
            continue

        raw_fair = float(scored["fair_yes_probability"])
        calibrated_fair = (
            apply_probability_calibration(raw_fair, calibration_bins)
            if calibration_bins
            else raw_fair
        )
        edge = abs(calibrated_fair - scored["mid_probability"])
        candidates.append(
            {
                "ticker": quote.ticker,
                "title": quote.title,
                "volume": quote.volume,
                "spread": spread,
                "trade_count": int(trade_features["trade_count"]),
                "signed_pressure": trade_features["signed_pressure"],
                "volume_accel": trade_features["volume_accel"],
                "price_momentum": trade_features["price_momentum"],
                "orderbook_imbalance": imbalance,
                "flow_score": scored["flow_score"],
                "mid_probability": scored["mid_probability"],
                "raw_fair_yes_probability": raw_fair,
                "fair_yes_probability": calibrated_fair,
                "confidence": scored["confidence"],
                "edge_magnitude": edge,
                "source": args.source_tag,
            }
        )

    candidates.sort(key=lambda row: row["edge_magnitude"] * row["confidence"], reverse=True)
    if args.top_k > 0:
        candidates = candidates[: args.top_k]
    return candidates


def write_outputs(
    signals: List[Dict[str, Any]],
    alpha_out: Path,
    csv_out: Optional[Path],
    source_tag: str,
    model_version: str,
    horizon_minutes: int,
) -> None:
    normalized = {
        signal["ticker"]: AlphaSignal(
            fair_yes_probability=float(signal["fair_yes_probability"]),
            confidence=float(signal["confidence"]),
            source=source_tag,
            model_version=model_version,
            horizon_minutes=horizon_minutes,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        for signal in signals
    }
    write_alpha_signals(alpha_out, normalized, metadata={"source": source_tag})

    if csv_out:
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "ticker",
            "title",
            "volume",
            "spread",
            "trade_count",
            "signed_pressure",
            "volume_accel",
            "price_momentum",
            "orderbook_imbalance",
            "flow_score",
            "mid_probability",
            "raw_fair_yes_probability",
            "fair_yes_probability",
            "confidence",
            "edge_magnitude",
            "source",
        ]
        with csv_out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in signals:
                writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build alpha_signals.json from Kalshi flow data")
    parser.add_argument("--env", default="prod", choices=["demo", "prod"])
    parser.add_argument("--markets-limit", type=int, default=200)
    parser.add_argument("--trade-limit", type=int, default=120)
    parser.add_argument("--book-depth", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--min-market-volume", type=float, default=2500.0)
    parser.add_argument("--min-trades", type=int, default=15)
    parser.add_argument("--max-spread", type=float, default=0.08)
    parser.add_argument("--min-confidence", type=float, default=0.6)
    parser.add_argument("--source-tag", default="smart_money_flow_v1")
    parser.add_argument("--model-version", default="smart_money_flow_v1")
    parser.add_argument("--horizon-minutes", type=int, default=60)
    parser.add_argument("--calibration", help="Optional alpha calibration JSON file")
    parser.add_argument("--alpha-out", default="data/alpha_signals.json")
    parser.add_argument("--csv-out", default="data/flow_signals_latest.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    signals = build_signals(args)
    if not signals:
        raise SystemExit("No signals generated from flow data (adjust filters).")
    alpha_out = Path(args.alpha_out)
    csv_out = Path(args.csv_out) if args.csv_out else None
    write_outputs(
        signals,
        alpha_out,
        csv_out,
        args.source_tag,
        model_version=str(args.model_version),
        horizon_minutes=int(args.horizon_minutes),
    )
    print(f"Generated {len(signals)} flow signals")
    print(f"Alpha file: {alpha_out}")
    if csv_out:
        print(f"Signal CSV: {csv_out}")


if __name__ == "__main__":
    main()
