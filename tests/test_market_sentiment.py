import unittest
from unittest.mock import patch

import market_sentiment


class PublicSentimentTests(unittest.TestCase):
    def test_headline_direction_is_conservative(self):
        self.assertEqual(market_sentiment._headline_score("Bitcoin rallies as inflows rise"), 1)
        self.assertEqual(market_sentiment._headline_score("Gold falls after selloff"), -1)
        self.assertEqual(market_sentiment._headline_score("Markets trade sideways today"), 0)

    def test_publisher_weighting(self):
        self.assertGreater(
            market_sentiment._publisher_weight("Reuters"),
            market_sentiment._publisher_weight("Unknown Blog"),
        )

    def test_scan_rotates_through_the_full_universe(self):
        market = "test-rotation"
        market_sentiment._cache.pop(market, None)
        market_sentiment._cursor[market] = 0
        universe = [
            {"symbol": "AAA", "quote_volume": 500},
            {"symbol": "BBB", "quote_volume": 400},
            {"symbol": "CCC", "quote_volume": 300},
            {"symbol": "DDD", "quote_volume": 200},
            {"symbol": "EEE", "quote_volume": 100},
        ]
        neutral = {"side": "NEUTRAL", "mentions": 0, "source_errors": []}
        with patch.object(market_sentiment, "collect_sentiment", return_value=neutral):
            first = market_sentiment.scan_market(market, universe, lambda *_: [], limit=2)
            market_sentiment._cache[market] = (0, first)
            second = market_sentiment.scan_market(market, universe, lambda *_: [], limit=2)
        self.assertEqual(first["scan_offset"], 0)
        self.assertEqual(second["scan_offset"], 2)
        self.assertEqual(first["checked_assets"], 2)
        self.assertEqual(first["universe_total"], 5)

    def test_daily_levels_have_three_to_one_final_reward_risk(self):
        rows = []
        for i in range(22):
            close = 100 + i * 0.35
            rows.append([i * 86400000, close - 0.1, close + 0.45, close - 0.45, close, 1000])
        levels = market_sentiment.technical_levels(
            "us-stocks", "TEST", "BUY", lambda *_args, **_kwargs: rows
        )
        self.assertIsNotNone(levels)
        risk = levels["entry"] - levels["stop"]
        reward = levels["tp3"] - levels["entry"]
        self.assertGreater(risk, 0)
        self.assertAlmostEqual(reward / risk, 3.0, places=6)
        self.assertEqual(levels["reward_risk_tp3"], 3.0)

    def test_short_levels_are_directionally_valid(self):
        rows = []
        for i in range(22):
            close = 120 - i * 0.25
            rows.append([i * 86400000, close + 0.1, close + 0.45, close - 0.45, close, 1000])
        levels = market_sentiment.technical_levels(
            "futures", "TESTUSDT", "SELL", lambda *_args, **_kwargs: rows
        )
        self.assertIsNotNone(levels)
        self.assertGreater(levels["stop"], levels["entry"])
        self.assertLess(levels["tp3"], levels["entry"])
        self.assertAlmostEqual(
            (levels["entry"] - levels["tp3"]) / (levels["stop"] - levels["entry"]),
            3.0, places=6
        )


if __name__ == "__main__":
    unittest.main()
