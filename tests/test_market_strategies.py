import unittest

from market_strategies import PROFILES, analyze


def market_rows(side="BUY", volume=300.0):
    rows = []
    for i in range(50):
        rows.append([i * 900000, 100.0, 100.3, 99.7, 100.0, 100.0])
    if side == "BUY":
        # High-volume bearish candle becomes the bullish OB.
        rows[35] = [35 * 900000, 100.0, 100.2, 99.5, 99.8, volume]
        rows[36] = [36 * 900000, 100.0, 101.5, 99.9, 101.2, 120.0]
        rows[37] = [37 * 900000, 101.2, 102.2, 101.0, 102.0, 120.0]
        rows[38] = [38 * 900000, 102.0, 102.8, 101.8, 102.5, 120.0]
        rows[49] = [49 * 900000, 100.0, 100.2, 99.7, 99.9, 100.0]
    else:
        # High-volume bullish candle becomes the bearish OB.
        rows[35] = [35 * 900000, 100.0, 100.5, 99.8, 100.2, volume]
        rows[36] = [36 * 900000, 100.2, 100.3, 98.5, 98.8, 120.0]
        rows[37] = [37 * 900000, 98.8, 99.0, 97.8, 98.0, 120.0]
        rows[38] = [38 * 900000, 98.0, 98.2, 97.2, 97.5, 120.0]
        rows[49] = [49 * 900000, 100.0, 100.3, 99.8, 100.1, 100.0]
    rows.append([50 * 900000, 100.0, 101.0, 99.0, 100.0, 9999.0])
    return rows


def micro_rows(side="BUY"):
    base = 49 * 900000
    if side == "BUY":
        return [
            [base - 180000, 99.65, 99.7, 99.6, 99.68, 10.0],
            [base - 120000, 99.85, 99.9, 99.6, 99.82, 10.0],
            [base - 60000, 99.8, 100.0, 99.75, 99.95, 20.0],
            [base, 99.95, 100.1, 99.9, 100.0, 999.0],
        ]
    return [
        [base - 180000, 100.55, 100.6, 100.5, 100.55, 10.0],
        [base - 120000, 100.25, 100.5, 100.2, 100.3, 10.0],
        [base - 60000, 100.4, 100.45, 100.1, 100.2, 20.0],
        [base, 100.2, 100.3, 100.0, 100.1, 999.0],
    ]


class MarketStrategyTests(unittest.TestCase):
    def test_buy_enters_retested_bullish_order_block_on_one_minute(self):
        signal = analyze("futures", "TESTUSDT", market_rows("BUY"),
                         micro_rows=micro_rows("BUY"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["tp1"], signal["entry"])
        self.assertEqual(signal["stop"], 99.5)
        self.assertEqual(signal["tp1"], 100.2)
        self.assertEqual(signal["stop"], signal["volume_candle_low"])
        self.assertEqual(signal["tp1"], signal["volume_candle_high"])
        self.assertEqual(signal["tp1"], signal["tp2"])
        self.assertEqual(signal["tp2"], signal["tp3"])
        self.assertEqual(signal["timeframe"], "15m / 1m entry")
        self.assertLessEqual(signal["order_block_low"], signal["entry"])
        self.assertGreaterEqual(signal["order_block_high"], signal["entry"])

    def test_sell_enters_retested_bearish_order_block_on_one_minute(self):
        signal = analyze("futures", "TESTUSDT", market_rows("SELL"),
                         micro_rows=micro_rows("SELL"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])
        self.assertEqual(signal["stop"], 100.5)
        self.assertEqual(signal["tp1"], 99.8)
        self.assertEqual(signal["stop"], signal["volume_candle_high"])
        self.assertEqual(signal["tp1"], signal["volume_candle_low"])

    def test_cash_markets_are_long_only(self):
        self.assertIsNone(analyze("spot", "TEST", market_rows("SELL"),
                                  micro_rows=micro_rows("SELL")))
        self.assertIsNone(analyze("saudi", "TEST", market_rows("SELL"),
                                  micro_rows=micro_rows("SELL")))

    def test_no_micro_retest_means_no_trade(self):
        self.assertIsNone(analyze("futures", "TEST", market_rows("BUY"),
                                  micro_rows=micro_rows("SELL")))

    def test_low_volume_order_block_is_rejected(self):
        self.assertIsNone(analyze("futures", "TEST", market_rows("BUY", 110.0),
                                  micro_rows=micro_rows("BUY")))

    def test_every_supported_market_has_a_profile(self):
        self.assertEqual(set(PROFILES), {
            "spot", "alpha", "futures", "us-stocks", "us-contracts", "saudi", "forex"
        })

    def test_unknown_market_is_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", market_rows("BUY"),
                                  micro_rows=micro_rows("BUY")))


if __name__ == "__main__":
    unittest.main()
