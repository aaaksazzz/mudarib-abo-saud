"""Tests for the single active ICT/SMC reversal strategy."""
import unittest
import smart_money_strategy as strategy


def candle(i, op=100, high=101, low=99, close=100, volume=10):
    return [i, op, high, low, close, volume]


def bullish_reversal_rows():
    bars = [candle(i) for i in range(21)]
    bars[5] = candle(5, 97, 99, 95, 98)
    bars[8] = candle(8, 103, 105, 102, 104)
    bars[12] = candle(12, 97, 99, 94, 96)
    bars[15] = candle(15, 104, 108, 103, 107)
    bars[16] = candle(16, 107, 108, 106, 107)
    bars[17] = candle(17, 108, 109, 107, 108)
    bars[18] = candle(18, 110, 112, 109, 111)
    bars[19] = candle(19, 110, 111, 108, 109)
    bars[20] = candle(20, 108, 110, 107.5, 109.5)
    # Final row is intentionally forming and must be ignored.
    bars.append(candle(21, 109.5, 110, 109, 109.7))
    return bars


class ICTReversalStrategyTests(unittest.TestCase):
    def test_final_forming_candle_is_excluded(self):
        self.assertEqual(len(strategy._bars(bullish_reversal_rows())), 21)

    def test_target_geometry_is_exactly_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))

    def test_sweep_choch_bos_fvg_retest_generates_buy(self):
        signal = strategy.analyze("futures", "TESTUSDT", bullish_reversal_rows(), "15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertEqual(signal["setup_type"], "ICT_SMC_REVERSAL_FVG_RETEST")
        self.assertEqual(signal["confirmations"][:5], [
            "CLOSED_CANDLE", "LIQUIDITY_SWEEP", "CHoCH_BOS_DISPLACEMENT",
            "FAIR_VALUE_GAP", "FVG_RETEST_REJECTION"
        ])

    def test_spot_does_not_emit_short_signals(self):
        signal = strategy.analyze("spot", "TEST", bullish_reversal_rows(), "15m")
        self.assertTrue(signal is None or signal["side"] == "BUY")

    def test_all_supported_markets_and_six_timeframes(self):
        self.assertEqual(len(strategy.MARKETS), 7)
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES), set(strategy.TIMEFRAMES))

    def test_diagnostic_self_test(self):
        self.assertTrue(strategy.diagnostic_self_test()["ok"])


if __name__ == "__main__":
    unittest.main()
