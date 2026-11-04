import unittest
from unittest.mock import patch

import quant_engine


class DiveQuantProTests(unittest.TestCase):
    def rising_rows(self):
        rows = []
        for index in range(120):
            close = 100.0 + index * 0.4
            rows.append([index * 900000, close - 0.15, close + 0.2, close - 0.2, close, 1000])
        return rows

    def test_closed_candle_consensus_builds_three_r_targets(self):
        with patch.object(quant_engine, "_micro", return_value={"available": False, "score": 0, "notes": []}):
            setup = quant_engine.analyze("spot", "BTCUSDT", self.rising_rows())
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")
        risk = setup["entry"] - setup["stop"]
        self.assertAlmostEqual(setup["tp1"] - setup["entry"], risk)
        self.assertAlmostEqual(setup["tp2"] - setup["entry"], 2 * risk)
        self.assertAlmostEqual(setup["tp3"] - setup["entry"], 3 * risk)
        self.assertEqual(setup["reward_risk"], 3.0)

    def test_short_trade_targets_are_three_r_when_signal_exists(self):
        rows = []
        for index in range(120):
            close = 180.0 - index * 0.4
            rows.append([index * 900000, close + 0.15, close + 0.2, close - 0.2, close, 1000])
        with patch.object(quant_engine, "_micro", return_value={"available": False, "score": 0, "notes": []}):
            setup = quant_engine.analyze("futures", "BTCUSDT", rows, include_micro=False)
        if setup:
            self.assertEqual(setup["side"], "SELL")
            risk = setup["stop"] - setup["entry"]
            self.assertAlmostEqual(setup["entry"] - setup["tp1"], risk)
            self.assertAlmostEqual(setup["entry"] - setup["tp2"], 2 * risk)
            self.assertAlmostEqual(setup["entry"] - setup["tp3"], 3 * risk)

    def test_unfinished_or_insufficient_candles_do_not_create_signals(self):
        self.assertIsNone(quant_engine.analyze("spot", "BTCUSDT", self.rising_rows()[:74]))


if __name__ == "__main__":
    unittest.main()
