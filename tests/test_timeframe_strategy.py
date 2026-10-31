import math
import unittest

from timeframe_strategy import TIMEFRAME_RULES, assess_timeframe, make_trade


def rising_bars(count=80):
    rows = []
    for index in range(count):
        close = 100 + index * 0.1 + math.sin(index / 3) * 0.12
        rows.append({
            "open": close - 0.03,
            "high": close + 0.55,
            "low": close - 0.55,
            "close": close,
            "volume": 1000 + (index % 5) * 20,
        })
    return rows


class TimeframeStrategyTests(unittest.TestCase):
    def test_monthly_is_a_supported_standalone_timeframe(self):
        self.assertEqual(TIMEFRAME_RULES["1M"], ())

    def test_short_history_is_rejected(self):
        result = assess_timeframe(rising_bars(30))
        self.assertEqual(result["state"], "INSUFFICIENT")

    def test_directional_score_is_bounded_and_not_a_probability_claim(self):
        result = assess_timeframe(rising_bars())
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["state"], ("BUY", "STRONG_BUY", "NEUTRAL", "SELL", "STRONG_SELL"))

    def test_trade_levels_follow_one_two_three_r(self):
        rows = rising_bars()
        trade = make_trade(rows, "BUY")
        self.assertIsNotNone(trade)
        risk = trade["entry"] - trade["stop_loss"]
        self.assertAlmostEqual(trade["tp1"] - trade["entry"], risk)
        self.assertAlmostEqual(trade["tp2"] - trade["entry"], risk * 2)
        self.assertAlmostEqual(trade["tp3"] - trade["entry"], risk * 3)
        self.assertGreater(trade["risk_percent"], 0)
        self.assertLessEqual(trade["risk_percent"], 4.5)

    def test_invalid_side_never_creates_trade(self):
        self.assertIsNone(make_trade(rising_bars(), "HOLD"))


if __name__ == "__main__":
    unittest.main()
