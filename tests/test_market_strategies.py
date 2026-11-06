import unittest

from market_strategies import PROFILES, TIMEFRAMES, analyze


def candles(direction="UP", volume=True):
    rows = []
    price = 100.0
    for i in range(100):
        step = 0.42 if direction == "UP" else -0.42
        previous = price
        price += step
        op = previous
        high = price + 0.04 if direction == "UP" else op + 0.04
        low = op - 0.04 if direction == "UP" else price - 0.04
        vol = 3200.0 if i == 99 else 1000.0
        rows.append([i * 900000, op, high, low, price, vol if volume else 0.0])
    rows.append([100 * 900000, price, price * 1.2, price * 0.8, price, 999999.0])
    return rows


class SmartFlowQuantTests(unittest.TestCase):
    def test_all_six_timeframes_are_supported_independently(self):
        self.assertEqual(TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        for frame in TIMEFRAMES:
            signal = analyze("futures", "TEST", candles("UP"), timeframe=frame)
            self.assertIsNotNone(signal, frame)
            self.assertEqual(signal["timeframe"], frame)

    def test_buy_signal_uses_structural_stop_and_three_r_targets(self):
        signal = analyze("futures", "TEST", candles("UP"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], risk)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], risk * 2)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], risk * 3)
        self.assertTrue(signal["reason"].startswith("SMART FLOW QUANT:"))
        self.assertNotIn("EMA", signal["reason"])
        self.assertNotIn("MACD", signal["reason"])
        self.assertNotIn("RSI", signal["reason"])

    def test_sell_signal_only_for_short_capable_markets(self):
        signal = analyze("futures", "TEST", candles("DOWN"), timeframe="1h")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertIsNone(analyze(market, "TEST", candles("DOWN"), timeframe="1h"))

    def test_cash_markets_can_generate_long_signals(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            signal = analyze(market, "TEST", candles("UP"), timeframe="4h")
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "BUY")

    def test_zero_volume_feed_can_use_price_structure_without_fabricating_volume(self):
        signal = analyze("forex", "EURUSD=X", candles("UP", volume=False), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertIsNone(signal["volume_ratio"])

    def test_binance_flow_is_optional_and_additive(self):
        flow = {"taker_delta_ratio": 0.45, "book_imbalance": 0.35}
        signal = analyze("futures", "TEST", candles("UP"), microstructure=flow)
        self.assertIsNotNone(signal)
        self.assertGreaterEqual(signal["score"], 90)
        self.assertEqual(signal["taker_delta_ratio"], 0.45)
        self.assertEqual(signal["book_imbalance"], 0.35)

    def test_forming_candle_does_not_change_signal(self):
        rows = candles("UP")
        original = analyze("futures", "TEST", rows, timeframe="1d")
        rows[-1] = [rows[-1][0], 1000, 5000, 1, 2, 1e12]
        changed = analyze("futures", "TEST", rows, timeframe="1d")
        self.assertEqual(original, changed)

    def test_flat_market_does_not_generate_a_signal(self):
        rows = [[i * 900000, 100, 100.2, 99.8, 100, 1000] for i in range(100)]
        self.assertIsNone(analyze("futures", "FLAT", rows, timeframe="15m"))

    def test_unknown_market_and_timeframe_are_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("UP"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("UP"), timeframe="3m"))


if __name__ == "__main__":
    unittest.main()
