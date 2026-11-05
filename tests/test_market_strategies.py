import unittest

from market_strategies import PROFILES, TIMEFRAMES, analyze


def candles(direction="UP"):
    rows = []
    price = 100.0
    for i in range(100):
        if direction == "UP":
            price += 0.35 if i % 7 else 0.22
        else:
            price -= 0.30 if i % 7 else 0.18
        high, low = price + 0.18, price - 0.18
        volume = 3000.0 if i == 99 else 1000.0
        if i == 99:
            high = price + 0.30
            low = price - 0.08 if direction == "UP" else price - 0.30
        rows.append([i * 900000, price - 0.1, high, low, price, volume])
    # Forming candle is deliberately extreme and must be ignored.
    rows.append([100 * 900000, price, price * 1.2, price * 0.8, price, 99999.0])
    return rows


class MultiTimeframeEnsembleTests(unittest.TestCase):
    def test_all_six_timeframes_are_independent_profiles(self):
        self.assertEqual(TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        for timeframe in TIMEFRAMES:
            signal = analyze("futures", "TEST", candles("UP"), timeframe=timeframe)
            self.assertIsNotNone(signal, timeframe)
            self.assertEqual(signal["timeframe"], timeframe)

    def test_long_signal_has_one_risk_two_targets_and_three_r_final_target(self):
        signal = analyze("futures", "TEST", candles("UP"), timeframe="15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], risk)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], risk * 2)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], risk * 3)
        self.assertGreaterEqual(signal["confirmations"], 2)
        self.assertLessEqual(signal["score"], 96)

    def test_short_signals_only_on_markets_that_allow_shorting(self):
        signal = analyze("futures", "TEST", candles("DOWN"), timeframe="1h")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "SELL")
        self.assertGreater(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["entry"])
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            self.assertIsNone(analyze(market, "TEST", candles("DOWN"), timeframe="1h"))

    def test_cash_markets_can_generate_buy_signals(self):
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            signal = analyze(market, "TEST", candles("UP"), timeframe="4h")
            self.assertIsNotNone(signal, market)
            self.assertEqual(signal["side"], "BUY")

    def test_forming_candle_does_not_change_signal(self):
        rows = candles("UP")
        original = analyze("futures", "TEST", rows, timeframe="1d")
        rows[-1] = [rows[-1][0], 1000, 5000, 1, 2, 1e12]
        changed = analyze("futures", "TEST", rows, timeframe="1d")
        self.assertEqual(original, changed)

    def test_unknown_market_and_timeframe_are_rejected(self):
        self.assertIsNone(analyze("unknown", "TEST", candles("UP"), timeframe="15m"))
        self.assertIsNone(analyze("futures", "TEST", candles("UP"), timeframe="3m"))


if __name__ == "__main__":
    unittest.main()
