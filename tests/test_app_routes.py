import unittest
import app as platform

class RebuildApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = platform.app.test_client()

    def test_independent_sections_render(self):
        for path in ("/", "/markets", "/portfolio", "/news", "/blog", "/alerts", "/account"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"SMART TRADING PRO", response.data)

    def test_each_market_has_its_own_page(self):
        for market in platform.MARKETS:
            with self.subTest(market=market):
                response = self.client.get("/markets/" + market)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"MARKET WORKSPACE", response.data)

    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_unknown_market_is_rejected(self):
        self.assertEqual(self.client.get("/markets/not-a-market").status_code, 404)

if __name__ == "__main__":
    unittest.main()
