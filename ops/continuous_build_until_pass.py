#!/usr/bin/env python3
"""
Continuously run the paper-only quant build loop until gates pass.

Loop per iteration:
1) capture snapshot batch (optional)
2) sweep replay parameters
3) calibrate alpha
4) run quant pipeline (paper + report)
5) check gate status and continue until required consecutive passes
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import time
from typing import List
import json


def run_command(
    cmd: List[str],
    *,
    cwd: Path,
    check: bool = True,
) -> int:
    print(f"$ {' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=str(cwd), check=check)
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Continuously build quant pipeline until gate passes")
    parser.add_argument("--env", default="prod", choices=["demo", "prod"])
    parser.add_argument("--snapshot-file", default="data/trades_snapshots.jsonl")
    parser.add_argument("--skip-capture", action="store_true")

    parser.add_argument("--capture-cycles", type=int, default=30)
    parser.add_argument("--capture-interval-seconds", type=int, default=30)
    parser.add_argument("--capture-markets-limit", type=int, default=200)
    parser.add_argument("--capture-top-markets", type=int, default=30)
    parser.add_argument("--capture-min-volume", type=float, default=2500.0)
    parser.add_argument("--capture-trade-limit", type=int, default=120)

    parser.add_argument("--sweep-max-runs", type=int, default=200)
    parser.add_argument("--sweep-top-n", type=int, default=20)

    parser.add_argument("--paper-state", default="data/auto_trader_state.json")
    parser.add_argument("--paper-bankroll", type=float, default=250.0)
    parser.add_argument("--alpha-source", choices=["flow", "csv"], default="flow")
    parser.add_argument("--alpha-input", help="Required when --alpha-source=csv")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--bankroll", type=float, default=100.0)

    parser.add_argument("--required-consecutive-pass", type=int, default=2)
    parser.add_argument("--max-iterations", type=int, default=1000)
    parser.add_argument("--sleep-seconds-between-iterations", type=int, default=60)
    parser.add_argument("--deploy-live-on-pass", action="store_true")
    return parser.parse_args()


def _load_json(path: Path):
    return json.loads(path.read_text())


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _summary_line(gate_json: Path) -> str:
    if not gate_json.exists():
        return "gate_json_missing"
    try:
        payload = _load_json(gate_json)
    except Exception:
        return "gate_json_parse_error"
    go_live = bool(payload.get("go_live"))
    metrics = payload.get("metrics", {})
    trades = int(metrics.get("trades", 0) or 0)
    expectancy = float(metrics.get("expectancy_pct", 0.0) or 0.0)
    pf = float(metrics.get("profit_factor", 0.0) or 0.0)
    return (
        f"go_live={go_live} trades={trades} "
        f"expectancy={expectancy:+.4f}% pf={pf:.4f}"
    )


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    snapshot_file = Path(args.snapshot_file)
    if not snapshot_file.is_absolute():
        snapshot_file = root / snapshot_file
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)

    if args.alpha_source == "csv" and not args.alpha_input:
        raise SystemExit("--alpha-input is required when --alpha-source=csv")

    consecutive_pass = 0
    required = max(1, int(args.required_consecutive_pass))
    max_iterations = max(1, int(args.max_iterations))

    print("=" * 78)
    print("CONTINUOUS QUANT BUILD LOOP (paper-only by default)")
    print("=" * 78)
    print(f"snapshot_file: {snapshot_file}")
    print(f"required_consecutive_pass: {required}")
    print(f"max_iterations: {max_iterations}")
    print("=" * 78)

    for iteration in range(1, max_iterations + 1):
        stamp = _timestamp()
        print(f"\n--- Iteration {iteration}/{max_iterations} @ {stamp} ---")

        # 1) Capture snapshots (optional).
        if not args.skip_capture:
            run_command(
                [
                    sys.executable,
                    "ops/capture_trades_snapshots.py",
                    "--env",
                    args.env,
                    "--cycles",
                    str(args.capture_cycles),
                    "--interval-seconds",
                    str(args.capture_interval_seconds),
                    "--markets-limit",
                    str(args.capture_markets_limit),
                    "--top-markets",
                    str(args.capture_top_markets),
                    "--min-volume",
                    str(args.capture_min_volume),
                    "--trade-limit",
                    str(args.capture_trade_limit),
                    "--out",
                    str(snapshot_file),
                ],
                cwd=root,
            )
        elif not snapshot_file.exists():
            raise SystemExit(
                f"--skip-capture was set but snapshot file does not exist: {snapshot_file}"
            )

        # 2) Sweep replay params.
        sweep_out = root / "data" / "replay_sweeps" / f"{stamp}_iter{iteration:04d}.json"
        run_command(
            [
                sys.executable,
                "ops/sweep_replay_params.py",
                "--snapshot-file",
                str(snapshot_file),
                "--out",
                str(sweep_out),
                "--top-n",
                str(args.sweep_top_n),
                "--max-runs",
                str(args.sweep_max_runs),
                "--paper-bankroll",
                str(args.paper_bankroll),
            ],
            cwd=root,
        )

        # 3) Calibrate alpha.
        calibration_path = root / "data" / "alpha_calibration.json"
        calib_rc = run_command(
            [
                sys.executable,
                "ops/calibrate_alpha.py",
                "--replay-results",
                str(sweep_out),
                "--out",
                str(calibration_path),
            ],
            cwd=root,
            check=False,
        )
        calibration_available = calib_rc == 0 and calibration_path.exists()
        if calibration_available:
            print(f"Calibration ready: {calibration_path}")
        else:
            print("Calibration unavailable for this iteration; continuing with uncalibrated flow.")

        # 4) Run quant pipeline (paper + report).
        report_md = root / "data" / "quant_pm_report.md"
        report_json = root / "data" / "quant_pm_report.json"
        pipeline_cmd = [
            sys.executable,
            "ops/run_quant_pipeline.py",
            "--alpha-source",
            args.alpha_source,
            "--top-k",
            str(args.top_k),
            "--bankroll",
            str(args.bankroll),
            "--paper-mode",
            "replay",
            "--snapshot-file",
            str(snapshot_file),
            "--paper-state",
            args.paper_state,
            "--paper-bankroll",
            str(args.paper_bankroll),
            "--quant-report-out",
            str(report_md),
            "--quant-json-out",
            str(report_json),
            "--emit-json-report",
        ]
        if calibration_available:
            pipeline_cmd.extend(["--calibration-file", str(calibration_path)])
        if args.alpha_source == "csv":
            pipeline_cmd.extend(["--input", str(args.alpha_input)])

        pipeline_rc = run_command(pipeline_cmd, cwd=root, check=False)

        gate_json = root / "data" / "go_live_gate.json"
        summary = _summary_line(gate_json)
        print(f"Iteration summary: {summary}")

        go_live = False
        if gate_json.exists():
            try:
                go_live = bool(_load_json(gate_json).get("go_live"))
            except Exception:
                go_live = False

        if go_live and pipeline_rc == 0:
            consecutive_pass += 1
            print(f"Gate PASS streak: {consecutive_pass}/{required}")
        else:
            consecutive_pass = 0
            print("Gate PASS streak reset to 0")

        if consecutive_pass >= required:
            print("\n✅ Required consecutive gate passes reached.")
            if args.deploy_live_on_pass:
                print("Deploying live trader because --deploy-live-on-pass was set...")
                deploy = subprocess.run(
                    ["bash", "deploy_auto_trader.sh", "live"],
                    cwd=str(root),
                    text=True,
                    input="yes\n",
                    check=False,
                )
                if deploy.returncode != 0:
                    raise SystemExit("Live deploy attempted but failed.")
            else:
                print("Live deploy not requested. Staying in paper mode.")
            return

        if iteration < max_iterations:
            sleep_for = max(0, int(args.sleep_seconds_between_iterations))
            if sleep_for > 0:
                print(f"Sleeping {sleep_for}s before next iteration...")
                time.sleep(sleep_for)

    raise SystemExit(
        f"Reached max iterations ({max_iterations}) without {required} consecutive gate passes."
    )


if __name__ == "__main__":
    main()
