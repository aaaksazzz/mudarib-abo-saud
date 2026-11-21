import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ["ENABLE_AUTO_SCAN"] = "false"

import app as platform_app
import us_day_trader_strategy as strategy


class USDayTraderStrategyTests(unittest.TestCase):
    def test_engine_is_limited_to_us_stocks_and_contracts(self):
        self.assertEqual(set(strategy.MARKETS), {"us-stocks", "us-contracts"})
        self.assertEqual(strategy.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))

    def test_targets_are_one_two_three_r(self):
        self.assertEqual(strategy.target_prices(100, "BUY", 98), (102, 104, 106))
        self.assertEqual(strategy.target_prices(100, "SELL", 102), (98, 96, 94))
        self.assertIsNone(strategy.target_prices(100, "BUY", 101))

    def test_opening_range_breakout_uses_ny_regular_session_and_volume(self):
        ny = ZoneInfo("America/New_York")
        bars = []
        # Twenty prior completed candles establish an ordinary volume baseline.
        for index in range(20):
            stamp = int(datetime(2026, 11, 20, 10, index, tzinfo=ny).timestamp() * 1000)
            bars.append({"time": stamp, "open": 100, "high": 100.5,
                         "low": 99.5, "close": 100, "volume": 10})
        for minute, op, high, low, close, volume in (
            (570, 100, 101, 99, 100.5, 10),
            (585, 100.5, 100.9, 99.8, 100.8, 10),
            (600, 100.9, 102.2, 100.7, 102, 60),
        ):
            stamp = int(datetime(2026, 11, 23, minute // 60, minute % 60, tzinfo=ny).timestamp() * 1000)
            bars.append({"time": stamp, "open": op, "high": high, "low": low,
                         "close": close, "volume": volume})
        result = strategy._opening_range_setup(bars, "15m")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "OPENING_RANGE_BREAKOUT")
        self.assertEqual(result["side"], "BUY")

    def test_analyze_emits_confirmed_setup_and_three_r_exit_plan(self):
        rows = []
        for index in range(51):
            price = 100 + index * 0.01
            rows.append([index * 900000, price, price + 1, price - 1, price + 0.2, 100])
        with patch.object(strategy, "_opening_range_setup",
                          return_value={"side": "BUY", "name": "OPENING_RANGE_BREAKOUT",
                                        "level": 100.5, "score": 86}), \
             patch.object(strategy, "_flag_setup", return_value=None), \
             patch.object(strategy, "_oversold_bounce_setup", return_value=None), \
             patch.object(strategy, "_breakout_setup", return_value=None):
            signal = strategy.analyze("us-stocks", "AAPL", rows, "15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["strategy_fingerprint"], strategy.STRATEGY_FINGERPRINT)
        self.assertEqual(signal["reward_risk"], 3.0)
        self.assertEqual(signal["setup_type"], "OPENING_RANGE_BREAKOUT")
        self.assertIn("CLOSED_CANDLE_ENTRY_TIMING", signal["confirmations"])
        self.assertIn("EXIT_PLAN_1R_2R_3R", signal["confirmations"])
        self.assertIn("HISTORICAL_REPLAY_TRACKING", signal["confirmations"])

    def test_engine_diagnostic_self_test(self):
        result = strategy.diagnostic_self_test()
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["strategies"]), 8)

    def test_application_routes_only_us_markets_to_new_engine(self):
        self.assertIs(platform_app.strategy_engine_for_market("us-stocks"), strategy)
        self.assertIs(platform_app.strategy_engine_for_market("us-contracts"), strategy)
        self.assertIs(platform_app.strategy_engine_for_market("spot"), platform_app.breakout_50_strategy)

    def test_build_signal_publishes_us_engine_fingerprint(self):
        rows = [[i * 900000, 100, 101, 99, 100.2, 100] for i in range(51)]
        payload = {
            "market": "us-stocks", "symbol": "AAPL", "side": "BUY",
            "entry": 100.2, "stop": 99.2, "tp1": 101.2, "tp2": 102.2, "tp3": 103.2,
            "score": 86, "timeframe": "15m", "signal_candle_time": rows[-2][0],
            "atr": 2, "risk_pct": 1, "risk_distance": 1, "reward_risk": 3,
            "strategy_names": ["OPENING_RANGE_BREAKOUT", "CLOSED_CANDLE_ENTRY_TIMING"],
            "confirmations": ["OPENING_RANGE_BREAKOUT", "CLOSED_CANDLE_ENTRY_TIMING"],
            "reason": "test setup",
        }
        with patch.object(platform_app, "klines", return_value=rows), \
             patch.object(strategy, "analyze", return_value=payload.copy()):
            result = platform_app.build_signal("us-stocks", {"symbol": "AAPL"}, "15m")
        self.assertEqual(result["strategy_fingerprint"], strategy.STRATEGY_FINGERPRINT)
        self.assertTrue(result["reason"].startswith(platform_app.US_DAY_TRADER_REASON_PREFIX))
        self.assertEqual(result["strategy_total"], 8)


if __name__ == "__main__":
    unittest.main()
