#!/usr/bin/env python3
"""Evaluate hard go-live gates from paper-trading state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops.gate_metrics import evaluate_go_live_gates

DEFAULT_FEE_PER_CONTRACT_PROB = 0.008
DEFAULT_SLIPPAGE_SPREAD_FACTOR = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check go-live gate for auto trader")
    parser.add_argument("--state", default="data/auto_trader_state.json")
    parser.add_argument("--min-trades", type=int, default=300)
    parser.add_argument("--min-expectancy", type=float, default=0.0, help="Percent per trade")
    parser.add_argument("--min-profit-factor", type=float, default=1.15)
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=25.0,
        help="Maximum allowed drawdown in percent of paper bankroll",
    )
    parser.add_argument("--paper-bankroll", type=float, default=250.0)
    parser.add_argument(
        "--min-cost-coverage",
        type=float,
        default=0.95,
        help="Minimum share [0,1] of closed trades that include cost telemetry",
    )
    parser.add_argument(
        "--holdout-windows",
        default="100,200",
        help="Comma-separated trailing windows that must have positive expectancy",
    )
    parser.add_argument(
        "--max-concentration-share",
        type=float,
        default=0.25,
        help="Maximum allowed share [0,1] of absolute PnL from a single ticker",
    )
    parser.add_argument("--json-out", help="Optional JSON file for machine-readable gate output")
    return parser.parse_args()


def parse_windows(raw: str):
    windows = []
    for chunk in str(raw).split(","):
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


def _safe_float(raw, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:
        return default
    return value


def main() -> None:
    args = parse_args()
    state_path = Path(args.state)
    if not state_path.exists():
        raise SystemExit(f"State file not found: {state_path}")

    payload = json.loads(state_path.read_text())
    closed_positions = payload.get("closed_positions", [])
    if not isinstance(closed_positions, list):
        closed_positions = []

    config = payload.get("config", {}) if isinstance(payload.get("config"), dict) else {}
    fee_per_contract_prob = _safe_float(
        config.get("fee_per_contract_prob", DEFAULT_FEE_PER_CONTRACT_PROB),
        DEFAULT_FEE_PER_CONTRACT_PROB,
    )
    slippage_spread_factor = _safe_float(
        config.get("slippage_spread_factor", DEFAULT_SLIPPAGE_SPREAD_FACTOR),
        DEFAULT_SLIPPAGE_SPREAD_FACTOR,
    )

    holdout_windows = parse_windows(args.holdout_windows)
    gate = evaluate_go_live_gates(
        closed_positions,
        paper_bankroll=float(args.paper_bankroll),
        min_trades=int(args.min_trades),
        min_expectancy=float(args.min_expectancy),
        min_profit_factor=float(args.min_profit_factor),
        max_drawdown=float(args.max_drawdown),
        min_cost_coverage=float(args.min_cost_coverage),
        holdout_windows=holdout_windows,
        max_concentration_share=float(args.max_concentration_share),
        fee_per_contract_prob=fee_per_contract_prob,
        slippage_spread_factor=slippage_spread_factor,
    )

    print("Go-Live Gate Check")
    print("-" * 72)
    for check in gate["checks"]:
        status = "PASS" if check["pass"] else "FAIL"
        name = check["name"]
        value = check["value"]
        threshold = check["threshold"]
        direction = check["direction"]
        if name == "trades":
            expr = f"{int(value)} {direction} {int(threshold)}"
        elif name == "max_drawdown_pct":
            expr = f"{value:.2f}% {direction} {threshold:.2f}%"
        elif name == "cost_coverage_ratio" or name == "max_ticker_concentration":
            expr = f"{value * 100:.2f}% {direction} {threshold * 100:.2f}%"
        elif name.startswith("holdout_expectancy_"):
            if isinstance(value, str):
                expr = f"insufficient trades for window ({direction} 0.0000%)"
            else:
                expr = f"{value:.4f}% {direction} 0.0000%"
        else:
            expr = f"{value:.4f} {direction} {threshold:.4f}"
        print(f"{status} | {name}: {expr}")

    concentration = gate["concentration"]
    max_ticker = concentration.get("max_ticker")
    if max_ticker:
        print(
            f"INFO | concentration leader: {max_ticker} "
            f"({float(concentration['max_share_of_abs_pnl']) * 100:.2f}% of abs PnL)"
        )
    print("-" * 72)

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(gate, indent=2))
        print(f"JSON output: {out_path}")

    if gate["go_live"]:
        print("STATUS: PASS (eligible for constrained live rollout)")
        raise SystemExit(0)

    print("STATUS: FAIL (stay in paper mode)")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
