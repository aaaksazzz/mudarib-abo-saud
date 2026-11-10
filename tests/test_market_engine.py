import unittest
from market_engine import MarketEngine

class MarketEngineTests(unittest.TestCase):
    def make_candles(self, count=210, bullish=True):
        rows = []
        for i in range(count):
            close = 100 + i * 0.1 if bullish else 200 - i * 0.1
            rows.append({
                "t": i * 60,
                "o": close - 0.05 if bullish else close + 0.05,
                "h": close + 0.2,
                "l": close - 0.2,
                "c": close,
                "v": 1000,
            })
        return rows

    def test_scan_uses_requested_timeframe(self):
        engine = MarketEngine()
        requested = []
        candles = self.make_candles()
        def fake_candles(market, symbol, timeframe):
            requested.append(timeframe)
            return candles
        engine._candles = fake_candles
        result = engine._analyze("spot", {"symbol": "BTCUSDT"}, "1h")
        self.assertIn("1h", requested)
        self.assertEqual(result["signal"]["timeframe"], "1h")

    def test_target_is_three_times_structural_risk(self):
        engine = MarketEngine()
        candles = self.make_candles()
        engine._candles = lambda market, symbol, timeframe: candles
        signal = engine._signal("spot", "BTCUSDT", "15m", "صاعد")
        self.assertIsNotNone(signal)
        risk = signal["entry"] - signal["stop"]
        reward = signal["target"] - signal["entry"]
        self.assertAlmostEqual(reward / risk, 3.0, places=6)

    def test_options_are_not_misrepresented_as_underlying_stocks(self):
        engine = MarketEngine()
        with self.assertRaises(ValueError):
            engine.scan("us_options", "15m")

    def test_monthly_timeframe_is_supported(self):
        self.assertIn("1M", MarketEngine().market_overview()["timeframes"])

if __name__ == "__main__":
    unittest.main()
