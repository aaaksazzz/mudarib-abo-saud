import unittest

from market_strategies import PROFILES, analyze


def candles(side="BUY", volume=220.0):
    rows = []
    for i in range(45):
        rows.append([i * 900000, 99.8, 100.2, 99.5, 100.0, 100.0])
    if side == "BUY":
        rows[-1] = [44 * 900000, 100.1, 103.0, 100.0, 102.8, volume]
    elif side == "SELL":
        rows[-1] = [44 * 900000, 99.9, 100.0, 97.0, 97.2, volume]
    # The final row is still forming and must be ignored.
    rows.append([45 * 900000, 102.8, 104.0, 102.0, 103.5, 9999.0])
    return rows


class MarketStrategyTests(unittest.TestCase):
    def test_buy_uses_body_midpoint_stop_and_staggered_targets(self):
        signal = analyze("futures", "TESTUSDT", candles("BUY"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        midpoint = (100.1 + 102.8) / 2.0
        self.assertLess(signal["stop"], midpoint)
        risk = signal["entry"] - signal["stop"]
        self.assertAlmostEqual(signal["tp1"], signal["entry"] + risk)
        self.assertAlmostEqual(signal["tp2"], signal["entry"] + 2 * risk)
        self.assertAlmostEqual(signal["tp3"], signal["entry"] + 3 * risk)
        self.assertLess(signal["tp1"], signal["tp2"])
        self.assertLess(signal["tp2"], signal["tp3"])
        self.assertAlmostEqual(signal["reward_risk"], 3.0)
        self.assertEqual(signal["timeframe"], "15m")

    def test_sell_uses_body_midpoint_stop_and_staggered_targets(self):
        signal = analyze("futures", "TESTUSDT", candles("SELL"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        midpoint = (99.9 + 97.2) / 2.0
        self.assertGreater(signal["stop"], midpoint)
        risk = signal["stop"] - signal["entry"]
        self.assertAlmostEqual(signal["tp1"], signal["entry"] - risk)
        self.assertAlmostEqual(signal["tp2"], signal["entry"] - 2 * risk)
        self.assertAlmostEqual(signal["tp3"], signal["entry"] - 3 * risk)
        self.assertGreater(signal["tp1"], signal["tp2"])
        self.assertGreater(signal["tp2"], signal["tp3"])

    def test_cash_markets_are_long_only(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertIsNone(analyze(market, "TEST", candles("SELL")))

    def test_derivatives_and_fx_allow_short(self):
        for market in ("futures", "us-contracts", "forex"):
            signal = analyze(market, "TEST", candles("SELL"))
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "SELL")

    def test_low_volume_is_rejected(self):
        self.assertIsNone(analyze("futures", "TESTUSDT", candles("BUY", volume=110.0)))

    def test_each_supported_market_has_a_profile(self):
        self.assertEqual(set(PROFILES), {
            "spot", "alpha", "futures", "us-stocks", "us-contracts", "saudi", "forex"
        })

    def test_unknown_market_is_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("BUY")))


if __name__ == "__main__":
    unittest.main()
