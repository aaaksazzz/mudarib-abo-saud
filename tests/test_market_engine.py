import os
import unittest
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("ENABLE_AUTO_SCAN", "false")
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///ci-market-tests.db")

import app as platform


def candle_rows(closes):
    rows = []
    for index, close in enumerate(closes):
        rows.append([index, close, close * 1.01, close * 0.99, close, 1000, index + 1, 0, 0, 0, 0, 0])
    return rows


class MarketEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform.app.config.update(TESTING=True)
        cls.client = platform.app.test_client()

    def setUp(self):
        with platform.app.app_context():
            platform.db.drop_all()
            platform.db.create_all()

    def test_health_and_readiness_distinguish_liveness_from_scheduler(self):
        health = self.client.get("/health")
        ready = self.client.get("/ready")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["ok"])
        self.assertEqual(ready.status_code, 503)
        self.assertTrue(ready.get_json()["checks"]["database"])
        self.assertFalse(ready.get_json()["checks"]["persistent_database"])
        self.assertTrue(ready.get_json()["checks"]["persistent_secret"])
        self.assertFalse(ready.get_json()["checks"]["market_scheduler"])

    def test_public_signal_read_does_not_start_synchronous_scan(self):
        with patch.object(platform, "run_market_scan", side_effect=AssertionError("HTTP request must not scan")) as scan:
            response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["signals"], [])
        scan.assert_not_called()

    def test_external_market_failure_never_returns_fabricated_data(self):
        with patch.object(platform.market_adapters, "market_tickers", side_effect=RuntimeError("provider unavailable")):
            response = self.client.get("/api/markets/saudi/snapshot")
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.get_json()["ok"])
        signals = self.client.get("/api/markets/saudi/signals").get_json()
        self.assertEqual(signals["signals"], [])
        self.assertFalse(signals["scan_ready"])

    def test_journal_expires_old_active_trades(self):
        with platform.app.app_context():
            trade = platform.Trade(
                market="spot", symbol="BTCUSDT", side="BUY", entry=100,
                stop=97, tp1=103, tp2=106, tp3=109, score=70,
                timeframe="15m", reason="test",
                expires_at=platform.utcnow() - timedelta(minutes=1),
            )
            platform.db.session.add(trade)
            platform.db.session.commit()
        response = self.client.get("/api/trades")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["trades"][0]["status"], "expired")

    def test_price_action_signal_uses_4h_structure_and_15m_liquidity_sweep(self):
        four_hour = []
        for i in range(60):
            base = 100 + i * 0.2 + 5 * __import__("math").sin(i * __import__("math").pi / 3)
            four_hour.append([i, base, base + 1, base - 1, base + 0.2, 1000])
        four_hour.append([60, 115, 116, 114, 115, 1000])
        fifteen = [[i, 101, 102, 100, 101, 1000] for i in range(30)]
        fifteen[-1] = [29, 100.5, 102, 99, 101.8, 1600]
        fifteen.append([30, 101.8, 102, 101, 101.5, 1000])
        def candles(_market, _symbol, interval, _limit):
            return four_hour if interval == "4h" else fifteen
        with patch.object(platform, "klines", side_effect=candles):
            signal = platform.build_signal("spot", {"symbol": "BTCUSDT", "quote_volume": 50000000}, "15m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertLess(signal["stop"], signal["entry"])
        self.assertLess(signal["tp1"], signal["tp2"])
        self.assertLess(signal["tp2"], signal["tp3"])
        self.assertIn("سحب سيولة", signal["reason"])


    def test_only_15m_timeframe_is_scanned_and_returned(self):
        self.assertEqual(platform.TIMEFRAMES, ("15m",))
        with platform.app.app_context():
            now = platform.utcnow()
            platform.db.session.add_all([
                platform.Trade(market="spot", symbol="OLDUSDT", side="BUY", entry=100, stop=95,
                    tp1=110, tp2=110, tp3=110, score=0, timeframe="1h",
                    reason="legacy", expires_at=now + timedelta(hours=1)),
                platform.Trade(market="spot", symbol="NEWUSDT", side="BUY", entry=100, stop=95,
                    tp1=110, tp2=110, tp3=110, score=0, timeframe="15m",
                    reason="current", expires_at=now + timedelta(hours=1)),
            ])
            platform.db.session.commit()
        response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["symbol"] for x in response.get_json()["signals"]], ["NEWUSDT"])
    def test_public_routes_do_not_disclose_strategy_details(self):
        self.assertEqual(self.client.get("/api/strategies").status_code, 404)
        self.assertEqual(self.client.get("/smart-flow-lab").status_code, 404)
        self.assertEqual(self.client.get("/smart-flow-lab/api/scan").status_code, 404)
        with platform.app.app_context():
            trade = platform.Trade(market="spot", symbol="BTCUSDT", side="BUY", entry=100,
                stop=95, tp1=110, tp2=110, tp3=110, score=0, timeframe="15m",
                reason="PRIVATE STRATEGY DETAIL", expires_at=platform.utcnow() + timedelta(hours=1))
            payload = platform.trade_json(trade)
            self.assertNotIn("reason", payload)
            self.assertNotIn("PRIVATE STRATEGY DETAIL", str(payload))

    def test_scheduler_can_force_a_new_scan_inside_cache_window(self):
        with platform.app.app_context():
            row = platform.Setting(key="scan:spot", value=platform.iso(platform.utcnow()))
            platform.db.session.add(row)
            platform.db.session.commit()
            with patch.object(platform, "market_tickers", return_value=[
                {"symbol": "BTCUSDT", "price": 60000, "change_pct": 2, "quote_volume": 5000000}
            ]) as ticker_source, patch.object(platform, "build_signal", return_value=None):
                cached = platform.run_market_scan("spot")
                self.assertTrue(cached["cached"])
                ticker_source.assert_not_called()
                forced = platform.run_market_scan("spot", force=True)
                self.assertFalse(forced.get("cached", False))
                ticker_source.assert_called_once()

    def test_trade_lifecycle_tracks_targets_and_stop(self):
        with platform.app.app_context():
            trade = platform.Trade(
                market="spot", symbol="BTCUSDT", side="BUY", entry=100,
                stop=97, tp1=103, tp2=106, tp3=109, score=70,
                timeframe="15m", reason="test",
                expires_at=platform.utcnow() + timedelta(hours=1),
            )
            platform.db.session.add(trade)
            platform.db.session.commit()
            platform.update_trade_outcomes("spot", [{"symbol": "BTCUSDT", "price": 104}])
            self.assertEqual(trade.status, "tp1_hit")
            self.assertGreater(trade.result_pct, 0)
            platform.update_trade_outcomes("spot", [{"symbol": "BTCUSDT", "price": 107}])
            self.assertEqual(trade.status, "tp2_hit")
            platform.update_trade_outcomes("spot", [{"symbol": "BTCUSDT", "price": 96}])
            self.assertEqual(trade.status, "stopped_after_tp2")

    def test_ticker_filter_rejects_nan_and_infinite_values(self):
        exchange_info = {
            "symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True, "baseAsset": "BTC"},
                {"symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT", "isSpotTradingAllowed": True, "baseAsset": "ETH"},
            ]
        }
        tickers = [
            {"symbol": "BTCUSDT", "quoteVolume": "NaN", "priceChangePercent": "2", "lastPrice": "60000"},
            {"symbol": "ETHUSDT", "quoteVolume": "5000000", "priceChangePercent": "Infinity", "lastPrice": "3000"},
        ]
        with patch.object(platform, "fetch_json", side_effect=[exchange_info, tickers]):
            platform.market_symbols.cache_clear()
            rows = platform.market_tickers("spot")
        self.assertEqual(rows, [])

    def test_four_hour_structure_blocks_opposite_15m_sweep(self):
        bearish_4h = []
        for i in range(60):
            base = 180 - i * 0.2 - 5 * __import__("math").sin(i * __import__("math").pi / 3)
            bearish_4h.append([i, base, base + 1, base - 1, base - 0.2, 1000])
        bearish_4h.append([60, 165, 166, 164, 165, 1000])
        bullish_15m = [[i, 101, 102, 100, 101, 1000] for i in range(30)]
        bullish_15m[-1] = [29, 100.5, 102, 99, 101.8, 1600]
        bullish_15m.append([30, 101.8, 102, 101, 101.5, 1000])
        def candles(_market, _symbol, interval, _limit):
            return bearish_4h if interval == "4h" else bullish_15m
        with patch.object(platform, "klines", side_effect=candles):
            signal = platform.build_signal("spot", {"symbol": "BTCUSDT", "quote_volume": 5000000}, "15m")
        self.assertIsNone(signal)

    def test_strategy_contains_no_ema_or_indicator_entry_rule(self):
        import inspect
        source = inspect.getsource(platform.build_signal)
        self.assertNotIn("ema(", source)
        self.assertIn("swept_low", source)
        self.assertIn("volume_ratio", source)

    def test_registration_accepts_unicode_letters_and_digits(self):
        bootstrap = self.client.get("/api/bootstrap").get_json()
        response = self.client.post("/api/auth/register",
            json={"email":"arabic-pass@example.com","password":"كلمةمرورقوية123"},
            headers={"X-CSRF-Token":bootstrap["csrf"]},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["user"]["active"])

    def test_existing_admin_password_is_synchronized_from_environment(self):
        with platform.app.app_context():
            admin = platform.User(email="old-admin@example.com",
                                  password_hash=platform.generate_password_hash("OldPassword123!"),
                                  role="admin", active=True, subscription_plan="admin")
            platform.db.session.add(admin)
            platform.db.session.commit()
            with patch.dict(os.environ, {"ADMIN_EMAIL":"new-admin@example.com","ADMIN_PASSWORD":"NewAdminPassword123!"}):
                platform.provision_admin_from_env()
            self.assertEqual(admin.email, "new-admin@example.com")
            self.assertTrue(platform.check_password_hash(admin.password_hash, "NewAdminPassword123!"))

    def test_public_subscription_plans_and_payment_methods(self):
        response = self.client.get("/api/plans")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([plan["total_usd"] for plan in data["plans"]], [30.0, 171.0, 324.0])
        self.assertEqual(data["plans"][1]["discount_pct"], 5)
        self.assertEqual(data["plans"][2]["discount_pct"], 10)
        self.assertEqual(data["payment_methods"]["binance_uid"]["value"], "28191866")

    def test_admin_can_grant_lifetime_access_by_email(self):
        with platform.app.app_context():
            admin = platform.User(email="owner@example.com",
                                  password_hash=platform.generate_password_hash("NewSecurePass123!"),
                                  role="admin", active=True, subscription_plan="admin")
            target = platform.User(email="member@example.com",
                                   password_hash=platform.generate_password_hash("MemberPass123!"),
                                   role="user", active=True, subscription_plan="free")
            platform.db.session.add_all([admin, target])
            platform.db.session.commit()
        bootstrap = self.client.get("/api/bootstrap").get_json()
        login = self.client.post("/api/auth/login",
            json={"email":"owner@example.com","password":"NewSecurePass123!"},
            headers={"X-CSRF-Token":bootstrap["csrf"]},
        )
        self.assertEqual(login.status_code, 200)
        grant = self.client.post("/api/admin/users/subscription-by-email",
            json={"email":"member@example.com","lifetime":True},
            headers={"X-CSRF-Token":login.get_json()["csrf"]},
        )
        self.assertEqual(grant.status_code, 200)
        self.assertTrue(grant.get_json()["user"]["lifetime"])
        self.assertTrue(grant.get_json()["user"]["subscribed"])

    def test_admin_username_alias_authenticates_admin(self):
        with platform.app.app_context():
            admin = platform.User(email="owner@example.com",
                                  password_hash=platform.generate_password_hash("NewSecurePass123!"),
                                  role="admin", active=True, subscription_plan="admin")
            platform.db.session.add(admin)
            platform.db.session.commit()
        bootstrap = self.client.get("/api/bootstrap").get_json()
        with patch.dict(os.environ, {"ADMIN_USERNAME":"aaaksazzz"}):
            response = self.client.post("/api/auth/login",
                json={"email":"aaaksazzz","password":"NewSecurePass123!"},
                headers={"X-CSRF-Token":bootstrap["csrf"]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["role"], "admin")

    def test_lifetime_subscription_is_active_without_expiry(self):
        with platform.app.app_context():
            user = platform.User(email="lifetime@example.com", password_hash="not-used",
                                 role="user", active=True, subscription_plan="lifetime",
                                 subscription_until=None)
            self.assertTrue(platform.subscription_is_active(user))
            user.subscription_plan = "free"
            self.assertFalse(platform.subscription_is_active(user))

    def test_futures_universe_excludes_stablecoin_bases(self):
        exchange_info = {
            "symbols": [
                {"symbol": "BTCUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL", "baseAsset": "BTC"},
                {"symbol": "USDCUSDT", "status": "TRADING", "quoteAsset": "USDT", "contractType": "PERPETUAL", "baseAsset": "USDC"},
            ]
        }
        tickers = [
            {"symbol": "BTCUSDT", "quoteVolume": "5000000", "priceChangePercent": "2", "lastPrice": "60000"},
            {"symbol": "USDCUSDT", "quoteVolume": "5000000", "priceChangePercent": "0", "lastPrice": "1"},
        ]
        with patch.object(platform, "fetch_json", side_effect=[exchange_info, tickers]):
            rows = platform.market_tickers("futures")
        self.assertEqual([row["symbol"] for row in rows], ["BTCUSDT"])


if __name__ == "__main__":
    unittest.main()
