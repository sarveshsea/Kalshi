#!/usr/bin/env python3
"""
Fit a probability calibration map from replay outcomes.

Input is sweep output from ops/sweep_replay_params.py and the best run's
holdout state file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.trading import (
    AlphaSignal,
    apply_probability_calibration,
    load_alpha_signals,
    to_probability,
    write_alpha_signals,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate fair probabilities from replay outcomes")
    parser.add_argument("--replay-results", required=True, help="Output JSON from sweep_replay_params.py")
    parser.add_argument("--out", default="data/alpha_calibration.json")
    parser.add_argument("--run-id", type=int, help="Specific run id from sweep results (defaults to best run)")
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--min-points-per-bin", type=int, default=5)
    parser.add_argument("--alpha-in", help="Optional alpha_signals.json to calibrate")
    parser.add_argument("--alpha-out", help="Output path for calibrated alpha_signals.json")
    return parser.parse_args()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def _find_run(payload: Dict[str, Any], run_id: Optional[int]) -> Dict[str, Any]:
    if run_id is None:
        best = payload.get("best_run")
        if isinstance(best, dict):
            return best
        raise SystemExit("Replay results missing best_run.")

    for run in payload.get("top_runs", []):
        if int(run.get("run_id", -1)) == int(run_id):
            return run
    raise SystemExit(f"Run id {run_id} not found in top_runs.")


def _trade_points_from_state(state_path: Path) -> List[Dict[str, float]]:
    if not state_path.exists():
        raise SystemExit(f"Holdout state file not found: {state_path}")
    payload = _load_json(state_path)
    closed = payload.get("closed_positions", [])
    if not isinstance(closed, list):
        closed = []

    points: List[Dict[str, float]] = []
    for trade in closed:
        if not isinstance(trade, dict):
            continue
        pred = to_probability(trade.get("entry_win_probability"))
        if pred is None:
            fair_yes = to_probability(trade.get("entry_fair_yes_probability"))
            side = str(trade.get("side", "")).lower().strip()
            if fair_yes is None or side not in {"yes", "no"}:
                continue
            pred = fair_yes if side == "yes" else (1.0 - fair_yes)
        pnl = float(trade.get("pnl_cents", trade.get("pnl", 0.0)) or 0.0)
        outcome = 1.0 if pnl > 0 else 0.0
        points.append(
            {
                "predicted_probability": float(pred),
                "outcome": outcome,
            }
        )
    return points


def _enforce_monotonic(rows: List[Dict[str, float]]) -> List[Dict[str, float]]:
    if not rows:
        return rows
    adjusted: List[Dict[str, float]] = []
    running = 0.0
    for idx, row in enumerate(rows):
        value = float(row["calibrated_probability"])
        if idx == 0:
            running = value
        else:
            running = max(running, value)
        adjusted.append(
            {
                "raw_probability": float(row["raw_probability"]),
                "calibrated_probability": float(min(1.0, running)),
                "count": int(row["count"]),
                "observed_win_rate": float(row["observed_win_rate"]),
            }
        )
    return adjusted


def _fit_bins(
    points: List[Dict[str, float]],
    bins: int,
    min_points_per_bin: int,
) -> List[Dict[str, float]]:
    bins = max(2, int(bins))
    if not points:
        raise SystemExit("No calibration points found in holdout state.")

    rows: List[Dict[str, float]] = []
    for idx in range(bins):
        lo = idx / bins
        hi = (idx + 1) / bins
        bucket = [
            point
            for point in points
            if (point["predicted_probability"] >= lo and point["predicted_probability"] < hi)
        ]
        if idx == bins - 1:
            bucket.extend(
                [point for point in points if point["predicted_probability"] == 1.0]
            )
        if len(bucket) < min_points_per_bin:
            continue
        raw_mean = sum(p["predicted_probability"] for p in bucket) / len(bucket)
        win_rate = sum(p["outcome"] for p in bucket) / len(bucket)
        rows.append(
            {
                "raw_probability": raw_mean,
                "calibrated_probability": win_rate,
                "count": len(bucket),
                "observed_win_rate": win_rate,
            }
        )

    if not rows:
        raise SystemExit(
            "Not enough points per bin to fit calibration. "
            "Reduce --min-points-per-bin or increase replay sample."
        )

    rows.sort(key=lambda row: row["raw_probability"])
    return _enforce_monotonic(rows)


def _apply_calibration_to_alpha(
    alpha_in: Path,
    alpha_out: Path,
    bins: List[Dict[str, float]],
) -> int:
    signals = load_alpha_signals(alpha_in)
    if not signals:
        raise SystemExit(f"No alpha signals found in {alpha_in}")
    mapping = [
        (float(row["raw_probability"]), float(row["calibrated_probability"]))
        for row in bins
    ]
    calibrated: Dict[str, AlphaSignal] = {}
    for ticker, signal in signals.items():
        cal_prob = apply_probability_calibration(signal.fair_yes_probability, mapping)
        calibrated[ticker] = AlphaSignal(
            fair_yes_probability=cal_prob,
            confidence=signal.confidence,
            source=signal.source,
            model_version=signal.model_version,
            horizon_minutes=signal.horizon_minutes,
            expected_edge_net=signal.expected_edge_net,
            generated_at=signal.generated_at,
        )
    write_alpha_signals(
        alpha_out,
        calibrated,
        metadata={
            "calibrated_from": str(alpha_in),
            "calibration_timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    return len(calibrated)


def main() -> None:
    args = parse_args()
    replay_results_path = Path(args.replay_results)
    if not replay_results_path.exists():
        raise SystemExit(f"Replay results not found: {replay_results_path}")
    payload = _load_json(replay_results_path)
    run = _find_run(payload, args.run_id)

    holdout_state_raw = ((run.get("holdout") or {}).get("state_file"))
    if not holdout_state_raw:
        raise SystemExit("Selected run missing holdout.state_file.")

    points = _trade_points_from_state(Path(str(holdout_state_raw)))
    bins = _fit_bins(
        points=points,
        bins=int(args.bins),
        min_points_per_bin=int(args.min_points_per_bin),
    )

    calibration_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "replay_results": str(replay_results_path),
        "run_id": int(run.get("run_id", 0)),
        "points_used": len(points),
        "bins": bins,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(calibration_payload, indent=2))
    print(f"Calibration file written: {out_path}")
    print(f"Bins: {len(bins)} | points: {len(points)}")

    if args.alpha_in or args.alpha_out:
        if not args.alpha_in or not args.alpha_out:
            raise SystemExit("Provide both --alpha-in and --alpha-out to emit calibrated alpha signals.")
        count = _apply_calibration_to_alpha(
            alpha_in=Path(args.alpha_in),
            alpha_out=Path(args.alpha_out),
            bins=bins,
        )
        print(f"Calibrated alpha written: {args.alpha_out} ({count} signals)")


if __name__ == "__main__":
    main()
