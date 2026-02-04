#!/usr/bin/env python3
"""
Grid-search replay parameters on deterministic trades snapshots.

Ranking objective (holdout, in order):
1) expectancy
2) profit factor
3) drawdown (lower is better)
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from automation.auto_trader import TraderConfig
from core.trading import compute_performance_metrics
from ops.replay_trades_backtest import (
    SnapshotReplayTrader,
    build_snapshot_signals,
    load_snapshots,
)


@dataclass(frozen=True)
class ReplayParams:
    min_net_edge: float
    max_spread: float
    min_confidence: float
    slippage_factor: float
    fee_per_contract: float
    take_profit: float
    stop_loss: float
    max_holding_minutes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep replay parameters on snapshot data")
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--out", help="Output JSON path (default data/replay_sweeps/<timestamp>.json)")
    parser.add_argument("--top-n", type=int, default=20, help="Number of ranked runs to persist")
    parser.add_argument("--max-runs", type=int, default=300, help="Cap total grid combinations evaluated")

    parser.add_argument("--paper-bankroll", type=float, default=250.0)
    parser.add_argument("--max-position", type=float, default=20.0)
    parser.add_argument("--min-position", type=float, default=5.0)
    parser.add_argument("--max-exposure", type=float, default=150.0)
    parser.add_argument("--min-volume", type=float, default=500.0)
    parser.add_argument("--kelly-fraction", type=float, default=0.25)

    parser.add_argument("--holdout-ratio", type=float, default=0.30)
    parser.add_argument("--min-holdout", type=int, default=50)

    parser.add_argument("--min-net-edge-grid", default="0.01,0.015,0.02")
    parser.add_argument("--max-spread-grid", default="0.05,0.06,0.08")
    parser.add_argument("--min-confidence-grid", default="0.55,0.60,0.65")
    parser.add_argument("--slippage-factor-grid", default="0.25,0.35,0.45")
    parser.add_argument("--fee-per-contract-grid", default="0.006,0.008,0.01")
    parser.add_argument("--take-profit-grid", default="0.15,0.20,0.25")
    parser.add_argument("--stop-loss-grid", default="0.10,0.12,0.15")
    parser.add_argument("--max-holding-grid", default="120,240,360")
    return parser.parse_args()


def _parse_float_grid(raw: str) -> List[float]:
    values = []
    for chunk in str(raw).split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.append(float(text))
        except ValueError:
            continue
    deduped = sorted(set(values))
    if not deduped:
        raise SystemExit(f"Invalid grid: {raw}")
    return deduped


def _parse_int_grid(raw: str) -> List[int]:
    values = []
    for chunk in str(raw).split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.append(int(text))
        except ValueError:
            continue
    deduped = sorted(set(v for v in values if v > 0))
    if not deduped:
        raise SystemExit(f"Invalid grid: {raw}")
    return deduped


def _split_train_holdout(
    snapshots: Sequence[Dict[str, Any]],
    holdout_ratio: float,
    min_holdout: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if len(snapshots) < 3:
        raise SystemExit("Need at least 3 snapshots for train/holdout split.")
    holdout_count = int(round(len(snapshots) * holdout_ratio))
    holdout_count = max(int(min_holdout), holdout_count)
    holdout_count = min(holdout_count, len(snapshots) - 1)
    train = list(snapshots[:-holdout_count])
    holdout = list(snapshots[-holdout_count:])
    if not train or not holdout:
        raise SystemExit("Invalid split; train/holdout must both be non-empty.")
    return train, holdout


def _build_trader_config(
    state_file: Path,
    args: argparse.Namespace,
    params: ReplayParams,
) -> TraderConfig:
    return TraderConfig(
        env="prod",
        enabled=True,
        paper_mode=True,
        paper_bankroll_usd=args.paper_bankroll,
        max_position_usd=args.max_position,
        min_position_usd=args.min_position,
        max_daily_trades=1000000,
        max_total_exposure_usd=args.max_exposure,
        min_signal_confidence=params.min_confidence,
        min_edge=0.03,
        min_net_edge=params.min_net_edge,
        max_spread=params.max_spread,
        min_volume=args.min_volume,
        fee_per_contract_prob=params.fee_per_contract,
        slippage_spread_factor=params.slippage_factor,
        kelly_fraction=args.kelly_fraction,
        take_profit_pct=params.take_profit,
        stop_loss_pct=params.stop_loss,
        max_holding_minutes=params.max_holding_minutes,
        scan_interval_seconds=0,
        markets_limit=500,
        state_file=str(state_file),
        alpha_file="data/alpha_signals.json",
    )


def _run_replay(
    snapshots: Sequence[Dict[str, Any]],
    args: argparse.Namespace,
    params: ReplayParams,
    state_file: Path,
) -> Dict[str, Any]:
    if state_file.exists():
        state_file.unlink()
    trader = SnapshotReplayTrader(_build_trader_config(state_file=state_file, args=args, params=params))
    for snapshot in snapshots:
        trader.current_markets = list(snapshot.get("markets", []))
        signals = build_snapshot_signals(snapshot, min_confidence=params.min_confidence)
        if signals:
            trader.check_exits(signals)
            candidates = trader._scan_candidates(signals)
            if candidates:
                trader._open_position(candidates[0])
    trader.save_state()
    metrics = compute_performance_metrics(trader.closed_positions)
    drawdown_pct = (
        float(metrics["max_drawdown_cents"]) / max(args.paper_bankroll * 100.0, 1.0) * 100.0
    )
    return {
        "metrics": metrics,
        "drawdown_pct": drawdown_pct,
        "state_file": str(state_file),
        "trade_count": int(metrics["trades"]),
    }


def _score_key(run: Dict[str, Any]) -> tuple[float, float, float]:
    holdout = run["holdout"]
    return (
        float(holdout["metrics"]["expectancy_pct"]),
        float(holdout["metrics"]["profit_factor"]),
        -float(holdout["drawdown_pct"]),
    )


def _iter_grid(args: argparse.Namespace) -> Iterable[ReplayParams]:
    grids = itertools.product(
        _parse_float_grid(args.min_net_edge_grid),
        _parse_float_grid(args.max_spread_grid),
        _parse_float_grid(args.min_confidence_grid),
        _parse_float_grid(args.slippage_factor_grid),
        _parse_float_grid(args.fee_per_contract_grid),
        _parse_float_grid(args.take_profit_grid),
        _parse_float_grid(args.stop_loss_grid),
        _parse_int_grid(args.max_holding_grid),
    )
    for combo in grids:
        yield ReplayParams(
            min_net_edge=float(combo[0]),
            max_spread=float(combo[1]),
            min_confidence=float(combo[2]),
            slippage_factor=float(combo[3]),
            fee_per_contract=float(combo[4]),
            take_profit=float(combo[5]),
            stop_loss=float(combo[6]),
            max_holding_minutes=int(combo[7]),
        )


def _default_out_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("data/replay_sweeps") / f"{timestamp}.json"


def main() -> None:
    args = parse_args()
    snapshots = load_snapshots(Path(args.snapshot_file))
    train_snapshots, holdout_snapshots = _split_train_holdout(
        snapshots=snapshots,
        holdout_ratio=float(args.holdout_ratio),
        min_holdout=int(args.min_holdout),
    )

    out_path = Path(args.out) if args.out else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_dir = out_path.parent / f"{out_path.stem}_runs"
    run_dir.mkdir(parents=True, exist_ok=True)

    all_runs: List[Dict[str, Any]] = []
    max_runs = max(1, int(args.max_runs))
    for idx, params in enumerate(_iter_grid(args), start=1):
        if idx > max_runs:
            break

        train_state = run_dir / f"run_{idx:04d}_train_state.json"
        holdout_state = run_dir / f"run_{idx:04d}_holdout_state.json"
        train = _run_replay(train_snapshots, args=args, params=params, state_file=train_state)
        holdout = _run_replay(holdout_snapshots, args=args, params=params, state_file=holdout_state)

        run = {
            "run_id": idx,
            "params": asdict(params),
            "train": train,
            "holdout": holdout,
        }
        all_runs.append(run)
        print(
            f"[{idx}/{max_runs}] holdout expectancy={holdout['metrics']['expectancy_pct']:+.4f}% "
            f"pf={holdout['metrics']['profit_factor']:.4f} dd={holdout['drawdown_pct']:.2f}%"
        )

    if not all_runs:
        raise SystemExit("No runs executed.")

    ranked = sorted(all_runs, key=_score_key, reverse=True)
    top_n = max(1, int(args.top_n))
    top_runs = ranked[:top_n]
    best_run = ranked[0]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_file": str(Path(args.snapshot_file)),
        "train_snapshots": len(train_snapshots),
        "holdout_snapshots": len(holdout_snapshots),
        "total_runs": len(all_runs),
        "ranking_objective": ["holdout_expectancy_pct", "holdout_profit_factor", "holdout_drawdown_pct_asc"],
        "best_run": best_run,
        "top_runs": top_runs,
    }
    out_path.write_text(json.dumps(payload, indent=2))

    best = best_run["holdout"]["metrics"]
    print("\nSweep complete")
    print(f"Output: {out_path}")
    print(
        "Best holdout metrics: "
        f"expectancy={best['expectancy_pct']:+.4f}% "
        f"pf={best['profit_factor']:.4f} "
        f"trades={int(best['trades'])} "
        f"pnl=${best['total_pnl_cents'] / 100:+.2f}"
    )


if __name__ == "__main__":
    main()
