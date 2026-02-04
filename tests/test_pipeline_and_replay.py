import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_empty_snapshots(path: Path, count: int = 5) -> None:
    rows = []
    for idx in range(count):
        rows.append(
            {
                "timestamp": f"2026-02-04T00:00:{idx:02d}Z",
                "sequence": idx + 1,
                "markets": [],
                "trades": {},
                "orderbooks": {},
            }
        )
    path.write_text(json.dumps(rows))


class PipelineAndReplayTests(unittest.TestCase):
    def test_replay_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kalshi-replay-det-") as td:
            root = Path(td)
            snapshots = root / "snapshots.json"
            state_a = root / "state_a.json"
            state_b = root / "state_b.json"
            _write_empty_snapshots(snapshots)

            cmd_a = [
                "python3",
                "ops/replay_trades_backtest.py",
                "--snapshot-file",
                str(snapshots),
                "--state-out",
                str(state_a),
            ]
            cmd_b = [
                "python3",
                "ops/replay_trades_backtest.py",
                "--snapshot-file",
                str(snapshots),
                "--state-out",
                str(state_b),
            ]
            res_a = subprocess.run(cmd_a, capture_output=True, text=True, check=False)
            res_b = subprocess.run(cmd_b, capture_output=True, text=True, check=False)
            self.assertEqual(res_a.returncode, 0, msg=res_a.stderr or res_a.stdout)
            self.assertEqual(res_b.returncode, 0, msg=res_b.stderr or res_b.stdout)

            a = json.loads(state_a.read_text())
            b = json.loads(state_b.read_text())
            self.assertEqual(a["performance"], b["performance"])
            self.assertEqual(len(a.get("closed_positions", [])), len(b.get("closed_positions", [])))

    def test_pipeline_halts_on_gate_fail_and_can_pass_with_relaxed_thresholds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kalshi-pipeline-") as td:
            root = Path(td)
            snapshots = root / "snapshots.json"
            _write_empty_snapshots(snapshots)

            fail_state = root / "state_fail.json"
            fail_report = root / "report_fail.md"
            fail_report_json = root / "report_fail.json"
            fail_cmd = [
                "python3",
                "ops/run_quant_pipeline.py",
                "--alpha-source",
                "csv",
                "--input",
                "data/alpha_signals_input_example.csv",
                "--paper-mode",
                "replay",
                "--snapshot-file",
                str(snapshots),
                "--paper-state",
                str(fail_state),
                "--quant-report-out",
                str(fail_report),
                "--quant-json-out",
                str(fail_report_json),
                "--emit-json-report",
            ]
            fail_run = subprocess.run(fail_cmd, capture_output=True, text=True, check=False)
            self.assertNotEqual(fail_run.returncode, 0)
            self.assertTrue(fail_report.exists())
            self.assertTrue(fail_report_json.exists())

            pass_state = root / "state_pass.json"
            pass_report = root / "report_pass.md"
            pass_report_json = root / "report_pass.json"
            pass_cmd = [
                "python3",
                "ops/run_quant_pipeline.py",
                "--alpha-source",
                "csv",
                "--input",
                "data/alpha_signals_input_example.csv",
                "--paper-mode",
                "replay",
                "--snapshot-file",
                str(snapshots),
                "--paper-state",
                str(pass_state),
                "--quant-report-out",
                str(pass_report),
                "--quant-json-out",
                str(pass_report_json),
                "--emit-json-report",
                "--gate-min-trades",
                "0",
                "--gate-min-expectancy",
                "-100.0",
                "--gate-min-profit-factor",
                "0.0",
                "--gate-max-drawdown",
                "100.0",
                "--gate-min-cost-coverage",
                "0.0",
                "--gate-holdout-windows",
                "",
                "--gate-max-concentration-share",
                "1.0",
            ]
            pass_run = subprocess.run(pass_cmd, capture_output=True, text=True, check=False)
            self.assertEqual(pass_run.returncode, 0, msg=pass_run.stderr or pass_run.stdout)
            payload = json.loads(pass_report_json.read_text())
            self.assertTrue(payload["go_live"])


if __name__ == "__main__":
    unittest.main()
