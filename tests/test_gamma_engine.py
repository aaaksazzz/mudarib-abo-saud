import unittest

from gamma_engine import analyse_liquidity_candidate


def make_bars():
    bars = []
    for i in range(25):
        base = 100 + (i % 3) * 0.05
        bars.append({"open": base, "high": base + 1, "low": base - 1,
                     "close": base + 0.1, "volume": 100, "time": i})
    return bars


class GammaLiquidityEngineTests(unittest.TestCase):
    def test_buy_sweep_returns_complete_levels(self):
        bars = make_bars()
        bars[-1] = {"open": 99.4, "high": 100.2, "low": 96.5,
                    "close": 99.9, "volume": 300, "time": 24}
        result = analyse_liquidity_candidate(bars, 99.9, "BUY")
        self.assertIsNotNone(result)
        self.assertLess(result["stop_loss"], result["entry"])
        self.assertLess(result["entry"], result["tp1"])
        self.assertLess(result["tp1"], result["tp2"])
        self.assertLess(result["tp2"], result["tp3"])
        self.assertIsNone(result["gamma_exposure"])

    def test_no_sweep_or_absorption_means_no_trade(self):
        bars = make_bars()
        bars[-1] = {"open": 100.0, "high": 100.2, "low": 99.8,
                    "close": 100.1, "volume": 100, "time": 24}
        self.assertIsNone(analyse_liquidity_candidate(bars, 100.1, "BUY"))

    def test_sell_sweep_returns_sell_levels(self):
        bars = make_bars()
        bars[-1] = {"open": 100.6, "high": 103.5, "low": 99.8,
                    "close": 100.1, "volume": 300, "time": 24}
        result = analyse_liquidity_candidate(bars, 100.1, "SELL")
        self.assertIsNotNone(result)
        self.assertGreater(result["stop_loss"], result["entry"])
        self.assertGreater(result["entry"], result["tp1"])
        self.assertGreater(result["tp1"], result["tp2"])
        self.assertGreater(result["tp2"], result["tp3"])


if __name__ == "__main__":
    unittest.main()

 
def test_recent_local_sweep_can_generate_confirmed_setup():
    rows = []
    for i in range(24):
        rows.append({"open": 100.0, "high": 101.0, "low": 99.0,
                     "close": 100.2, "volume": 100.0})
    rows.append({"open": 99.4, "high": 100.1, "low": 98.7,
                 "close": 99.9, "volume": 140.0})
    from gamma_engine import analyse_liquidity_candidate
    result = analyse_liquidity_candidate(rows, 99.9, "BUY", "spot")
    assert result is not None
    assert result["side"] == "BUY"
    assert result["stop_loss"] < result["entry"]
    assert result["tp1"] > result["entry"]
    assert result["liquidity_event"] == "سحب سيولة بيع واسترداد"
