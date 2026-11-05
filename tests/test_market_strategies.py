import unittest

from market_strategies import PROFILES, analyze


def candles(side="BUY"):
    rows = []
    # 100 quiet bars, then a persistent trend to establish EMA/ADX alignment.
    price = 100.0
    for i in range(100):
        if i >= 82:
            price += 0.18 if side == "BUY" else -0.18
        rows.append([
            i * 900000, price - 0.05, price + 0.12,
            price - 0.12, price, 1000.0
        ])
    # Closed breakout candle above/below the prior 55-candle channel.
    if side == "BUY":
        rows[-1] = [99 * 900000, price, price + 1.0, price - 0.05, price + 0.9, 3000.0]
    else:
        rows[-1] = [99 * 900000, price, price + 0.05, price - 1.0, price - 0.9, 3000.0]
    # A still-forming candle is deliberately extreme and must be ignored.
    rows.append([100 * 900000, price, price + 5.0, price - 5.0, price, 99999.0])
    return rows


class DonchianStrategyTests(unittest.TestCase):
    def test_long_breakout_has_distinct_risk_targets(self):
        signal = analyze("futures", "TESTUSDT", candles("BUY"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertAlmostEqual(signal["tp1"], signal["entry"] + risk)
        self.assertAlmostEqual(signal["tp2"], signal["entry"] + 2 * risk)
        self.assertAlmostEqual(signal["tp3"], signal["entry"] + 3 * risk)
        self.assertLess(signal["tp1"], signal["tp2"])
        self.assertLess(signal["tp2"], signal["tp3"])
        self.assertEqual(signal["timeframe"], "15m")

    def test_short_breakout_has_distinct_risk_targets(self):
        signal = analyze("futures", "TESTUSDT", candles("SELL"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        risk = signal["stop"] - signal["entry"]
        self.assertAlmostEqual(signal["tp1"], signal["entry"] - risk)
        self.assertAlmostEqual(signal["tp2"], signal["entry"] - 2 * risk)
        self.assertAlmostEqual(signal["tp3"], signal["entry"] - 3 * risk)
        self.assertGreater(signal["tp1"], signal["tp2"])
        self.assertGreater(signal["tp2"], signal["tp3"])

    def test_spot_and_cash_markets_never_short(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertFalse(PROFILES[market]["allow_short"])
            self.assertIsNone(analyze(market, "TEST", candles("SELL")))

    def test_derivatives_and_forex_can_short(self):
        for market in ("futures", "us-contracts", "forex"):
            self.assertTrue(PROFILES[market]["allow_short"])
            signal = analyze(market, "TEST", candles("SELL"))
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "SELL")

    def test_unknown_market_is_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("BUY")))


if __name__ == "__main__":
    unittest.main()
