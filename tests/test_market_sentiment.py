import unittest

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
