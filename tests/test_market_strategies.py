import unittest

from market_strategies import PROFILES, STRATEGY_FINGERPRINT, TIMEFRAMES, analyze, sma200_allows


def candles(direction="UP", volume=True, count=220):
    rows = []
    price = 100.0 if direction == "UP" else 300.0
    for i in range(count):
        step = 0.42 if direction == "UP" else -0.42
        previous = price
        price += step
        op = previous
        high = price + 0.04 if direction == "UP" else op + 0.04
        low = op - 0.04 if direction == "UP" else price - 0.04
        vol = 3200.0 if i == count - 1 else 1000.0
        rows.append([i * 900000, op, high, low, price, vol if volume else 0.0])
    # A deliberately forming candle: the analyzer must ignore it.
    rows.append([count * 900000, price, price * 1.2, price * 0.8, price, 999999.0])
    return rows


class Sma200StrategyTests(unittest.TestCase):
    def test_fingerprint_and_timeframes(self):
        self.assertEqual(STRATEGY_FINGERPRINT, "SMART-FLOW-SMA200-V1-20261107")
        self.assertEqual(TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(len(PROFILES), 7)

    def test_sma200_gate_allows_only_matching_direction(self):
        self.assertTrue(sma200_allows("BUY", 101, 100))
        self.assertFalse(sma200_allows("BUY", 99, 100))
        self.assertTrue(sma200_allows("SELL", 99, 100))
        self.assertFalse(sma200_allows("SELL", 101, 100))
        self.assertFalse(sma200_allows("BUY", 100, 100))

    def test_all_timeframes_are_analyzed_independently(self):
        for frame in TIMEFRAMES:
            signal = analyze("futures", "TEST", candles("UP"), timeframe=frame)
            self.assertIsNotNone(signal, frame)
            self.assertEqual(signal["timeframe"], frame)
            self.assertGreater(signal["entry"], signal["ma200"])

    def test_buy_signal_has_structural_stop_and_three_r_targets(self):
        signal = analyze("futures", "TEST", candles("UP"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], risk)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], risk * 2)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], risk * 3)
        self.assertGreaterEqual(signal["score"], 70)
        self.assertLessEqual(signal["score"], 100)

    def test_sell_signal_requires_short_capable_market_and_below_sma200(self):
        signal = analyze("futures", "TEST", candles("DOWN"), timeframe="1h")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        self.assertLess(signal["entry"], signal["ma200"])
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertIsNone(analyze(market, "TEST", candles("DOWN"), timeframe="1h"))

    def test_cash_markets_can_generate_long_signals_above_sma200(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            signal = analyze(market, "TEST", candles("UP"), timeframe="4h")
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "BUY")

    def test_zero_volume_does_not_fabricate_volume_confirmation(self):
        signal = analyze("forex", "EURUSD=X", candles("UP", volume=False), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertIsNone(signal["volume_ratio"])
        self.assertNotIn("volume expansion", signal["strategy_votes"]["BUY"])

    def test_binance_flow_is_optional_and_additive(self):
        flow = {"taker_delta_ratio": 0.45, "book_imbalance": 0.35}
        signal = analyze("futures", "TEST", candles("UP"), microstructure=flow)
        self.assertIsNotNone(signal)
        self.assertGreater(signal["score"], 80)
        self.assertEqual(signal["taker_delta_ratio"], 0.45)
        self.assertEqual(signal["book_imbalance"], 0.35)

    def test_forming_candle_does_not_change_signal(self):
        rows = candles("UP")
        original = analyze("futures", "TEST", rows, timeframe="1d")
        rows[-1] = [rows[-1][0], 1000, 5000, 1, 2, 1e12]
        changed = analyze("futures", "TEST", rows, timeframe="1d")
        self.assertEqual(original, changed)

    def test_insufficient_history_is_rejected(self):
        self.assertIsNone(analyze("futures", "TEST", candles("UP", count=199), timeframe="15m"))

    def test_flat_market_does_not_generate_a_signal(self):
        rows = [[i * 900000, 100, 100.2, 99.8, 100, 1000] for i in range(220)]
        rows.append([220 * 900000, 100, 101, 99, 100, 1000])
        self.assertIsNone(analyze("futures", "FLAT", rows, timeframe="15m"))

    def test_unknown_market_and_timeframe_are_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("UP"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("UP"), timeframe="3m"))


if __name__ == "__main__":
    unittest.main()
