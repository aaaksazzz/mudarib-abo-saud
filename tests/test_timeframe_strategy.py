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


    def test_bullish_liquidity_sweep_is_detected_on_completed_candle(self):
        rows = rising_bars()
        prior_low = min(row["low"] for row in rows[-21:-1])
        prior_high = max(row["high"] for row in rows[-21:-1])
        rows[-1] = {"open": prior_low + 0.08, "high": prior_high,
                    "low": prior_low - 0.12, "close": prior_low + 0.24,
                    "volume": 1500}
        result = assess_timeframe(rows)
        self.assertEqual(result["liquidity_sweep"], "BULLISH")

    def test_bearish_liquidity_sweep_is_detected_on_completed_candle(self):
        rows = rising_bars()
        prior_low = min(row["low"] for row in rows[-21:-1])
        prior_high = max(row["high"] for row in rows[-21:-1])
        rows[-1] = {"open": prior_high - 0.08, "high": prior_high + 0.12,
                    "low": prior_low, "close": prior_high - 0.24,
                    "volume": 1500}
        result = assess_timeframe(rows)
        self.assertEqual(result["liquidity_sweep"], "BEARISH")

    def test_absorption_is_labeled_as_ohlcv_proxy(self):
        rows = rising_bars()
        prior_volume = sum(row["volume"] for row in rows[-21:-1]) / 20
        rows[-1] = {"open": 107.5, "high": 108.0, "low": 106.0,
                    "close": 107.9, "volume": prior_volume * 2}
        result = assess_timeframe(rows)
        self.assertEqual(result["absorption_proxy"], "BULLISH")

    def test_invalid_side_never_creates_trade(self):
        self.assertIsNone(make_trade(rising_bars(), "HOLD"))


if __name__ == "__main__":
    unittest.main()
