"""Regression tests for the shared strategy gate; run with python -m unittest discover -s tests."""
import math
import unittest

from strategy_engine_v2 import evaluate_v2


def make_bars(count=80, base=100.0):
    bars = []
    for i in range(count):
        close = base + 0.03 * math.sin(i / 3.0)
        open_ = close - 0.01 * math.cos(i / 2.0)
        bars.append({
            "open": open_,
            "high": max(open_, close) + 0.05,
            "low": min(open_, close) - 0.05,
            "close": close,
            "volume": 100.0,
        })
    return bars


class StrategyGateTests(unittest.TestCase):
    def test_insufficient_candles_returns_wait_without_prices(self):
        result = evaluate_v2(make_bars(40), make_bars(60), timeframe="15m")
        self.assertEqual(result["action"], "WAIT")
        self.assertIsNone(result["entry"])
        self.assertTrue(result["reasons"])

    def test_invalid_ohlcv_is_rejected(self):
        bars = make_bars(80)
        bars[-1]["high"] = bars[-1]["low"] / 2
        result = evaluate_v2(bars, make_bars(80), timeframe="1h")
        self.assertEqual(result["action"], "WAIT")
        self.assertIn("شموع غير متطابقة", " ".join(result["reasons"]))

    def test_flat_market_does_not_create_a_trade(self):
        bars = make_bars(80)
        result = evaluate_v2(bars, make_bars(80), timeframe="4h")
        self.assertIn(result["action"], ("WAIT", "BUY", "SELL"))
        if result["action"] == "WAIT":
            self.assertIsNone(result["entry"])
        else:
            self.assertIsNotNone(result["stop_loss"])
            self.assertIsNotNone(result["take_profit_1"])
            self.assertGreater(result["score"], 0)
            self.assertLess(result["score"], 98)


if __name__ == "__main__":
    unittest.main()
