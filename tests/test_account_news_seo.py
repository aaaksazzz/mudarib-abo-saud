import os
import unittest
import uuid
from unittest.mock import patch

os.environ["ENABLE_AUTO_SCAN"] = "false"

import app as platform_app


class AccountNewsSeoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform_app.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        with platform_app.app.app_context():
            platform_app.db.create_all()

    def setUp(self):
        self.client = platform_app.app.test_client()
        self.base_url = "https://localhost"
        self.email = "test-" + uuid.uuid4().hex + "@example.com"

    def tearDown(self):
        with platform_app.app.app_context():
            user = platform_app.User.query.filter_by(email=self.email).first()
            if user:
                platform_app.db.session.delete(user)
            article = platform_app.Article.query.filter_by(slug=getattr(self, "slug", "")).first()
            if article:
                platform_app.db.session.delete(article)
            platform_app.db.session.commit()

    def csrf(self):
        response = self.client.get("/api/bootstrap", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf"]

    def test_register_creates_account_and_keeps_authenticated_session(self):
        token = self.csrf()
        response = self.client.post(
            "/api/auth/register",
            base_url=self.base_url,
            json={"email": self.email, "password": "StrongPassword123"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user"]["email"], self.email)
        me = self.client.get("/api/me", base_url=self.base_url)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["email"], self.email)

    def test_login_rejects_bad_credentials_and_accepts_valid_credentials(self):
        with platform_app.app.app_context():
            user = platform_app.User(
                email=self.email,
                password_hash=platform_app.generate_password_hash("StrongPassword123"),
                role="user",
            )
            platform_app.db.session.add(user)
            platform_app.db.session.commit()
        token = self.csrf()
        bad = self.client.post(
            "/api/auth/login",
            base_url=self.base_url,
            json={"email": self.email, "password": "WrongPassword123"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(bad.status_code, 401)
        good = self.client.post(
            "/api/auth/login",
            base_url=self.base_url,
            json={"email": self.email.upper(), "password": "StrongPassword123"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(good.status_code, 200, good.get_json())
        self.assertEqual(self.client.get("/api/me", base_url=self.base_url).status_code, 200)

    def test_live_news_endpoint_uses_feed_and_returns_items(self):
        item = {"title": "Market update", "url": "https://example.com/news", "source": "Example", "published_at": ""}
        with patch.object(platform_app, "_cached_google_news", return_value=[item]):
            response = self.client.get("/api/news?lang=en", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        item = response.get_json()["items"][0]
        self.assertEqual(item["title"], "Market update")
        self.assertNotIn("url", item)
        self.assertIn(item["direction"], ("BUY", "SELL", "NEUTRAL"))
        self.assertEqual(response.get_json()["delivery"], "in_app_only")

    def test_news_headline_sentiment_distinguishes_negative_positive_and_neutral(self):
        negative = platform_app.classify_news_headline("Bitcoin price crash as market losses deepen")
        positive = platform_app.classify_news_headline("Bitcoin rally brings strong gains to crypto market")
        neutral = platform_app.classify_news_headline("Central bank publishes weekly market calendar")
        self.assertEqual(negative["direction"], "SELL")
        self.assertEqual(negative["sentiment"], "negative")
        self.assertEqual(positive["direction"], "BUY")
        self.assertEqual(positive["sentiment"], "positive")
        self.assertEqual(neutral["direction"], "NEUTRAL")
        self.assertEqual(neutral["sentiment"], "neutral")

    def test_blog_article_has_search_metadata_and_is_in_sitemap(self):
        self.slug = "seo-test-" + uuid.uuid4().hex
        with platform_app.app.app_context():
            article = platform_app.Article(
                kind="blog",
                title="Trading Risk Management",
                slug=self.slug,
                summary="A practical guide to trading risk.",
                body="Position sizing and stop placement matter.",
                published=True,
                language="en",
                meta_title="Trading Risk Management Guide",
                meta_description="Learn practical risk controls for active traders.",
                canonical_slug=self.slug,
            )
            platform_app.db.session.add(article)
            platform_app.db.session.commit()
        response = self.client.get("/blog/" + self.slug, base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="description"', response.data)
        self.assertIn(b'application/ld+json', response.data)
        sitemap = self.client.get("/sitemap.xml", base_url=self.base_url)
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn(self.slug.encode(), sitemap.data)

    def test_system_status_does_not_expose_credentials(self):
        response = self.client.get("/api/system/status", base_url=self.base_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ADMIN_PASSWORD", response.get_json())
        self.assertNotIn("SECRET_KEY", response.get_json())

    def test_every_market_has_six_independent_timeframes(self):
        expected = ("15m", "1h", "4h", "1d", "1w", "1M")
        self.assertEqual(platform_app.market_strategies.TIMEFRAMES, expected)
        for market in platform_app.MARKETS:
            self.assertEqual(platform_app.market_scan_timeframes(market), expected)
        self.assertEqual(platform_app.market_strategies.SIGNAL_TIMEFRAME,
                         {frame: frame for frame in expected})

    def test_build_signal_rejects_short_candle_provider_response(self):
        with patch.object(platform_app, "klines", return_value=[[i, 100, 101, 99, 100, 10] for i in range(40)]):
            with self.assertRaisesRegex(ValueError, "Insufficient candles"):
                platform_app.build_signal("futures", {"symbol": "TESTUSDT"}, "15m")

    def test_fresh_signal_preserves_previous_swing_target_and_rebases_extensions(self):
        now = platform_app.utcnow()
        signal = {
            "symbol": "TESTUSDT", "side": "BUY", "timeframe": "15m",
            "signal_candle_time": int(now.timestamp() * 1000) - 900000,
            "entry": 100.0, "stop": 99.0, "tp1": 101.0, "tp2": 102.0,
            "tp3": 103.0, "atr": 1.0,
        }
        accepted, rejected = platform_app.filter_fresh_signals(
            [signal], [{"symbol": "TESTUSDT", "price": 100.1}], now
        )
        self.assertEqual(rejected["rejected_late_price"], 0)
        self.assertEqual(len(accepted), 1)
        self.assertAlmostEqual(accepted[0]["entry"], 100.1)
        self.assertAlmostEqual(accepted[0]["tp1"], 101.0)
        self.assertAlmostEqual(accepted[0]["tp2"], 102.3)
        self.assertAlmostEqual(accepted[0]["tp3"], 103.4)
        self.assertEqual(accepted[0]["entry_price_source"], "live_market_quote")

    def test_fresh_signal_is_rejected_if_live_price_crossed_structural_stop(self):
        now = platform_app.utcnow()
        signal = {
            "symbol": "TESTUSDT", "side": "BUY", "timeframe": "15m",
            "signal_candle_time": int(now.timestamp() * 1000) - 900000,
            "entry": 100.0, "stop": 99.0, "tp1": 101.0,
            "tp2": 102.0, "tp3": 103.0, "atr": 1.0,
        }
        accepted, rejected = platform_app.filter_fresh_signals(
            [signal], [{"symbol": "TESTUSDT", "price": 98.9}], now
        )
        self.assertEqual(accepted, [])
        self.assertEqual(rejected["rejected_late_price"], 1)



if __name__ == "__main__":
    unittest.main()
