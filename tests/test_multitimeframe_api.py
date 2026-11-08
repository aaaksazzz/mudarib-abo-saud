import os
import unittest

os.environ.setdefault("ENABLE_AUTO_SCAN", "false")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///ci-market-tests.db")

import app as platform


class MultiTimeframeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform.app.config.update(TESTING=True)
        cls.client = platform.app.test_client()

    def test_provider_advertises_all_independent_timeframes(self):
        data = self.client.get("/api/markets").get_json()
        self.assertTrue(data["ok"])
        for market in data["markets"]:
            self.assertEqual(
                market["provider"]["timeframes"],
                ["15m","1h","4h","1d","1w","1M"],
            )

    def test_signal_endpoint_rejects_unknown_timeframe(self):
        response = self.client.get("/api/markets/futures/signals?timeframe=30m")
        self.assertEqual(response.status_code, 400)

    def test_signal_endpoint_accepts_each_independent_timeframe(self):
        for timeframe in ("15m","1h","4h","1d","1w","1M"):
            response = self.client.get("/api/markets/futures/signals?timeframe=" + timeframe)
            self.assertEqual(response.status_code, 200, timeframe)
            self.assertEqual(response.get_json()["timeframe"], timeframe)
            self.assertEqual(response.get_json()["timeframes"], ["15m","1h","4h","1d","1w","1M"])


if __name__ == "__main__":
    unittest.main()
