import math
import unittest

from timeframe_strategy import assess_signal, assess_timeframe


def trend_bars(direction="up", count=100):
    rows = []
    for index in range(count):
        base = 100 + index * 0.18 if direction == "up" else 120 - index * 0.18
        close = base + math.sin(index / 3) * 0.025
        open_price = close - 0.025 if direction == "up" else close + 0.025
        rows.append({
            "open": open_price,
            "high": max(open_price, close) + 0.12,
            "low": min(open_price, close) - 0.12,
            "close": close,
            "volume": 1000 + (index % 7) * 35,
        })
    return rows


class TimeframeStrategyTests(unittest.TestCase):
    def test_short_history_is_rejected(self):
        result = assess_timeframe(trend_bars(count=20))
        self.assertEqual(result["state"], "INSUFFICIENT")

    def test_invalid_rows_are_skipped_not_allowed_to_kill_valid_history(self):
        rows = trend_bars()
        rows.insert(20, {"open": None, "high": 1, "low": 1, "close": 1})
        result = assess_timeframe(rows)
        self.assertEqual(result["candles_used"], 100)

    def test_directional_score_is_bounded(self):
        result = assess_timeframe(trend_bars())
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertIn(result["state"], ("BUY", "STRONG_BUY", "NEUTRAL", "SELL", "STRONG_SELL"))

    def test_uptrend_keeps_original_buy_direction(self):
        result = assess_signal(trend_bars("up"))
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["side"], "BUY")
        self.assertIn(result["state"], ("BUY", "STRONG_BUY"))

    def test_downtrend_keeps_original_sell_direction(self):
        result = assess_signal(trend_bars("down"))
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["side"], "SELL")
        self.assertIn(result["state"], ("SELL", "STRONG_SELL"))



if __name__ == "__main__":
    unittest.main()
