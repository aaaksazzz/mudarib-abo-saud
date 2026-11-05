import unittest

from market_strategies import PROFILES, TIMEFRAMES, analyze


def candles(side="BUY"):
    rows = []
    # Stable, low-range candles keep ADX in a ranging regime.
    for i in range(100):
        price = 100.0 + (0.03 if i % 2 else -0.03)
        rows.append([i * 900000, price - 0.05, price + 0.05, price - 0.05, price, 1000.0])
    stamp = 100 * 900000
    if side == "BUY":
        rows.append([stamp, 100.0, 101.0, 94.5, 95.0, 3000.0])
    else:
        rows.append([stamp, 100.0, 105.5, 99.0, 105.0, 3000.0])
    # Forming candle is deliberately extreme and must be ignored.
    rows.append([stamp + 900000, 100.0, 110.0, 90.0, 100.0, 99999.0])
    return rows


class VWAPReversionTests(unittest.TestCase):
    def test_long_bracket_and_staged_targets(self):
        signal = analyze("futures", "TEST", candles("BUY"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertGreater(signal["entry"], signal["stop"])
        self.assertLess(signal["entry"], signal["tp1"])
        self.assertLess(signal["tp1"], signal["tp2"])
        self.assertLess(signal["tp2"], signal["tp3"])
        self.assertEqual(signal["timeframe"], "15m")

    def test_short_only_for_markets_that_allow_it(self):
        signal = analyze("futures", "TEST", candles("SELL"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertGreater(signal["tp1"], signal["tp2"])
        self.assertGreater(signal["tp2"], signal["tp3"])
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertIsNone(analyze(market, "TEST", candles("SELL"), timeframe="15m"))

    def test_cash_markets_can_generate_long_signals(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            signal = analyze(market, "TEST", candles("BUY"), timeframe="15m")
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "BUY")

    def test_only_15m_is_registered(self):
        self.assertEqual(TIMEFRAMES, ("15m",))
        self.assertIsNotNone(analyze("futures", "TEST", candles("BUY"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("BUY"), timeframe="1h"))

    def test_zero_volume_feed_uses_explicit_price_proxy(self):
        rows = candles("BUY")
        for row in rows:
            row[5] = 0.0
        signal = analyze("forex", "EURUSD=X", rows, timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["vwap_method"], "equal_weight_proxy")

    def test_unknown_market_and_timeframe_are_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("BUY"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("BUY"), timeframe="3m"))


if __name__ == "__main__":
    unittest.main()
