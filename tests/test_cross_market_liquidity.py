import unittest
from gamma_engine import analyse_liquidity_candidate


def make_bars():
    bars = []
    for i in range(25):
        base = 100 + (i % 3) * 0.05
        bars.append({"open": base, "high": base + 1, "low": base - 1,
                     "close": base + 0.1, "volume": 100, "time": i})
    return bars


class CrossMarketLiquidityEngineTests(unittest.TestCase):
    def test_crypto_buy_sweep_has_complete_r_levels(self):
        bars = make_bars()
        bars[-1] = {"open": 99.4, "high": 100.2, "low": 96.5, "close": 99.9, "volume": 300, "time": 24}
        result = analyse_liquidity_candidate(bars, 99.9, "BUY", "spot")
        self.assertIsNotNone(result)
        self.assertLess(result["stop_loss"], result["entry"])
        self.assertTrue(result["entry"] < result["tp1"] < result["tp2"] < result["tp3"])
        self.assertEqual(result["volume_source"], "base_asset_volume")
        self.assertIsNone(result["gamma_exposure"])

    def test_futures_sell_sweep(self):
        bars = make_bars()
        bars[-1] = {"open": 100.6, "high": 103.5, "low": 99.8, "close": 100.1, "volume": 300, "time": 24}
        result = analyse_liquidity_candidate(bars, 100.1, "SELL", "futures")
        self.assertIsNotNone(result)
        self.assertGreater(result["stop_loss"], result["entry"])
        self.assertEqual(result["volume_source"], "contract_base_volume")

    def test_forex_tick_volume_uses_relative_baseline(self):
        bars = make_bars()
        bars[-1] = {"open": 99.4, "high": 100.2, "low": 96.5, "close": 99.9, "volume": 120, "time": 24}
        result = analyse_liquidity_candidate(bars, 99.9, "BUY", "forex")
        self.assertIsNotNone(result)
        self.assertEqual(result["volume_source"], "tick_volume")

    def test_equity_requires_stronger_relative_volume(self):
        bars = make_bars()
        bars[-1] = {"open": 99.4, "high": 100.2, "low": 96.5, "close": 99.9, "volume": 110, "time": 24}
        self.assertIsNone(analyse_liquidity_candidate(bars, 99.9, "BUY", "us"))

    def test_zero_volume_never_creates_signal(self):
        bars = make_bars()
        for bar in bars:
            bar["volume"] = 0
        self.assertIsNone(analyse_liquidity_candidate(bars, 99.9, "BUY", "forex"))

    def test_no_sweep_or_absorption_means_no_trade(self):
        bars = make_bars()
        bars[-1] = {"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.1, "volume": 100, "time": 24}
        self.assertIsNone(analyse_liquidity_candidate(bars, 100.1, "BUY"))


if __name__ == "__main__":
    unittest.main()
