#!/usr/bin/env python3
"""
Daily quant PM report for auto-trader operations.

Outputs:
- signal quality snapshot from alpha_signals.json
- execution-cost diagnostics from closed trades
- gate trajectory + explicit GO/NO-GO verdict
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.trading import load_alpha_signals
from ops.gate_metrics import evaluate_go_live_gates

DEFAULT_FEE_PER_CONTRACT_PROB = 0.008
DEFAULT_SLIPPAGE_SPREAD_FACTOR = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily quant PM report")
    parser.add_argument("--state", default="data/auto_trader_state.json")
    parser.add_argument("--alpha", default="data/alpha_signals.json")
    parser.add_argument("--output", default="data/quant_pm_report.md")
    parser.add_argument("--json-output", default="data/quant_pm_report.json")
    parser.add_argument("--history-file", default="data/quant_pm_history.jsonl")
    parser.add_argument("--paper-bankroll", type=float, default=250.0)

    parser.add_argument("--min-trades", type=int, default=300)
    parser.add_argument("--min-expectancy", type=float, default=0.0, help="Percent per trade")
    parser.add_argument("--min-profit-factor", type=float, default=1.15)
    parser.add_argument("--max-drawdown", type=float, default=25.0, help="Percent of bankroll")
    parser.add_argument("--min-cost-coverage", type=float, default=0.95)
    parser.add_argument("--holdout-windows", default="100,200")
    parser.add_argument("--max-concentration-share", type=float, default=0.25)
    parser.add_argument("--rolling-windows", default="50,100,200", help="Comma-separated trailing windows")
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN check
        return default
    return value


def _parse_windows(raw: str) -> List[int]:
    windows: List[int] = []
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            value = int(text)
        except ValueError:
            continue
        if value > 0:
            windows.append(value)
    return sorted(set(windows))


def _source_counts(signals: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for signal in signals.values():
        source = str(getattr(signal, "source", "unknown") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def compute_signal_quality(alpha_path: Path) -> Dict[str, Any]:
    signals = load_alpha_signals(alpha_path)
    if not signals:
        return {
            "signal_count": 0,
            "avg_confidence": 0.0,
            "median_confidence": 0.0,
            "avg_conviction": 0.0,
            "strong_signal_count": 0,
            "yes_bias_ratio": 0.0,
            "quality_score": 0.0,
            "source_counts": {},
        }

    confidences = [signal.confidence for signal in signals.values()]
    convictions = [abs(signal.fair_yes_probability - 0.5) * 2.0 for signal in signals.values()]
    strong = sum(
        1
        for signal in signals.values()
        if signal.confidence >= 0.75 and abs(signal.fair_yes_probability - 0.5) >= 0.075
    )
    yes_bias = sum(1 for signal in signals.values() if signal.fair_yes_probability >= 0.5)

    avg_conf = mean(confidences)
    avg_conviction = mean(convictions)
    return {
        "signal_count": len(signals),
        "avg_confidence": avg_conf,
        "median_confidence": median(confidences),
        "avg_conviction": avg_conviction,
        "strong_signal_count": strong,
        "yes_bias_ratio": yes_bias / max(len(signals), 1),
        "quality_score": avg_conf * avg_conviction,
        "source_counts": _source_counts(signals),
    }


def compute_trailing_metrics(
    closed_positions: Sequence[Dict[str, Any]],
    windows: Sequence[int],
) -> List[Dict[str, float]]:
    from core.trading import compute_performance_metrics

    result: List[Dict[str, float]] = []
    for window in windows:
        if len(closed_positions) < window:
            continue
        metrics = compute_performance_metrics(list(closed_positions[-window:]))
        result.append(
            {
                "window": float(window),
                "trades": float(metrics["trades"]),
                "win_rate_pct": float(metrics["win_rate"]) * 100.0,
                "expectancy_pct": float(metrics["expectancy_pct"]),
                "profit_factor": float(metrics["profit_factor"]),
                "pnl_cents": float(metrics["total_pnl_cents"]),
            }
        )
    return result


def load_history(history_path: Path) -> List[Dict[str, Any]]:
    if not history_path.exists():
        return []
    entries: List[Dict[str, Any]] = []
    for line in history_path.read_text().splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def append_history(history_path: Path, payload: Dict[str, Any]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def _format_check_line(check: Dict[str, Any]) -> str:
    status = "PASS" if check["pass"] else "FAIL"
    name = check["name"]
    raw_value = check["value"]
    threshold = float(check["threshold"])
    direction = check["direction"]
    if isinstance(raw_value, str):
        return f"- {status} | {name}: insufficient trades ({direction} 0.0000%)"
    value = float(raw_value)
    if name == "trades":
        value_text = f"{int(value)}"
        threshold_text = f"{int(threshold)}"
    elif name == "max_drawdown_pct":
        value_text = f"{value:.4f}%"
        threshold_text = f"{threshold:.4f}%"
    elif name in {"cost_coverage_ratio", "max_ticker_concentration"}:
        value_text = f"{value * 100:.2f}%"
        threshold_text = f"{threshold * 100:.2f}%"
    else:
        value_text = f"{value:.4f}"
        threshold_text = f"{threshold:.4f}"
    return (
        f"- {status} | {name}: {value_text} {direction} {threshold_text} "
        f"(progress {check['progress'] * 100:.1f}%)"
    )


def build_markdown(
    generated_at_iso: str,
    verdict: str,
    signal_quality: Dict[str, Any],
    gate_status: Dict[str, Any],
    trailing: Sequence[Dict[str, float]],
    delta_from_previous: Optional[Dict[str, float]],
    args: argparse.Namespace,
) -> str:
    checks = gate_status["checks"]
    metrics = gate_status["metrics"]
    cost_summary = gate_status["cost_summary"]
    concentration = gate_status["concentration"]
    holdout_expectancies = gate_status["holdout_expectancies"]
    source_counts = signal_quality["source_counts"]
    top_sources = sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:5]

    lines: List[str] = []
    lines.append(f"# Quant PM Report ({generated_at_iso})")
    lines.append("")
    lines.append(f"## Verdict: **{verdict}**")
    lines.append("")
    lines.append("## Gate Status")
    for check in checks:
        lines.append(_format_check_line(check))
    lines.append(
        f"- Closed trades: {int(metrics['trades'])} | Win rate: {metrics['win_rate'] * 100:.2f}% | "
        f"Total PnL: ${metrics['total_pnl_cents'] / 100:+.2f}"
    )
    lines.append(
        f"- Drawdown: ${metrics['max_drawdown_cents'] / 100:.2f} "
        f"({gate_status['max_drawdown_pct']:.2f}% of bankroll)"
    )
    if concentration["max_ticker"]:
        lines.append(
            f"- Concentration leader: {concentration['max_ticker']} "
            f"({concentration['max_share_of_abs_pnl'] * 100:.2f}% of abs PnL)"
        )

    lines.append("")
    lines.append("## Gate Trajectory")
    if delta_from_previous:
        lines.append(
            f"- Since previous report: trades {delta_from_previous['trades']:+.0f}, "
            f"expectancy {delta_from_previous['expectancy_pct']:+.4f}pp, "
            f"profit factor {delta_from_previous['profit_factor']:+.4f}, "
            f"drawdown {delta_from_previous['max_drawdown_pct']:+.2f}pp"
        )
    else:
        lines.append("- No prior report snapshot found; trajectory starts from this run.")
    for window, expectancy in sorted(holdout_expectancies.items()):
        if expectancy is None:
            lines.append(f"- Holdout {window}: insufficient trades")
        else:
            lines.append(f"- Holdout {window} expectancy: {expectancy:+.4f}%")
    if trailing:
        for row in trailing:
            lines.append(
                f"- Trailing {int(row['window'])}: expectancy {row['expectancy_pct']:+.4f}%, "
                f"profit factor {row['profit_factor']:.4f}, win rate {row['win_rate_pct']:.2f}%, "
                f"PnL ${row['pnl_cents'] / 100:+.2f}"
            )
    else:
        lines.append("- Not enough trades yet for configured trailing windows.")

    lines.append("")
    lines.append("## Signal Quality")
    lines.append(f"- Active signals: {signal_quality['signal_count']}")
    lines.append(
        f"- Confidence: avg {signal_quality['avg_confidence'] * 100:.2f}%, "
        f"median {signal_quality['median_confidence'] * 100:.2f}%"
    )
    lines.append(
        f"- Conviction (|p_yes-0.5|*2): avg {signal_quality['avg_conviction'] * 100:.2f}%"
    )
    lines.append(
        f"- Strong signals: {signal_quality['strong_signal_count']} | "
        f"YES bias ratio: {signal_quality['yes_bias_ratio'] * 100:.2f}% | "
        f"quality score: {signal_quality['quality_score'] * 100:.2f}"
    )
    if top_sources:
        source_text = ", ".join(f"{name}:{count}" for name, count in top_sources)
        lines.append(f"- Top sources: {source_text}")
    else:
        lines.append("- Top sources: none")

    lines.append("")
    lines.append("## Execution Costs")
    lines.append(
        f"- Cost telemetry coverage: {cost_summary['cost_coverage_trades']}/"
        f"{cost_summary['closed_trades']} closed trades "
        f"({cost_summary['cost_coverage_ratio'] * 100:.2f}%)"
    )
    lines.append(
        f"- Configured fee/slippage model: fee={cost_summary['fee_per_contract_prob'] * 100:.2f}¢/side, "
        f"slippage_factor={cost_summary['slippage_spread_factor']:.2f}"
    )
    lines.append(
        f"- Entry edges: gross {cost_summary['avg_gross_edge'] * 100:.3f}%, "
        f"net {cost_summary['avg_net_edge'] * 100:.3f}%, "
        f"cost drag {cost_summary['avg_round_trip_cost'] * 100:.3f}%"
    )
    lines.append(
        f"- Estimated total friction: ${cost_summary['estimated_total_cost_cents'] / 100:.2f} "
        f"({cost_summary['estimated_cost_bps_on_notional']:.2f} bps of notional)"
    )
    lines.append(
        f"- Realized return on traded notional: {cost_summary['realized_return_pct']:+.4f}%"
    )

    lines.append("")
    lines.append("## Gates (Configured)")
    lines.append(
        f"- Primary: trades >= {args.min_trades}, expectancy > {args.min_expectancy:.4f}%, "
        f"profit_factor >= {args.min_profit_factor:.4f}, drawdown <= {args.max_drawdown:.2f}%"
    )
    lines.append(
        f"- Additional: cost_coverage >= {args.min_cost_coverage * 100:.2f}%, "
        f"holdout windows [{args.holdout_windows}] expectancy > 0, "
        f"max ticker concentration <= {args.max_concentration_share * 100:.2f}%"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    generated_at = datetime.now(timezone.utc).isoformat()

    state_path = Path(args.state)
    alpha_path = Path(args.alpha)
    output_path = Path(args.output)
    json_output_path = Path(args.json_output) if args.json_output else None
    history_path = Path(args.history_file)

    if not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")
    try:
        state = _read_json(state_path)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse state file: {exc}") from exc

    closed_positions = state.get("closed_positions", [])
    if not isinstance(closed_positions, list):
        closed_positions = []

    signal_quality = compute_signal_quality(alpha_path)
    config = state.get("config", {}) if isinstance(state.get("config"), dict) else {}
    fee_prob = _safe_float(
        config.get("fee_per_contract_prob", DEFAULT_FEE_PER_CONTRACT_PROB),
        DEFAULT_FEE_PER_CONTRACT_PROB,
    )
    slippage_factor = _safe_float(
        config.get("slippage_spread_factor", DEFAULT_SLIPPAGE_SPREAD_FACTOR),
        DEFAULT_SLIPPAGE_SPREAD_FACTOR,
    )

    holdout_windows = _parse_windows(args.holdout_windows)
    gate_status = evaluate_go_live_gates(
        closed_positions,
        paper_bankroll=float(args.paper_bankroll),
        min_trades=int(args.min_trades),
        min_expectancy=float(args.min_expectancy),
        min_profit_factor=float(args.min_profit_factor),
        max_drawdown=float(args.max_drawdown),
        min_cost_coverage=float(args.min_cost_coverage),
        holdout_windows=holdout_windows,
        max_concentration_share=float(args.max_concentration_share),
        fee_per_contract_prob=fee_prob,
        slippage_spread_factor=slippage_factor,
    )

    windows = _parse_windows(args.rolling_windows)
    trailing = compute_trailing_metrics(closed_positions, windows)

    previous_entries = load_history(history_path)
    previous = previous_entries[-1] if previous_entries else None
    current_snapshot = {
        "timestamp": generated_at,
        "state": str(state_path),
        "alpha": str(alpha_path),
        "trades": int(gate_status["metrics"]["trades"]),
        "expectancy_pct": float(gate_status["metrics"]["expectancy_pct"]),
        "profit_factor": float(gate_status["metrics"]["profit_factor"]),
        "max_drawdown_pct": float(gate_status["max_drawdown_pct"]),
        "cost_coverage_ratio": float(gate_status["cost_summary"]["cost_coverage_ratio"]),
        "max_ticker_concentration": float(gate_status["concentration"]["max_share_of_abs_pnl"]),
        "holdout_expectancies": {str(k): v for k, v in gate_status["holdout_expectancies"].items()},
        "go_live": bool(gate_status["go_live"]),
    }
    append_history(history_path, current_snapshot)

    delta_from_previous: Optional[Dict[str, float]] = None
    if previous:
        delta_from_previous = {
            "trades": float(current_snapshot["trades"]) - _safe_float(previous.get("trades"), 0.0),
            "expectancy_pct": float(current_snapshot["expectancy_pct"]) - _safe_float(previous.get("expectancy_pct"), 0.0),
            "profit_factor": float(current_snapshot["profit_factor"]) - _safe_float(previous.get("profit_factor"), 0.0),
            "max_drawdown_pct": float(current_snapshot["max_drawdown_pct"]) - _safe_float(previous.get("max_drawdown_pct"), 0.0),
        }

    verdict = "GO LIVE" if gate_status["go_live"] else "NO-GO (PAPER ONLY)"
    report = build_markdown(
        generated_at_iso=generated_at,
        verdict=verdict,
        signal_quality=signal_quality,
        gate_status=gate_status,
        trailing=trailing,
        delta_from_previous=delta_from_previous,
        args=args,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    json_payload = {
        "generated_at": generated_at,
        "verdict": verdict,
        "go_live": bool(gate_status["go_live"]),
        "state_file": str(state_path),
        "alpha_file": str(alpha_path),
        "signal_quality": signal_quality,
        "gate": gate_status,
        "trailing_metrics": trailing,
        "delta_from_previous": delta_from_previous,
    }
    if json_output_path:
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(json.dumps(json_payload, indent=2))

    print(report, end="")
    print(f"Report written: {output_path}")
    if json_output_path:
        print(f"JSON report: {json_output_path}")
    print(f"History updated: {history_path}")


if __name__ == "__main__":
    main()
