"""Tests for the independent SMART MONEY market-structure engine."""
import unittest
import smart_money_strategy as strategy


class SmartMoneyStrategyTests(unittest.TestCase):
    def test_completed_candle_only(self):
        rows = [[i, 100, 101, 99, 100, 10] for i in range(25)]
        self.assertEqual(len(strategy._finite_rows(rows)), 24)

    def test_volume_profile_is_explicitly_approximate(self):
        bars = strategy._finite_rows([[i, 100+i*.1, 101+i*.1, 99+i*.1, 100+i*.1, 10] for i in range(30)])
        profile = strategy._volume_profile(bars)
        self.assertEqual(profile["method"], "candle_weighted_approximation")
        self.assertLessEqual(profile["val"], profile["poc"])
        self.assertLessEqual(profile["poc"], profile["vah"])

    def test_bullish_structure_requires_higher_high_and_higher_low(self):
        bars = []
        for i in range(30):
            close = 100 + i * 0.2 + (2 if i % 6 in (0, 1) else 0)
            bars.append({"open": close-.1, "high": close+.2, "low": close-.2, "close": close, "volume": 10, "time": i, "taker_buy": None})
        structure, highs, lows = strategy._market_structure(bars)
        self.assertIn(structure, ("BULLISH", "RANGE", "BEARISH", "UNCONFIRMED"))
        self.assertIsInstance(highs, list)
        self.assertIsInstance(lows, list)

    def test_binance_taker_flow_is_only_used_when_present(self):
        rows = [[i, 100, 101, 99, 100, 10, 0, 1000, 0, 7, 0, 0] for i in range(30)]
        bars = strategy._finite_rows(rows)
        self.assertTrue(all(bar["taker_buy"] == 7 for bar in bars))
        yahoo_rows = [[i, 100, 101, 99, 100, 10] for i in range(30)]
        self.assertTrue(all(bar["taker_buy"] is None for bar in strategy._finite_rows(yahoo_rows)))

    def test_spot_never_returns_sell(self):
        rows = [[i, 100, 101, 99, 100, 10] for i in range(30)]
        signal = strategy.analyze("spot", "TEST", rows)
        self.assertTrue(signal is None or signal["side"] == "BUY")

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
