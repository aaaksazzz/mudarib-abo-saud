import unittest

import market_strategies as strategy


class FalseSweepStrategyTests(unittest.TestCase):
    def _bars(self, side):
        opens = [100.0] * 30
        highs = [101.0] * 30
        lows = [99.0] * 30
        closes = [100.0] * 30
        volumes = [100.0] * 30
        if side == "BUY":
            opens[25], highs[25], lows[25], closes[25] = 98.9, 100.5, 98.0, 99.4
            opens[26], highs[26], lows[26], closes[26] = 99.5, 101.1, 99.3, 100.8
            closes[27:] = [100.7, 100.9, 100.9]
        else:
            opens[25], highs[25], lows[25], closes[25] = 101.0, 102.0, 99.5, 100.6
            opens[26], highs[26], lows[26], closes[26] = 100.5, 100.7, 98.9, 99.2
            closes[27:] = [99.3, 99.1, 99.1]
        return opens, highs, lows, closes, volumes

    def test_bullish_sweep_requires_later_close_above_sweep_high(self):
        o, h, l, c, v = self._bars("BUY")
        setup = strategy._find_sweep_setup(h, l, o, c, v, 1.0)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")
        self.assertEqual(setup["sweep_index"], 25)

    def test_bearish_sweep_requires_later_close_below_sweep_low(self):
        o, h, l, c, v = self._bars("SELL")
        setup = strategy._find_sweep_setup(h, l, o, c, v, 1.0)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "SELL")
        self.assertEqual(setup["sweep_index"], 25)

    def test_targets_are_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "BUY", 95), (105.0, 110.0, 115.0))
        self.assertEqual(strategy.target_prices(100, "SELL", 105), (95.0, 90.0, 85.0))

    def test_invalid_risk_is_rejected(self):
        self.assertIsNone(strategy.target_prices(100, "BUY", 101))
        self.assertIsNone(strategy.target_prices(100, "SELL", 99))

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
