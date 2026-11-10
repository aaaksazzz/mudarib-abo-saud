import unittest
import app as application

class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        application.app.config["TESTING"] = True
        self.client = application.app.test_client()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_home(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_market_list(self):
        response = self.client.get("/api/markets")
        self.assertEqual(response.status_code, 200)
        ids = {m["id"] for m in response.get_json()["markets"]}
        self.assertTrue({"spot", "futures", "us_stocks", "us_options", "saudi", "forex"}.issubset(ids))

if __name__ == "__main__":
    unittest.main()
