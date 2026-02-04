import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ops.gate_metrics import evaluate_go_live_gates


def _make_closed_trade(
    *,
    ticker: str,
    pnl_cents: float,
    notional_cents: int = 100,
    entry_edge: float = 0.03,
    entry_cost_estimate: float = 0.012,
    entry_gross_edge: float = 0.042,
) -> dict:
    return {
        "ticker": ticker,
        "side": "yes",
        "count": 1,
        "entry_price_cents": 50,
        "exit_price_cents": 50 + int(pnl_cents),
        "notional_cents": notional_cents,
        "pnl_cents": pnl_cents,
        "pnl_pct": pnl_cents / max(notional_cents, 1),
        "entry_edge": entry_edge,
        "entry_gross_edge": entry_gross_edge,
        "entry_cost_estimate": entry_cost_estimate,
        "entry_fair_yes_probability": 0.6,
        "entry_win_probability": 0.6,
        "signal_confidence": 0.8,
        "opened_at": "2026-02-04T00:00:00+00:00",
        "closed_at": "2026-02-04T00:05:00+00:00",
        "exit_reason": "unit",
        "entry_source": "unit",
    }


class GateAndReportTests(unittest.TestCase):
    def _make_state(self, closed_positions: list[dict]) -> dict:
        return {
            "schema_version": 3,
            "current_day": "2026-02-04",
            "daily_trades": 0,
            "positions": [],
            "closed_positions": closed_positions,
            "total_exposure_cents": 0,
            "total_pnl_cents": sum(float(t["pnl_cents"]) for t in closed_positions),
            "paper_cash_cents": 25000,
            "config": {
                "fee_per_contract_prob": 0.008,
                "slippage_spread_factor": 0.35,
            },
        }

    def test_gate_pass_and_concentration_fail(self) -> None:
        diversified = []
        tickers = [f"KXTEST-{i}" for i in range(8)]
        for idx in range(320):
            ticker = tickers[idx % len(tickers)]
            pnl = 5.0 if idx % 5 != 0 else -2.0
            diversified.append(_make_closed_trade(ticker=ticker, pnl_cents=pnl))

        gate_pass = evaluate_go_live_gates(
            diversified,
            paper_bankroll=250.0,
            min_trades=300,
            min_expectancy=0.0,
            min_profit_factor=1.15,
            max_drawdown=25.0,
            min_cost_coverage=0.95,
            holdout_windows=[100, 200],
            max_concentration_share=0.25,
            fee_per_contract_prob=0.008,
            slippage_spread_factor=0.35,
        )
        self.assertTrue(gate_pass["go_live"])

        concentrated = []
        for idx in range(320):
            ticker = "KXDOMINANT" if idx < 250 else "KXOTHER"
            pnl = 6.0 if idx < 250 else -1.0
            concentrated.append(_make_closed_trade(ticker=ticker, pnl_cents=pnl))
        gate_fail = evaluate_go_live_gates(
            concentrated,
            paper_bankroll=250.0,
            min_trades=300,
            min_expectancy=0.0,
            min_profit_factor=1.15,
            max_drawdown=25.0,
            min_cost_coverage=0.95,
            holdout_windows=[100, 200],
            max_concentration_share=0.25,
            fee_per_contract_prob=0.008,
            slippage_spread_factor=0.35,
        )
        self.assertFalse(gate_fail["go_live"])
        conc_check = [c for c in gate_fail["checks"] if c["name"] == "max_ticker_concentration"][0]
        self.assertFalse(conc_check["pass"])

    def test_quant_report_emits_json_verdict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kalshi-quant-report-") as td:
            root = Path(td)
            closed = []
            tickers = [f"KXTEST-{i}" for i in range(8)]
            for idx in range(320):
                ticker = tickers[idx % len(tickers)]
                pnl = 4.0 if idx % 4 != 0 else -1.0
                closed.append(_make_closed_trade(ticker=ticker, pnl_cents=pnl))
            state = self._make_state(closed)
            state_path = root / "state.json"
            state_path.write_text(json.dumps(state))

            alpha_path = root / "alpha.json"
            alpha_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-02-04T00:00:00Z",
                        "signals": {
                            "KXTEST-0": {
                                "fair_yes_probability": 0.62,
                                "confidence": 0.78,
                                "source": "unit",
                            }
                        },
                    }
                )
            )

            report_md = root / "report.md"
            report_json = root / "report.json"
            history = root / "history.jsonl"
            cmd = [
                "python3",
                "ops/quant_pm_report.py",
                "--state",
                str(state_path),
                "--alpha",
                str(alpha_path),
                "--output",
                str(report_md),
                "--json-output",
                str(report_json),
                "--history-file",
                str(history),
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr or completed.stdout)
            payload = json.loads(report_json.read_text())
            self.assertEqual(payload["go_live"], True)
            self.assertEqual(payload["verdict"], "GO LIVE")


if __name__ == "__main__":
    unittest.main()
