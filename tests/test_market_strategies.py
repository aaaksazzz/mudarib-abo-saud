import unittest

from market_strategies import analyze


def candles(side="BUY", volume=220.0):
    rows = []
    # Stable 15m history with a narrow range and consistent volume.
    for i in range(45):
        close = 100.0
        rows.append([i * 900000, 99.8, 100.2, 99.5, close, 100.0])
    if side == "BUY":
        rows[-1] = [44 * 900000, 100.1, 103.0, 100.0, 102.8, volume]
    elif side == "SELL":
        rows[-1] = [44 * 900000, 99.9, 100.0, 97.0, 97.2, volume]
    # Final row models the still-forming candle and must be ignored.
    rows.append([45 * 900000, 102.8, 104.0, 102.0, 103.5, 9999.0])
    return rows


class MarketStrategyTests(unittest.TestCase):
    def test_crypto_buy_signal_uses_dive_atr_stop_and_targets(self):
        signal = analyze("futures", "TESTUSDT", candles("BUY"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        atr = risk / 1.5
        self.assertAlmostEqual(signal["risk_atr"], 1.5)
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], atr)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], 2 * atr)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], 3 * atr)
        self.assertAlmostEqual(signal["reward_risk"], 2.0)
        self.assertEqual(signal["timeframe"], "15m")

    def test_spot_does_not_emit_short(self):
        self.assertIsNone(analyze("spot", "TESTUSDT", candles("SELL")))

    def test_futures_can_emit_short(self):
        signal = analyze("futures", "TESTUSDT", candles("SELL"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        risk = signal["stop"] - signal["entry"]
        atr = risk / 1.5
        self.assertAlmostEqual(signal["risk_atr"], 1.5)
        self.assertAlmostEqual(signal["entry"] - signal["tp1"], atr)
        self.assertAlmostEqual(signal["entry"] - signal["tp2"], 2 * atr)
        self.assertAlmostEqual(signal["entry"] - signal["tp3"], 3 * atr)

    def test_low_volume_is_rejected(self):
        self.assertIsNone(analyze("futures", "TESTUSDT", candles("BUY", volume=110.0)))

    def test_unknown_market_is_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("BUY")))


if __name__ == "__main__":
    unittest.main()
