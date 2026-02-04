import tempfile
import unittest
from pathlib import Path

from automation.auto_trader import KalshiAutoTrader, TraderConfig
from core.trading import AlphaSignal, MarketQuote


class AutoTraderEdgeTests(unittest.TestCase):
    def _make_trader(self, *, min_net_edge: float) -> KalshiAutoTrader:
        temp_dir = Path(tempfile.mkdtemp(prefix="kalshi-autotrader-test-"))
        config = TraderConfig(
            paper_mode=True,
            enabled=False,
            state_file=str(temp_dir / "state.json"),
            alpha_file=str(temp_dir / "alpha.json"),
            min_edge=0.03,
            min_net_edge=min_net_edge,
            max_spread=0.10,
            min_volume=100.0,
            min_signal_confidence=0.60,
            fee_per_contract_prob=0.008,
            slippage_spread_factor=0.35,
        )
        return KalshiAutoTrader(config)

    def test_entry_requires_fee_adjusted_net_edge(self) -> None:
        quote = MarketQuote(
            ticker="KXTEST-EDGE",
            title="Edge test",
            category="test",
            volume=5000.0,
            yes_bid=0.53,
            yes_ask=0.55,
            no_bid=0.45,
            no_ask=0.47,
        )
        signal = AlphaSignal(fair_yes_probability=0.62, confidence=0.85, source="unit")

        passing = self._make_trader(min_net_edge=0.03)
        candidate_pass = passing._compute_edge(quote, signal)
        self.assertIsNotNone(candidate_pass)
        assert candidate_pass is not None
        self.assertGreater(candidate_pass["net_edge"], 0.03)
        self.assertLess(candidate_pass["net_edge"], candidate_pass["gross_edge"])

        failing = self._make_trader(min_net_edge=0.05)
        candidate_fail = failing._compute_edge(quote, signal)
        self.assertIsNone(candidate_fail)


if __name__ == "__main__":
    unittest.main()
