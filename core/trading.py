"""
Reusable trading primitives for Kalshi automation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import json
import math


def clamp_probability(value: float) -> float:
    return max(0.0, min(1.0, value))


def to_probability(raw: Any) -> Optional[float]:
    """
    Convert mixed price formats into probability units [0, 1].

    Kalshi data can appear as:
    - probability: 0.37
    - cents: 37
    - basis points: 3700
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or value < 0:
        return None
    if value <= 1:
        return clamp_probability(value)
    if value <= 100:
        return clamp_probability(value / 100.0)
    if value <= 10000:
        return clamp_probability(value / 10000.0)
    return None


def probability_to_cents(probability: float) -> int:
    return int(round(clamp_probability(probability) * 100))


def parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class AlphaSignal:
    fair_yes_probability: float
    confidence: float
    source: str = "unknown"
    model_version: Optional[str] = None
    horizon_minutes: Optional[int] = None
    expected_edge_net: Optional[float] = None
    generated_at: Optional[str] = None

    @classmethod
    def from_payload(cls, payload: Any) -> Optional["AlphaSignal"]:
        fair_prob: Optional[float] = None
        confidence = 0.5
        source = "unknown"
        model_version: Optional[str] = None
        horizon_minutes: Optional[int] = None
        expected_edge_net: Optional[float] = None
        generated_at: Optional[str] = None

        if isinstance(payload, (float, int)):
            fair_prob = to_probability(payload)
        elif isinstance(payload, dict):
            fair_prob = to_probability(
                payload.get("fair_yes_probability")
                or payload.get("fair_prob")
                or payload.get("probability")
                or payload.get("yes_probability")
            )
            raw_conf = payload.get("confidence", confidence)
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = 0.5
            source = str(payload.get("source", source))
            raw_model_version = payload.get("model_version")
            if raw_model_version is not None:
                model_version = str(raw_model_version)
            raw_horizon = payload.get("horizon_minutes")
            try:
                if raw_horizon is not None:
                    horizon_minutes = int(raw_horizon)
            except (TypeError, ValueError):
                horizon_minutes = None
            raw_expected_edge_net = payload.get("expected_edge_net")
            try:
                if raw_expected_edge_net is not None:
                    expected_edge_net = float(raw_expected_edge_net)
            except (TypeError, ValueError):
                expected_edge_net = None
            raw_generated_at = payload.get("generated_at")
            if raw_generated_at is not None:
                generated_at = str(raw_generated_at)
        else:
            return None

        if fair_prob is None:
            return None
        return cls(
            fair_yes_probability=clamp_probability(fair_prob),
            confidence=clamp_probability(confidence),
            source=source,
            model_version=model_version,
            horizon_minutes=horizon_minutes,
            expected_edge_net=expected_edge_net,
            generated_at=generated_at,
        )


@dataclass(frozen=True)
class MarketQuote:
    ticker: str
    title: str
    category: str
    volume: float
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]

    @classmethod
    def from_market(cls, market: Dict[str, Any]) -> Optional["MarketQuote"]:
        ticker = str(market.get("ticker", "")).strip()
        if not ticker:
            return None

        yes_bid = to_probability(market.get("yes_bid"))
        yes_ask = to_probability(market.get("yes_ask"))
        no_bid = to_probability(market.get("no_bid"))
        no_ask = to_probability(market.get("no_ask"))

        # Infer missing opposite-side quotes where possible.
        if no_bid is None and yes_ask is not None:
            no_bid = clamp_probability(1 - yes_ask)
        if no_ask is None and yes_bid is not None:
            no_ask = clamp_probability(1 - yes_bid)
        if yes_bid is None and no_ask is not None:
            yes_bid = clamp_probability(1 - no_ask)
        if yes_ask is None and no_bid is not None:
            yes_ask = clamp_probability(1 - no_bid)

        # Correct inverted books defensively.
        if yes_bid is not None and yes_ask is not None and yes_ask < yes_bid:
            yes_bid, yes_ask = yes_ask, yes_bid
        if no_bid is not None and no_ask is not None and no_ask < no_bid:
            no_bid, no_ask = no_ask, no_bid

        raw_volume = market.get("volume", 0)
        try:
            volume = float(raw_volume or 0)
        except (TypeError, ValueError):
            volume = 0.0

        title = str(market.get("title") or ticker)
        category = str(market.get("category") or "unknown")
        return cls(
            ticker=ticker,
            title=title,
            category=category,
            volume=volume,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
        )

    def entry_price(self, side: str) -> Optional[float]:
        return self.yes_ask if side == "yes" else self.no_ask

    def exit_price(self, side: str) -> Optional[float]:
        return self.yes_bid if side == "yes" else self.no_bid

    def spread(self, side: str) -> Optional[float]:
        if side == "yes":
            if self.yes_ask is None or self.yes_bid is None:
                return None
            return max(0.0, self.yes_ask - self.yes_bid)
        if self.no_ask is None or self.no_bid is None:
            return None
        return max(0.0, self.no_ask - self.no_bid)


