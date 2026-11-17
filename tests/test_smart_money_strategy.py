"""Tests for independent Saudi day/night ICT/SMC strategy."""
import unittest
from datetime import datetime, timedelta, timezone
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


TZ = timezone(timedelta(hours=3))
DAY = datetime(2026, 11, 17, 12, 0, tzinfo=TZ)
NIGHT = datetime(2026, 11, 17, 20, 0, tzinfo=TZ)


class IndependentDayNightStrategyTests(unittest.TestCase):
    def test_final_forming_candle_is_excluded(self):
        self.assertEqual(len(strategy._bars(bullish_reversal_rows())), 47)

    def test_target_geometry_is_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))

    def test_day_uses_detected_direction_even_against_bearish_market_bias(self):
        signal = strategy.analyze("futures", "TESTUSDT", bullish_reversal_rows(),
                                  "4h", market_bias="SELL", now=DAY)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertEqual(signal["source_setup_side"], "BUY")
        self.assertEqual(signal["session_mode"], "DAY")
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["tp1"], signal["entry"])
        self.assertEqual(signal["reward_risk"], 3.0)
        self.assertNotIn("MARKET_BIAS_ALIGNMENT", signal["confirmations"])

    def test_night_reverses_buy_to_sell_and_rebuilds_levels(self):
        signal = strategy.analyze("spot", "TEST", bullish_reversal_rows(),
                                  "4h", market_bias="BUY", now=NIGHT)
        self.assertIsNotNone(signal)
        self.assertEqual(signal["source_setup_side"], "BUY")
        self.assertEqual(signal["side"], "SELL")
        self.assertEqual(signal["session_mode"], "NIGHT")
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])
        self.assertLess(signal["tp1"], signal["tp2"])
        self.assertLess(signal["tp2"], signal["tp3"])
        self.assertIn("SIDE_INVERTED_BY_SAUDI_SESSION", signal["confirmations"])

    def test_neutral_or_missing_market_bias_does_not_block_signal(self):
        for bias in (None, "NEUTRAL", "BUY", "SELL"):
            signal = strategy.analyze("spot", "TEST", bullish_reversal_rows(),
                                      "4h", market_bias=bias, now=DAY)
            self.assertIsNotNone(signal, msg=f"bias={bias}")

    def test_session_boundaries_use_saudi_time(self):
        self.assertEqual(strategy.saudi_session_mode(datetime(2026, 1, 1, 5, 59, tzinfo=TZ)), "NIGHT")
        self.assertEqual(strategy.saudi_session_mode(datetime(2026, 1, 1, 6, 0, tzinfo=TZ)), "DAY")
        self.assertEqual(strategy.saudi_session_mode(datetime(2026, 1, 1, 17, 59, tzinfo=TZ)), "DAY")
        self.assertEqual(strategy.saudi_session_mode(datetime(2026, 1, 1, 18, 0, tzinfo=TZ)), "NIGHT")

    def test_all_supported_markets_and_six_timeframes(self):
        self.assertEqual(len(strategy.MARKETS), 7)
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES), set(strategy.TIMEFRAMES))

    def test_frame_specific_risk_limits_are_used(self):
        self.assertEqual(strategy.FRAME_PROFILES["15m"]["max_risk_pct"], 0.035)
        self.assertEqual(strategy.FRAME_PROFILES["1h"]["max_risk_pct"], 0.040)
        self.assertEqual(strategy.FRAME_PROFILES["4h"]["max_risk_pct"], 0.050)
        self.assertEqual(strategy.FRAME_PROFILES["1d"]["max_risk_pct"], 0.070)
        self.assertEqual(strategy.FRAME_PROFILES["1w"]["max_risk_pct"], 0.120)
        self.assertEqual(strategy.FRAME_PROFILES["1M"]["max_risk_pct"], 0.200)

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
