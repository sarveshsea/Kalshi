import unittest

from core.trading import AlphaSignal, apply_probability_calibration, to_probability


class TradingProbabilityTests(unittest.TestCase):
    def test_to_probability_normalizes_common_formats(self) -> None:
        self.assertAlmostEqual(to_probability(0.37), 0.37)
        self.assertAlmostEqual(to_probability(37), 0.37)
        self.assertAlmostEqual(to_probability(3700), 0.37)
        self.assertEqual(to_probability(-1), None)
        self.assertEqual(to_probability("bad"), None)

    def test_alpha_signal_parses_optional_fields(self) -> None:
        signal = AlphaSignal.from_payload(
            {
                "fair_yes_probability": 0.62,
                "confidence": 0.8,
                "source": "unit",
                "model_version": "v1",
                "horizon_minutes": 60,
                "expected_edge_net": 0.02,
                "generated_at": "2026-02-04T00:00:00Z",
            }
        )
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.model_version, "v1")
        self.assertEqual(signal.horizon_minutes, 60)
        self.assertAlmostEqual(signal.expected_edge_net or 0.0, 0.02)

    def test_probability_calibration_is_piecewise_linear(self) -> None:
        bins = [(0.2, 0.25), (0.5, 0.55), (0.8, 0.75)]
        self.assertAlmostEqual(apply_probability_calibration(0.2, bins), 0.25)
        self.assertAlmostEqual(apply_probability_calibration(0.5, bins), 0.55)
        self.assertAlmostEqual(apply_probability_calibration(0.35, bins), 0.40)


if __name__ == "__main__":
    unittest.main()