def load_alpha_signals(alpha_file: Path) -> Dict[str, AlphaSignal]:
    if not alpha_file.exists():
        return {}

    try:
        payload = json.loads(alpha_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    signals_payload: Any = payload.get("signals") if isinstance(payload, dict) else payload
    if not isinstance(signals_payload, dict):
        return {}

    signals: Dict[str, AlphaSignal] = {}
    for ticker, raw_signal in signals_payload.items():
        if not ticker:
            continue
        parsed = AlphaSignal.from_payload(raw_signal)
        if parsed:
            signals[str(ticker)] = parsed
    return signals


def write_alpha_signals(
    alpha_file: Path,
    signals: Dict[str, AlphaSignal],
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            ticker: _alpha_payload(signal)
            for ticker, signal in sorted(signals.items())
        },
    }
    if metadata:
        payload.update(metadata)
    alpha_file.parent.mkdir(parents=True, exist_ok=True)
    alpha_file.write_text(json.dumps(payload, indent=2))


def _alpha_payload(signal: AlphaSignal) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fair_yes_probability": round(signal.fair_yes_probability, 6),
        "confidence": round(signal.confidence, 6),
        "source": signal.source,
    }
    if signal.model_version:
        payload["model_version"] = signal.model_version
    if signal.horizon_minutes is not None:
        payload["horizon_minutes"] = int(signal.horizon_minutes)
    if signal.expected_edge_net is not None:
        payload["expected_edge_net"] = round(float(signal.expected_edge_net), 6)
    if signal.generated_at:
        payload["generated_at"] = str(signal.generated_at)
    return payload


def apply_probability_calibration(
    probability: float,
    calibration_bins: Sequence[Tuple[float, float]],
) -> float:
    """
    Apply piecewise-linear probability calibration.

    calibration_bins: sequence of (raw_probability, calibrated_probability)
    pairs sorted by raw_probability in ascending order.
    """
    p = clamp_probability(probability)
    if not calibration_bins:
        return p

    ordered = sorted(
        (
            clamp_probability(float(raw_p)),
            clamp_probability(float(cal_p)),
        )
        for raw_p, cal_p in calibration_bins
    )
    if p <= ordered[0][0]:
        return ordered[0][1]
    if p >= ordered[-1][0]:
        return ordered[-1][1]

    for idx in range(1, len(ordered)):
        left_raw, left_cal = ordered[idx - 1]
        right_raw, right_cal = ordered[idx]
        if left_raw <= p <= right_raw:
            span = right_raw - left_raw
            if span <= 1e-9:
                return right_cal
            weight = (p - left_raw) / span
            return clamp_probability(left_cal + weight * (right_cal - left_cal))
    return p


def load_probability_calibration(path: Path) -> List[Tuple[float, float]]:
    """
    Read calibration bins from a calibration JSON file.
    """
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    raw_bins = payload.get("bins", []) if isinstance(payload, dict) else []
    bins: List[Tuple[float, float]] = []
    for row in raw_bins:
        if not isinstance(row, dict):
            continue
        raw_p = to_probability(row.get("raw_probability"))
        cal_p = to_probability(row.get("calibrated_probability"))
        if raw_p is None or cal_p is None:
            continue
        bins.append((raw_p, cal_p))
    bins.sort(key=lambda item: item[0])
    return bins


def compute_binary_kelly(win_probability: float, price_probability: float) -> float:
    """
    Kelly fraction for binary contract.
    """
    p = clamp_probability(win_probability)
    c = clamp_probability(price_probability)
    if c <= 0 or c >= 1:
        return 0.0
    return max(0.0, (p - c) / (1.0 - c))


def compute_performance_metrics(closed_positions: List[Dict[str, Any]]) -> Dict[str, float]:
    if not closed_positions:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_pnl_cents": 0.0,
            "expectancy_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_cents": 0.0,
            "avg_holding_minutes": 0.0,
        }

    pnl_values: List[float] = []
    return_values: List[float] = []
    holding_minutes: List[float] = []

    for trade in closed_positions:
        pnl = float(trade.get("pnl_cents", trade.get("pnl", 0.0)) or 0.0)
        pnl_values.append(pnl)

        notional = float(trade.get("notional_cents", 0.0) or 0.0)
        if notional > 0:
            return_values.append(pnl / notional)

        opened = parse_timestamp(trade.get("opened_at") or trade.get("timestamp"))
        closed = parse_timestamp(trade.get("closed_at") or trade.get("exit_time"))
        if opened and closed and closed >= opened:
            holding_minutes.append((closed - opened).total_seconds() / 60.0)

    wins = sum(1 for pnl in pnl_values if pnl > 0)
    losses = sum(1 for pnl in pnl_values if pnl < 0)

    gross_profit = sum(pnl for pnl in pnl_values if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnl_values if pnl < 0))
    total_pnl = sum(pnl_values)

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = gross_profit
    else:
        profit_factor = 0.0
    expectancy = sum(return_values) / len(return_values) if return_values else 0.0
    avg_holding = sum(holding_minutes) / len(holding_minutes) if holding_minutes else 0.0

    return {
        "trades": len(closed_positions),
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / len(closed_positions)) if closed_positions else 0.0,
        "total_pnl_cents": total_pnl,
        "expectancy_pct": expectancy * 100.0,
        "profit_factor": profit_factor,
        "max_drawdown_cents": max_drawdown,
        "avg_holding_minutes": avg_holding,
    }
