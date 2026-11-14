import unittest

from strategy_research import (
    StrategySpec, backtest_signals, chronological_splits,
    qualification_score, validate_catalog,
)


class StrategyResearchTests(unittest.TestCase):
    def _bars(self):
        return [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 100, "high": 102, "low": 99, "close": 101},
            {"open": 101, "high": 106, "low": 100, "close": 105},
            {"open": 105, "high": 106, "low": 104, "close": 105},
        ]

    def test_next_bar_entry_and_target_exit(self):
        result = backtest_signals(self._bars(), [
            {"index": 0, "side": "BUY", "stop": 98, "target": 104}
        ], fee_bps=0, slippage_bps=0)
        self.assertEqual(result["metrics"]["trades"], 1)
        self.assertGreater(result["metrics"]["net_return_pct"], 0)

    def test_stop_first_when_stop_and_target_touch_same_bar(self):
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 100, "high": 106, "low": 97, "close": 102},
            {"open": 100, "high": 101, "low": 99, "close": 100},
        ]
        result = backtest_signals(bars, [
            {"index": 0, "side": "BUY", "stop": 98, "target": 104}
        ], fee_bps=0, slippage_bps=0)
        self.assertLess(result["metrics"]["net_return_pct"], 0)

    def test_catalog_detects_logic_duplicates(self):
        a = StrategySpec("A", "A", "trend", "x", "close>ema", "close<ema", ("spot",), ("1h",))
        b = StrategySpec("B", "B", "trend", "y", "close>ema", "close<ema", ("spot",), ("1h",))
        result = validate_catalog([a, b])
        self.assertFalse(result["ok"])
        self.assertEqual(result["unique_logic"], 1)

    def test_chronological_splits_do_not_shuffle(self):
        rows = list(range(100))
        parts = chronological_splits(rows)
        self.assertEqual(parts["train"][0], 0)
        self.assertEqual(parts["test"][-1], 99)

    def test_weak_oos_result_is_not_qualified(self):
        self.assertFalse(qualification_score({
            "trades": 100, "net_return_pct": -2, "profit_factor": 0.9,
            "max_drawdown_pct": 10,
        })["eligible"])


if __name__ == "__main__":
    unittest.main()
