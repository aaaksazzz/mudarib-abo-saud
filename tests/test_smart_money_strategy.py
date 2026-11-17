"""Regression tests for STP Price Action Quant V2."""
import unittest
from datetime import datetime
import smart_money_strategy as strategy


def candle(i, op=100, high=101, low=99, close=100, volume=10):
    return [i, op, high, low, close, volume]


def bullish_reversal_rows():
    pattern = [candle(i) for i in range(21)]
    pattern[5] = candle(5, 99.2, 100.2, 98.8, 99.8)
    pattern[8] = candle(8, 100.8, 101.5, 100.4, 101.2)
    pattern[12] = candle(12, 99.4, 100, 98.4, 99.2)
    pattern[15] = candle(15, 100.8, 102.1, 100.6, 101.9)
    pattern[16] = candle(16, 101.9, 102.0, 101.7, 101.9)
    pattern[17] = candle(17, 102.0, 102.2, 101.9, 102.1)
    pattern[18] = candle(18, 102.5, 103.0, 102.4, 102.8)
    pattern[19] = candle(19, 102.8, 103.0, 102.2, 102.6)
    pattern[20] = candle(20, 102.3, 103.0, 101.9, 102.7)
    prefix = [candle(i) for i in range(25)]
    shifted = [[row[0] + 25, *row[1:]] for row in pattern]
    bars = prefix + shifted
    bars.append(candle(45, 102.1, 102.5, 102.1, 102.35))
    bars.append(candle(46, 102.7, 102.9, 102.5, 102.8))
    return bars


class PriceActionQuantV2Tests(unittest.TestCase):
    def test_final_forming_candle_is_excluded(self):
        self.assertEqual(len(strategy._bars(bullish_reversal_rows())), 47)

    def test_targets_are_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))

    def test_day_session_keeps_source_direction_independent_of_market_bias(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=strategy.SAUDI_TZ)
        buy = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h",
                               market_bias="SELL", now=now)
        self.assertIsNotNone(buy)
        self.assertEqual(buy["side"], "BUY")
        self.assertEqual(buy["session_mode"], "DAY_NORMAL")
        self.assertLess(buy["stop"], buy["entry"])
        self.assertEqual(buy["reward_risk"], 3.0)

    def test_night_session_inverts_source_direction(self):
        now = datetime(2026, 11, 17, 22, 0, tzinfo=strategy.SAUDI_TZ)
        sell = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h",
                                market_bias="BUY", now=now)
        self.assertIsNotNone(sell)
        self.assertEqual(sell["source_setup_side"], "BUY")
        self.assertEqual(sell["side"], "SELL")
        self.assertEqual(sell["session_mode"], "NIGHT_INVERTED")
        self.assertGreater(sell["stop"], sell["entry"])
        self.assertLess(sell["tp1"], sell["entry"])

    def test_spot_remains_buy_only_after_night_transform(self):
        now = datetime(2026, 11, 17, 22, 0, tzinfo=strategy.SAUDI_TZ)
        diagnostics = {}
        signal = strategy.analyze("spot", "TEST", bullish_reversal_rows(), "4h",
                                  now=now, diagnostics=diagnostics)
        self.assertIsNone(signal)
        self.assertIn("spot_buy_only_after_session_transform", diagnostics)

    def test_session_boundaries_are_saudi_local(self):
        self.assertTrue(strategy.is_night_session(datetime(2026, 11, 17, 18, 0, tzinfo=strategy.SAUDI_TZ)))
        self.assertTrue(strategy.is_night_session(datetime(2026, 11, 17, 5, 59, tzinfo=strategy.SAUDI_TZ)))
        self.assertFalse(strategy.is_night_session(datetime(2026, 11, 17, 6, 0, tzinfo=strategy.SAUDI_TZ)))
        self.assertFalse(strategy.is_night_session(datetime(2026, 11, 17, 17, 59, tzinfo=strategy.SAUDI_TZ)))

    def test_all_markets_and_six_timeframes(self):
        self.assertEqual(len(strategy.MARKETS), 7)
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES), set(strategy.TIMEFRAMES))

    def test_bias_argument_is_compatibility_only(self):
        now = datetime(2026, 11, 17, 12, 0, tzinfo=strategy.SAUDI_TZ)
        a = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h", market_bias="BUY", now=now)
        b = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h", market_bias="SELL", now=now)
        self.assertEqual(a["side"], b["side"])

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
