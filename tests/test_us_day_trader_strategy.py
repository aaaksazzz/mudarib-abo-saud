import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENABLE_AUTO_SCAN", "false")

import app as platform_app
import breakout_50_strategy as active_strategy
import us_day_trader_strategy as retired_strategy


class UnifiedMarketStrategyTests(unittest.TestCase):
    def test_every_market_uses_the_single_false_breakout_engine(self):
        for market in active_strategy.MARKETS:
            with self.subTest(market=market):
                self.assertIs(platform_app.strategy_engine_for_market(market), active_strategy)
                self.assertEqual(platform_app.strategy_engine_name(market), active_strategy.STRATEGY_NAME)
                self.assertEqual(platform_app.strategy_reason_prefix(market), platform_app.BREAKOUT_REASON_PREFIX)

    def test_active_engine_supports_all_markets_and_timeframes(self):
        self.assertEqual(len(active_strategy.MARKETS), 7)
        self.assertEqual(active_strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertTrue(active_strategy.diagnostic_self_test()["ok"])

    def test_legacy_us_engine_is_not_selected_for_live_signals(self):
        self.assertTrue(set(retired_strategy.MARKETS).issubset(set(active_strategy.MARKETS)))
        self.assertIsNot(platform_app.strategy_engine_for_market("us-stocks"), retired_strategy)
        self.assertIsNot(platform_app.strategy_engine_for_market("us-contracts"), retired_strategy)

    def test_us_stock_signal_uses_active_engine_fingerprint(self):
        rows = [[i * 900000, 100, 101, 99, 100.2, 100] for i in range(51)]
        payload = {
            "market": "us-stocks", "symbol": "AAPL", "side": "BUY",
            "entry": 100.2, "stop": 99.2, "tp1": 101.2, "tp2": 102.2, "tp3": 103.2,
            "score": 88, "timeframe": "15m", "signal_candle_time": rows[-2][0],
            "atr": 2, "risk_pct": 1, "risk_distance": 1, "reward_risk": 3,
            "strategy_names": ["CLOSED_CANDLE_ENTRY_TIMING"],
            "confirmations": ["CLOSED_CANDLE_ENTRY_TIMING"],
            "reason": "test setup",
        }
        with patch.object(platform_app, "klines", return_value=rows), \
             patch.object(active_strategy, "analyze", return_value=payload.copy()):
            result = platform_app.build_signal("us-stocks", {"symbol": "AAPL"}, "15m")
        self.assertEqual(result["strategy_fingerprint"], active_strategy.STRATEGY_FINGERPRINT)
        self.assertTrue(result["reason"].startswith(platform_app.BREAKOUT_REASON_PREFIX))
        self.assertEqual(result["strategy_total"], 7)


if __name__ == "__main__":
    unittest.main()
