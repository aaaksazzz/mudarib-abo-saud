"""Regression tests for STP Price Action Quant V2."""
import unittest
import smart_money_strategy as strategy


def trending_rows(direction="BULLISH"):
    rows=[]
    drift=0.16 if direction=="BULLISH" else -0.16
    wave=(0, 0.8, 1.4, 0.8, 0, -0.8, -1.4, -0.8)
    for i in range(80):
        close=100 + drift*i + wave[i % len(wave)]
        rows.append([i, close, close+0.25, close-0.25, close, 10])
    rows.append([80, rows[-1][4], rows[-1][4]+0.2, rows[-1][4]-0.2, rows[-1][4], 10])
    return rows


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


class PriceActionQuantV3Tests(unittest.TestCase):
    def test_final_forming_candle_is_excluded(self):
        self.assertEqual(len(strategy._bars(bullish_reversal_rows())), 47)

    def test_targets_are_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))

    def test_full_inversion_reverses_setup_and_trend_all_hours(self):
        bearish = [[r[0], 200-r[1], 200-r[3], 200-r[2], 200-r[4], r[5]] for r in bullish_reversal_rows()]
        inverted_buy = strategy.analyze("futures", "TEST", bearish, "4h", market_bias="SELL", higher_timeframe_rows=trending_rows("BULLISH"))
        inverted_sell = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h", market_bias="BUY", higher_timeframe_rows=trending_rows("BEARISH"))
        self.assertIsNotNone(inverted_buy)
        self.assertIsNotNone(inverted_sell)
        self.assertEqual(inverted_buy["side"], "BUY")
        self.assertEqual(inverted_sell["side"], "SELL")
        self.assertEqual(inverted_buy["session_mode"], "INVERTED_ALL_HOURS")
        self.assertEqual(inverted_sell["session_mode"], "INVERTED_ALL_HOURS")
        self.assertLess(inverted_buy["stop"], inverted_buy["entry"])
        self.assertGreater(inverted_sell["stop"], inverted_sell["entry"])
        self.assertEqual(inverted_buy["reward_risk"], 3.0)
        self.assertEqual(inverted_sell["reward_risk"], 3.0)

    def test_spot_only_keeps_executable_buy_after_inversion(self):
        bearish = [[r[0], 200-r[1], 200-r[3], 200-r[2], 200-r[4], r[5]] for r in bullish_reversal_rows()]
        signal = strategy.analyze("spot", "TEST", bearish, "4h", higher_timeframe_rows=trending_rows("BULLISH"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        blocked = strategy.analyze("spot", "TEST", bullish_reversal_rows(), "4h", higher_timeframe_rows=trending_rows("BEARISH"))
        self.assertIsNone(blocked)
    def test_all_markets_and_six_timeframes(self):
        self.assertEqual(len(strategy.MARKETS), 7)
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES), set(strategy.TIMEFRAMES))

    def test_higher_timeframe_trend_classification(self):
        self.assertEqual(strategy._classify_trend(trending_rows("BULLISH")), "BULLISH")
        self.assertEqual(strategy._classify_trend(trending_rows("BEARISH")), "BEARISH")

    def test_natural_trend_aligned_setup_is_rejected_by_inverse_filter(self):
        diagnostics = {}
        signal = strategy.analyze(
            "futures", "TEST", bullish_reversal_rows(), "4h",
            higher_timeframe_rows=trending_rows("BEARISH"), diagnostics=diagnostics
        )
        self.assertIsNone(signal)
        self.assertGreater(diagnostics.get("inverted_setup_not_aligned_with_inverse_trend", 0), 0)

    def test_unclear_higher_timeframe_is_rejected(self):
        diagnostics = {}
        signal = strategy.analyze(
            "futures", "TEST", bullish_reversal_rows(), "4h",
            higher_timeframe_rows=[[i,100,101,99,100,10] for i in range(50)],
            diagnostics=diagnostics
        )
        self.assertIsNone(signal)
        self.assertGreater(diagnostics.get("higher_timeframe_trend_unclear", 0), 0)

    def test_market_bias_remains_compatibility_only(self):
        a = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h", market_bias="BUY", higher_timeframe_rows=trending_rows("BEARISH"))
        b = strategy.analyze("futures", "TEST", bullish_reversal_rows(), "4h", market_bias="SELL", higher_timeframe_rows=trending_rows("BEARISH"))
        self.assertEqual(a["side"], b["side"])

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
