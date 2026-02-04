#!/usr/bin/env python3
"""
Report performance metrics from auto_trader_state.json.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.trading import compute_performance_metrics


def main() -> None:
    state_file = Path("data/auto_trader_state.json")
    if not state_file.exists():
        print("State file not found: data/auto_trader_state.json")
        return

    try:
        state = json.loads(state_file.read_text())
    except json.JSONDecodeError as exc:
        print(f"Failed to parse state file: {exc}")
        return

    positions = state.get("positions", [])
    closed_positions = state.get("closed_positions", [])
    metrics = compute_performance_metrics(closed_positions)

    print("Auto-Trader Performance")
    print("-" * 60)
    print(f"Open positions: {len(positions)}")
    print(f"Closed trades: {int(metrics['trades'])}")
    print(f"Wins/Losses: {int(metrics['wins'])}/{int(metrics['losses'])}")
    print(f"Win rate: {metrics['win_rate'] * 100:.2f}%")
    print(f"Total PnL: ${metrics['total_pnl_cents'] / 100:+.2f}")
    print(f"Expectancy: {metrics['expectancy_pct']:.2f}% per trade")
    print(f"Profit factor: {metrics['profit_factor']:.2f}")
    print(f"Max drawdown: ${metrics['max_drawdown_cents'] / 100:.2f}")
    print(f"Avg holding time: {metrics['avg_holding_minutes']:.1f} min")


if __name__ == "__main__":
    main()
