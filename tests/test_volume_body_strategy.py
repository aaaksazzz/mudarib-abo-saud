import unittest
from unittest.mock import patch

import quant_engine


class FakeSignalService:
    def calculate_all(self, frame):
        return [object() for _ in range(60)]


class FakeConsensusEngine:
    def __init__(self, side):
        self.side = side

    def evaluate(self, results):
        return {
            "final_signal": self.side,
            "should_trade": True,
            "risk_level": "LOW",
            "confidence": 82,
            "weighted_score": 1.4 if self.side == "STRONG_BUY" else -1.4,
            "score_data": {"active_signals": 12, "total_signals": 60, "buy_count": 11 if self.side == "STRONG_BUY" else 1,
                           "sell_count": 1 if self.side == "STRONG_BUY" else 11},
            "risk_data": {"risk_level": "LOW"},
        }


class DiveQuantProTests(unittest.TestCase):
    def rows(self, rising=True):
        out = []
        for i in range(120):
            close = 100 + i * 0.4 if rising else 180 - i * 0.4
            open_price = close - 0.15 if rising else close + 0.15
            out.append([i * 900000, open_price, close + 0.2, close - 0.2, close, 1000])
        return out

    def run_engine(self, side, market="spot", rising=True):
        config = {"indicator_weights": {}}
        with patch.object(quant_engine, "_engine", return_value=(config, FakeSignalService(), FakeConsensusEngine(side))), \
             patch.object(quant_engine, "evaluate_regime", return_value={"regime":"TREND","adaptive_score":1.4}):
            return quant_engine.analyze(market, "BTCUSDT", self.rows(rising), include_micro=False)

    def test_upstream_consensus_builds_exact_three_r_long_targets(self):
        setup = self.run_engine("STRONG_BUY")
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")
        risk = setup["entry"] - setup["stop"]
        self.assertAlmostEqual(setup["tp1"] - setup["entry"], risk)
        self.assertAlmostEqual(setup["tp2"] - setup["entry"], 2 * risk)
        self.assertAlmostEqual(setup["tp3"] - setup["entry"], 3 * risk)
        self.assertEqual(setup["reward_risk"], 3.0)
        self.assertEqual(setup["indicator_count"], 60)

    def test_upstream_consensus_builds_exact_three_r_short_targets(self):
        setup = self.run_engine("STRONG_SELL", market="futures", rising=False)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "SELL")
        risk = setup["stop"] - setup["entry"]
        self.assertAlmostEqual(setup["entry"] - setup["tp1"], risk)
        self.assertAlmostEqual(setup["entry"] - setup["tp2"], 2 * risk)
        self.assertAlmostEqual(setup["entry"] - setup["tp3"], 3 * risk)

    def test_insufficient_candles_do_not_create_signals(self):
        self.assertIsNone(quant_engine.analyze("spot", "BTCUSDT", self.rows()[:74]))


if __name__ == "__main__":
    unittest.main()
