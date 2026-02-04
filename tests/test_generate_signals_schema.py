import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class GenerateSignalsSchemaTests(unittest.TestCase):
    def test_generate_signals_requires_schema_and_writes_required_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kalshi-gen-signals-") as td:
            root = Path(td)
            valid_csv = root / "valid.csv"
            with valid_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "ticker",
                        "fair_yes_probability",
                        "confidence",
                        "source",
                        "model_version",
                        "horizon_minutes",
                        "expected_edge_net",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "ticker": "KXTEST-1",
                        "fair_yes_probability": "0.61",
                        "confidence": "0.77",
                        "source": "unit",
                        "model_version": "v1",
                        "horizon_minutes": "60",
                        "expected_edge_net": "0.02",
                    }
                )

            output_csv = root / "signals.csv"
            tg = root / "tg.txt"
            alpha = root / "alpha.json"
            cmd = [
                "python3",
                "kalshi_signal_pack/generate_signals.py",
                "--input",
                str(valid_csv),
                "--top_k",
                "5",
                "--output",
                str(output_csv),
                "--tg",
                str(tg),
                "--bankroll",
                "100",
                "--alpha",
                str(alpha),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)

            payload = json.loads(alpha.read_text())
            self.assertIn("signals", payload)
            row = payload["signals"]["KXTEST-1"]
            self.assertIn("fair_yes_probability", row)
            self.assertIn("confidence", row)
            self.assertIn("source", row)
            self.assertEqual(row["model_version"], "v1")

    def test_generate_signals_fails_when_required_columns_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kalshi-gen-signals-missing-") as td:
            root = Path(td)
            bad_csv = root / "bad.csv"
            with bad_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=["ticker", "confidence", "source"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "ticker": "KXTEST-1",
                        "confidence": "0.77",
                        "source": "unit",
                    }
                )

            cmd = [
                "python3",
                "kalshi_signal_pack/generate_signals.py",
                "--input",
                str(bad_csv),
                "--top_k",
                "5",
                "--output",
                str(root / "signals.csv"),
                "--tg",
                str(root / "tg.txt"),
                "--bankroll",
                "100",
                "--alpha",
                str(root / "alpha.json"),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("missing required column", (completed.stderr + completed.stdout).lower())


if __name__ == "__main__":
    unittest.main()
