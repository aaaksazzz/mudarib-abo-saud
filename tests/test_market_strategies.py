import unittest

from market_strategies import PROFILES, TIMEFRAMES, analyze


def candles(direction="UP", volume=True, count=220):
    rows = []
    price = 100.0
    for i in range(count):
        step = 0.42 if direction == "UP" else -0.42
        previous = price
        price += step
        op = previous
        high = max(op, price) + 0.04
        low = min(op, price) - 0.04
        vol = 3200.0 if i == count - 1 else 1000.0
        rows.append([i * 900000, op, high, low, price, vol if volume else 0.0])
    # Last row represents the still-forming candle and must be ignored.
    rows.append([count * 900000, price, price * 1.2, price * 0.8, price, 999999.0])
    return rows


class MA200OnlyTests(unittest.TestCase):
    def test_all_seven_markets_and_six_timeframes_are_supported(self):
        self.assertEqual(TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(set(PROFILES), {"spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex"})
        for market in PROFILES:
            for frame in TIMEFRAMES:
                signal = analyze(market, "TEST", candles("UP"), timeframe=frame)
                self.assertIsNotNone(signal, (market, frame))
                self.assertEqual(signal["side"], "BUY")
                self.assertEqual(signal["timeframe"], frame)
                self.assertGreater(signal["entry"], signal["ma200"])

    def test_price_below_ma200_generates_sell_for_every_market(self):
        for market in PROFILES:
            signal = analyze(market, "TEST", candles("DOWN"), timeframe="1h")
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "SELL", market)
            self.assertLess(signal["entry"], signal["ma200"])
            self.assertGreater(signal["stop"], signal["entry"])
            self.assertLess(signal["tp1"], signal["entry"])

    def test_buy_signal_uses_three_r_targets_and_valid_stop(self):
        signal = analyze("futures", "TEST", candles("UP"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], risk)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], risk * 2)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], risk * 3)
        self.assertEqual(signal["reward_risk"], 3.0)
        self.assertEqual(signal["strategy"], "MA200_ONLY_FUTURES_15m")

    def test_zero_volume_feed_does_not_fabricate_volume(self):
        signal = analyze("forex", "EURUSD=X", candles("UP", volume=False), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertIsNone(signal["volume_ratio"])

    def test_forming_candle_does_not_change_signal(self):
        rows = candles("UP")
        original = analyze("futures", "TEST", rows, timeframe="1d")
        rows[-1] = [rows[-1][0], 1000, 5000, 1, 2, 1e12]
        changed = analyze("futures", "TEST", rows, timeframe="1d")
        self.assertEqual(original, changed)

    def test_insufficient_history_and_flat_market_do_not_generate_signal(self):
        self.assertIsNone(analyze("futures", "SHORT", candles("UP", count=100), timeframe="15m"))
        rows = [[i * 900000, 100, 100.2, 99.8, 100, 1000] for i in range(220)]
        rows.append([220 * 900000, 100, 120, 80, 100, 1000])
        self.assertIsNone(analyze("futures", "FLAT", rows, timeframe="15m"))

    def test_unknown_market_and_timeframe_are_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("UP"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("UP"), timeframe="3m"))


if __name__ == "__main__":
    unittest.main()
