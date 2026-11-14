import unittest

import market_strategies as strategy


class RegimeAdaptiveStrategyTests(unittest.TestCase):
    def _flat_bars(self, count=110):
        return [[i, 100.0, 101.0, 99.0, 100.0, 100.0] for i in range(count)]

    def _trend_bars(self, count=112):
        rows = []
        for i in range(count):
            close = 100.0 + i * 0.1
            rows.append([i, close - 0.02, close + 0.05, close - 0.05, close, 100.0])
        return rows

    def test_targets_are_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "BUY", 95), (105.0, 110.0, 115.0))
        self.assertEqual(strategy.target_prices(100, "SELL", 105), (95.0, 90.0, 85.0))

    def test_invalid_risk_is_rejected(self):
        self.assertIsNone(strategy.target_prices(100, "BUY", 101))
        self.assertIsNone(strategy.target_prices(100, "SELL", 99))

    def test_spot_does_not_generate_short_signals(self):
        self.assertFalse(strategy.PROFILES["spot"]["allow_short"])
        self.assertTrue(strategy.PROFILES["futures"]["allow_short"])

    def test_flat_market_is_classified_as_range(self):
        bars = strategy._finite_rows(self._flat_bars())
        self.assertEqual(strategy._classify_window(bars[-80:])[0], "RANGE")
        regime, confidence, _ = strategy._rolling_regime(bars)
        self.assertEqual(regime, "RANGE")
        self.assertGreaterEqual(confidence, 0.75)

    def test_trending_market_is_classified_as_trend(self):
        bars = strategy._finite_rows(self._trend_bars())
        self.assertEqual(strategy._classify_window(bars[-80:])[0], "TREND")

    def test_trend_engine_confirms_multi_horizon_breakout(self):
        rows = self._trend_bars()
        bars = strategy._finite_rows(rows)
        highs = [bar[2] for bar in bars]
        lows = [bar[3] for bar in bars]
        closes = [bar[4] for bar in bars]
        atr = strategy._atr(highs, lows, closes, 14)
        ema20 = strategy._ema(closes, 20)
        ema50 = strategy._ema(closes, 50)
        signal = strategy._trend_signal(highs, lows, closes, ema20, ema50, atr)
        self.assertIsNotNone(signal)
        self.assertEqual(signal[0], "BUY")

    def test_range_engine_detects_bullish_rejection(self):
        closes = [100.0 - i * 0.5 for i in range(20)]
        opens = closes[:]
        highs = [value + 0.4 for value in closes]
        lows = [value - 0.4 for value in closes]
        closes[-1] = closes[-2] + 0.2
        opens[-1] = closes[-1] - 0.3
        highs[-1] = closes[-1] + 0.4
        lows[-1] = closes[-1] - 0.5
        signal = strategy._range_signal(opens, highs, lows, closes)
        self.assertIsNotNone(signal)
        self.assertEqual(signal[0], "BUY")

    def test_forming_candle_is_excluded(self):
        bars = strategy._finite_rows(self._flat_bars(106))
        self.assertEqual(len(bars), 105)

    def test_diagnostic_self_test(self):
        result = strategy.diagnostic_self_test()
        self.assertTrue(result["ok"], result["checks"])


if __name__ == "__main__":
    unittest.main()
