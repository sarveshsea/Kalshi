#!/usr/bin/env python3
"""
Orchestration command:
build alpha -> run paper -> gate check -> quant report -> optional live deploy.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import List


def run_command(
    cmd: List[str],
    *,
    cwd: Path,
    stdin_text: str | None = None,
    check: bool = True,
) -> int:
    print(f"$ {' '.join(cmd)}")
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        check=check,
    )
    return int(completed.returncode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run end-to-end quant pipeline")
    parser.add_argument("--alpha-source", choices=["csv", "flow"], default="flow")
    parser.add_argument("--input", help="CSV input when --alpha-source=csv")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--bankroll", type=float, default=100.0)
    parser.add_argument("--calibration-file", help="Optional calibration file for flow alpha")

    parser.add_argument("--paper-mode", choices=["replay", "run-once"], default="run-once")
    parser.add_argument("--snapshot-file", help="Required for replay mode")
    parser.add_argument("--paper-state", default="data/auto_trader_state.json")
    parser.add_argument("--paper-bankroll", type=float, default=250.0)

    parser.add_argument("--quant-report-out", default="data/quant_pm_report.md")
    parser.add_argument("--quant-json-out", default="data/quant_pm_report.json")
    parser.add_argument("--emit-json-report", action="store_true")

    parser.add_argument("--gate-min-trades", type=int, default=300)
    parser.add_argument("--gate-min-expectancy", type=float, default=0.0)
    parser.add_argument("--gate-min-profit-factor", type=float, default=1.15)
    parser.add_argument("--gate-max-drawdown", type=float, default=25.0)
    parser.add_argument("--gate-min-cost-coverage", type=float, default=0.95)
    parser.add_argument("--gate-holdout-windows", default="100,200")
    parser.add_argument("--gate-max-concentration-share", type=float, default=0.25)

    parser.add_argument("--deploy-live", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent

    # Step 1: Build alpha signals.
    if args.alpha_source == "csv":
        if not args.input:
            raise SystemExit("--input is required when --alpha-source=csv")
        run_command(
            [
                sys.executable,
                "kalshi_signal_pack/generate_signals.py",
                "--input",
                args.input,
                "--top_k",
                str(args.top_k),
                "--output",
                "/tmp/signals.csv",
                "--tg",
                "/tmp/telegram_message.txt",
                "--bankroll",
                str(args.bankroll),
                "--alpha",
                "data/alpha_signals.json",
            ],
            cwd=root,
        )
    else:
        flow_cmd = [
            sys.executable,
            "ops/build_flow_alpha.py",
            "--top-k",
            str(args.top_k),
            "--alpha-out",
            "data/alpha_signals.json",
            "--csv-out",
            "data/flow_signals_latest.csv",
        ]
        if args.calibration_file:
            flow_cmd.extend(["--calibration", args.calibration_file])
        run_command(
            flow_cmd,
            cwd=root,
        )

    # Step 2: Paper trial.
    if args.paper_mode == "replay":
        if not args.snapshot_file:
            raise SystemExit("--snapshot-file is required when --paper-mode=replay")
        run_command(
            [
                sys.executable,
                "ops/replay_trades_backtest.py",
                "--snapshot-file",
                args.snapshot_file,
                "--state-out",
                args.paper_state,
                "--paper-bankroll",
                str(args.paper_bankroll),
            ],
            cwd=root,
        )
    else:
        run_command(
            [
                sys.executable,
                "automation/auto_trader.py",
                "--run-once",
                "--state-file",
                args.paper_state,
                "--alpha-file",
                "data/alpha_signals.json",
                "--paper-bankroll",
                str(args.paper_bankroll),
            ],
            cwd=root,
        )

    # Step 3: Gate check.
    gate_json_path = "data/go_live_gate.json"
    gate_rc = run_command(
        [
            sys.executable,
            "ops/check_go_live_gate.py",
            "--state",
            args.paper_state,
            "--paper-bankroll",
            str(args.paper_bankroll),
            "--min-trades",
            str(args.gate_min_trades),
            "--min-expectancy",
            str(args.gate_min_expectancy),
            "--min-profit-factor",
            str(args.gate_min_profit_factor),
            "--max-drawdown",
            str(args.gate_max_drawdown),
            "--min-cost-coverage",
            str(args.gate_min_cost_coverage),
            "--holdout-windows",
            str(args.gate_holdout_windows),
            "--max-concentration-share",
            str(args.gate_max_concentration_share),
            "--json-out",
            gate_json_path,
        ],
        cwd=root,
        check=False,
    )

    # Step 4: Quant PM report (always emit after gate check).
    report_cmd = [
        sys.executable,
        "ops/quant_pm_report.py",
        "--state",
        args.paper_state,
        "--alpha",
        "data/alpha_signals.json",
        "--output",
        args.quant_report_out,
        "--paper-bankroll",
        str(args.paper_bankroll),
        "--min-trades",
        str(args.gate_min_trades),
        "--min-expectancy",
        str(args.gate_min_expectancy),
        "--min-profit-factor",
        str(args.gate_min_profit_factor),
        "--max-drawdown",
        str(args.gate_max_drawdown),
        "--min-cost-coverage",
        str(args.gate_min_cost_coverage),
        "--holdout-windows",
        str(args.gate_holdout_windows),
        "--max-concentration-share",
        str(args.gate_max_concentration_share),
    ]
    if args.emit_json_report:
        report_cmd.extend(["--json-output", args.quant_json_out])
    run_command(report_cmd, cwd=root)

    print("Artifacts")
    print(f"- alpha: {root / 'data/alpha_signals.json'}")
    print(f"- paper_state: {root / args.paper_state}")
    print(f"- gate_json: {root / gate_json_path}")
    print(f"- quant_report: {root / args.quant_report_out}")
    if args.emit_json_report:
        print(f"- quant_report_json: {root / args.quant_json_out}")

    if gate_rc != 0:
        print("Pipeline halted: go-live gate failed (paper mode only).")
        raise SystemExit(gate_rc)

    # Step 5: Optional deploy.
    if args.deploy_live:
        deploy_cmd = ["bash", "deploy_auto_trader.sh", "live"]
        run_command(deploy_cmd, cwd=root, stdin_text="yes\n")
    else:
        print("Pipeline finished. Live deploy not requested.")


if __name__ == "__main__":
    main()
