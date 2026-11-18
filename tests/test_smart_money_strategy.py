"""Regression tests for AS Practical Signal Extraction V4."""
import unittest
import smart_money_strategy as strategy


def candle(i, op, high, low, close, volume=10):
    return [i, op, high, low, close, volume]


def trending_rows(direction="BULLISH"):
    rows = []
    drift = 0.16 if direction == "BULLISH" else -0.16
    wave = (0, 0.8, 1.4, 0.8, 0, -0.8, -1.4, -0.8)
    for i in range(80):
        close = 100 + drift*i + wave[i % len(wave)]
        rows.append(candle(i, close, close+0.25, close-0.25, close))
    rows.append(candle(80, rows[-1][4], rows[-1][4]+0.2, rows[-1][4]-0.2, rows[-1][4]))
    return rows


def rising_pullback_rows():
    rows = []
    for i in range(55):
        close = 100 + i*0.12
        op = close-0.08
        rows.append(candle(i, op, close+0.12, op-0.12, close, 12))
    rows.append(candle(55, 106.45, 106.75, 106.35, 106.68, 15))
    rows.append(candle(56, 106.68, 106.78, 106.58, 106.72, 11))
    return rows


class ASPracticalSignalTests(unittest.TestCase):
    def test_forming_candle_is_excluded(self):
        self.assertEqual(len(strategy._bars(rising_pullback_rows())), 56)

    def test_targets_are_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))

    def test_local_setup_works_without_higher_timeframe_data(self):
        signal = strategy.analyze("futures", "TEST", rising_pullback_rows(), "1h")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertEqual(signal["reward_risk"], 3.0)
        self.assertEqual(signal["session_mode"], "NORMAL_ALL_HOURS")

    def test_higher_timeframe_conflict_is_caution_not_veto(self):
        signal = strategy.analyze(
            "futures", "TEST", rising_pullback_rows(), "1h",
            higher_timeframe_rows=trending_rows("BEARISH")
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertIn("HIGHER_TIMEFRAME_CONFLICT_CAUTION", signal["confirmations"])

    def test_spot_remains_buy_only(self):
        signal = strategy.analyze("spot", "TEST", rising_pullback_rows(), "4h")
        self.assertTrue(signal is None or signal["side"] == "BUY")

    def test_seven_markets_and_six_timeframes(self):
        self.assertEqual(len(strategy.MARKETS), 7)
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))

    def test_new_fingerprint_and_diagnostics(self):
        self.assertEqual(strategy.STRATEGY_FINGERPRINT, "AS-SIGNAL-EXTRACTION-V4-20261118-ADAPTIVE")
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
