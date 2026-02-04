#!/usr/bin/env python3
"""
Generate Kalshi alpha signals from a model export CSV.

STRICT MODE:
Only rows that contain an actual Kalshi ticker + fair_yes_probability +
confidence are eligible for alpha generation.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.trading import AlphaSignal, write_alpha_signals


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _safe_float(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _prob_from_raw(raw: Any) -> Optional[float]:
    value = _safe_float(raw)
    if value is None:
        return None
    if value < 0:
        return None
    if value <= 1:
        return _clamp(value)
    if value <= 100:
        return _clamp(value / 100.0)
    if value <= 10000:
        return _clamp(value / 10000.0)
    return None


def _read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _ticker_for_row(row: Dict[str, str]) -> Optional[str]:
    direct_keys = ("ticker", "market_ticker", "kalshi_ticker")
    for key in direct_keys:
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return None


def _direct_probability(row: Dict[str, str]) -> Optional[float]:
    return _prob_from_raw(row.get("fair_yes_probability"))


def _direct_confidence(row: Dict[str, str]) -> Optional[float]:
    return _prob_from_raw(row.get("confidence"))


def _build_signals(
    rows: Sequence[Dict[str, str]],
    top_k: int,
    bankroll: float,
) -> List[Dict[str, Any]]:
    built: List[Dict[str, Any]] = []
    skipped_missing = 0
    skipped_invalid = 0

    for row in rows:
        ticker = _ticker_for_row(row)
        direct_prob = _direct_probability(row)
        direct_conf = _direct_confidence(row)
        if not ticker:
            skipped_missing += 1
            continue
        if direct_prob is None or direct_conf is None:
            skipped_missing += 1
            continue
        if not ticker.startswith("KX"):
            skipped_invalid += 1
            continue

        source_hint = str(row.get("source", "")).strip()
        strategy_hint = str(row.get("strategy", "")).strip()
        symbol_hint = str(row.get("symbol", "")).strip()
        label = strategy_hint or symbol_hint or source_hint or "openclaw-model"
        model_version = str(row.get("model_version", "")).strip() or None
        horizon_minutes = _safe_float(row.get("horizon_minutes"))
        expected_edge_net = _prob_from_raw(row.get("expected_edge_net"))

        fair_yes_probability = direct_prob
        confidence = direct_conf
        score = abs(fair_yes_probability - 0.5) * confidence

        edge_magnitude = abs(fair_yes_probability - 0.5)
        side = "YES" if fair_yes_probability >= 0.5 else "NO"
        stake_fraction = _clamp(edge_magnitude * confidence * 2.4, 0.01, 0.25)
        recommended_stake_usd = round(bankroll * stake_fraction, 2)

        built.append(
            {
                "ticker": ticker,
                "fair_yes_probability": round(fair_yes_probability, 6),
                "confidence": round(confidence, 6),
                "score": round(score, 6),
                "edge_magnitude": round(edge_magnitude, 6),
                "side_bias": side,
                "recommended_stake_usd": recommended_stake_usd,
                "source": f"rarecandy:{label}",
                "model_version": model_version,
                "horizon_minutes": int(horizon_minutes) if horizon_minutes is not None else None,
                "expected_edge_net": expected_edge_net,
            }
        )

    # Keep only strongest signal per ticker.
    by_ticker: Dict[str, Dict[str, Any]] = {}
    for signal in built:
        existing = by_ticker.get(signal["ticker"])
        if existing is None or signal["score"] > existing["score"]:
            by_ticker[signal["ticker"]] = signal

    ranked = sorted(by_ticker.values(), key=lambda x: x["score"], reverse=True)
    if top_k > 0:
        ranked = ranked[:top_k]
    if skipped_missing:
        print(f"Skipped {skipped_missing} row(s): missing ticker/fair_yes_probability/confidence.")
    if skipped_invalid:
        print(f"Skipped {skipped_invalid} row(s): non-Kalshi ticker format.")
    return ranked


def _write_signal_csv(path: Path, signals: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker",
        "fair_yes_probability",
        "confidence",
        "score",
        "edge_magnitude",
        "side_bias",
        "recommended_stake_usd",
        "source",
        "model_version",
        "horizon_minutes",
        "expected_edge_net",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in signals:
            writer.writerow(row)


def _write_alpha_json(path: Path, signals: Sequence[Dict[str, Any]], input_path: Path) -> None:
    normalized = {
        row["ticker"]: AlphaSignal(
            fair_yes_probability=float(row["fair_yes_probability"]),
            confidence=float(row["confidence"]),
            source=str(row["source"]),
            model_version=row.get("model_version"),
            horizon_minutes=row.get("horizon_minutes"),
            expected_edge_net=row.get("expected_edge_net"),
        )
        for row in signals
    }
    write_alpha_signals(path, normalized, metadata={"input_file": str(input_path)})


def _write_telegram(path: Path, signals: Sequence[Dict[str, Any]], bankroll: float) -> None:
    lines = []
    lines.append("📈 *Kalshi Signal Pack*")
    lines.append(f"Bankroll: ${bankroll:,.2f}")
    lines.append("")
    if not signals:
        lines.append("No eligible signals generated.")
    else:
        for idx, signal in enumerate(signals, start=1):
            prob_pct = signal["fair_yes_probability"] * 100
            conf_pct = signal["confidence"] * 100
            edge_pct = signal["edge_magnitude"] * 100
            lines.append(
                f"{idx}. `{signal['ticker']}` | bias {signal['side_bias']} | "
                f"p_yes {prob_pct:.1f}% | conf {conf_pct:.0f}% | edge {edge_pct:.1f}%"
            )
            lines.append(
                f"   stake ${signal['recommended_stake_usd']:.2f} | src {signal['source']}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Kalshi trading signals from CSV")
    parser.add_argument("--input", required=True, help="Input model export CSV")
    parser.add_argument("--top_k", type=int, default=5, help="Number of signals to emit")
    parser.add_argument("--output", required=True, help="Output ranked signals CSV")
    parser.add_argument("--tg", required=True, help="Output telegram message file")
    parser.add_argument("--bankroll", type=float, default=100.0, help="Bankroll in USD")
    parser.add_argument(
        "--alpha",
        default="data/alpha_signals.json",
        help="Output alpha_signals.json path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    tg_path = Path(args.tg)
    alpha_path = Path(args.alpha)

    if not input_path.exists():
        raise SystemExit(f"Input CSV not found: {input_path}")

    headers, rows = _read_csv(input_path)
    if not rows:
        raise SystemExit("Input CSV has no rows.")
    lower_headers = {h.strip().lower() for h in headers}
    required = {"fair_yes_probability", "confidence"}
    if "ticker" not in lower_headers and "market_ticker" not in lower_headers and "kalshi_ticker" not in lower_headers:
        raise SystemExit("Input CSV missing ticker column (`ticker` or `market_ticker` or `kalshi_ticker`).")
    missing_required = sorted(required - lower_headers)
    if missing_required:
        raise SystemExit(f"Input CSV missing required column(s): {', '.join(missing_required)}")

    signals = _build_signals(rows=rows, top_k=args.top_k, bankroll=args.bankroll)
    if not signals:
        raise SystemExit(
            "No signals generated. Provide rows with valid Kalshi ticker + fair_yes_probability + confidence."
        )

    _write_signal_csv(output_path, signals)
    _write_telegram(tg_path, signals, args.bankroll)
    _write_alpha_json(alpha_path, signals, input_path)

    print(f"Generated {len(signals)} signals")
    print(f"Signal CSV: {output_path}")
    print(f"Telegram summary: {tg_path}")
    print(f"Alpha JSON: {alpha_path}")


if __name__ == "__main__":
    main()
