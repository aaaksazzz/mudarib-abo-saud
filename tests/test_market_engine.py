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


    def test_standalone_section_urls_and_authentication_flow(self):
        for path in ("/market/spot", "/market/futures", "/market/alpha", "/market/us-stocks", "/market/us-contracts", "/market/saudi", "/market/forex", "/plans", "/journal", "/blog", "/news", "/login", "/register", "/account", "/admin"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        bootstrap = self.client.get("/api/bootstrap").get_json()
        headers = {"X-CSRF-Token": bootstrap["csrf"]}
        registered = self.client.post("/api/auth/register", json={"email":"auth-check@example.com","password":"strongpass12345"}, headers=headers)
        self.assertEqual(registered.status_code, 201, registered.get_json())
        self.client.post("/api/auth/logout", headers={"X-CSRF-Token": registered.get_json()["csrf"]})
        login_bootstrap = self.client.get("/api/bootstrap").get_json()
        logged_in = self.client.post("/api/auth/login", json={"email":"auth-check@example.com","password":"strongpass12345"}, headers={"X-CSRF-Token":login_bootstrap["csrf"]})
        self.assertEqual(logged_in.status_code, 200, logged_in.get_json())
        self.assertEqual(logged_in.get_json()["user"]["role"], "user")

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


    def test_scan_candidate_batches_rotate_across_the_eligible_universe(self):
        universe = [{"symbol":f"COIN{i}","quote_volume":float(1000-i),"change_pct":0.1} for i in range(170)]
        first, cursor, offset = platform.select_scan_candidates(universe, 0, 80)
        second, cursor, _ = platform.select_scan_candidates(universe, cursor, 80)
        third, cursor, _ = platform.select_scan_candidates(universe, cursor, 80)
        self.assertEqual((len(first),len(second),len(third)), (80,80,10))
        self.assertEqual(len({x["symbol"] for x in first+second+third}), 170)
        self.assertEqual(offset, 0)
        self.assertEqual(cursor, 0)

    def test_build_signal_propagates_provider_failure_for_accurate_scan_health(self):
        with patch.object(platform, "klines", side_effect=RuntimeError("provider timeout")):
            with self.assertRaisesRegex(RuntimeError, "provider timeout"):
                platform.build_signal("spot", {"symbol":"BTCUSDT"}, "15m")

    def test_freshness_filter_rejects_late_or_old_entries(self):
        now = platform.utcnow()
        current = int(now.timestamp() * 1000)
        good = {"symbol":"BTCUSDT","timeframe":"15m","signal_candle_time":current-900000,
                "side":"BUY","entry":100.0,"stop":98.0,"tp1":103.0}
        late = {**good,"symbol":"LATEUSDT"}
        old = {**good,"symbol":"OLDUSDT","signal_candle_time":current-3600000}
        accepted, counts = platform.filter_fresh_signals(
            [good,late,old],
            [{"symbol":"BTCUSDT","price":100.2},{"symbol":"LATEUSDT","price":103.0},{"symbol":"OLDUSDT","price":100.0}],
            now=now,
        )
        self.assertEqual([item["symbol"] for item in accepted], ["BTCUSDT"])
        self.assertEqual(counts["rejected_late_price"], 1)
        self.assertEqual(counts["rejected_stale_candle"], 1)

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

    def test_saudi_screener_merges_yahoo_lists_and_keeps_all_tasi_volumes(self):
        lists = {
            "most_actives": [
                {"symbol":"2222.SR","regularMarketPrice":30,"regularMarketChangePercent":1.2,"regularMarketVolume":10,"currency":"SAR"},
            ],
            "day_gainers": [
                {"symbol":"7010.SR","regularMarketPrice":40,"regularMarketChangePercent":3.0,"regularMarketVolume":5,"currency":"SAR"},
            ],
            "day_losers": [
                {"symbol":"2222.SR","regularMarketPrice":31,"regularMarketChangePercent":-1.0,"regularMarketVolume":20,"currency":"SAR"},
                {"symbol":"AAPL","regularMarketPrice":200,"regularMarketChangePercent":1.0,"regularMarketVolume":1000,"currency":"USD"},
            ],
        }
        platform.market_adapters._screener_quotes_cached.cache_clear()
        with patch.object(platform.market_adapters, "_screener",
                          side_effect=lambda region, scr_id: lists[scr_id]) as screener:
            rows = platform.market_adapters.market_tickers("saudi")
        self.assertEqual({row["symbol"] for row in rows}, {"2222.SR","7010.SR"})
        self.assertEqual(len(rows), 2)
        self.assertEqual(screener.call_count, 3)
        # Saudi equities are not filtered by the one-million-volume threshold.
        self.assertTrue(all(row["quote_volume"] < 1_000_000 for row in rows))

    def test_saudi_screener_normalizes_numeric_tadawul_codes(self):
        lists = {
            "most_actives": [
                {"symbol":"2222","regularMarketPrice":30,"regularMarketChangePercent":1.2,"regularMarketVolume":10,"currency":"SAR"},
            ],
            "day_gainers": [
                {"symbol":"7010","regularMarketPrice":40,"regularMarketChangePercent":3.0,"regularMarketVolume":5,"currency":"SAR"},
            ],
            "day_losers": [],
        }
        with patch.object(platform.market_adapters, "_screener",
                          side_effect=lambda region, scr_id: lists[scr_id]):
            rows = platform.market_adapters.market_tickers("saudi")
        self.assertEqual({row["symbol"] for row in rows}, {"2222.SR","7010.SR"})

    def test_signal_read_does_not_write_expired_trades(self):
        with platform.app.app_context():
            trade = platform.Trade(
                market="spot", symbol="BTCUSDT", side="BUY", entry=100,
                stop=97, tp1=103, tp2=106, tp3=109, score=70,
                timeframe="15m", reason="test",
                expires_at=platform.utcnow() - timedelta(minutes=1),
            )
            platform.db.session.add(trade)
            platform.db.session.commit()
            trade_id = trade.id
        response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        with platform.app.app_context():
            trade = platform.db.session.get(platform.Trade, trade_id)
            self.assertEqual(trade.status, "active")

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

    def test_market_volume_strategy_preserves_dive_atr_levels(self):
        rows = [[i * 900000, 100, 101, 99, 100, 1000] for i in range(120)]
        setup = {"side":"BUY","entry":100.0,"stop":97.0,"tp1":103.0,"tp2":106.0,
                 "tp3":109.0,"score":84.0,"timeframe":"15m","change_pct":0.5,
                 "change_15m_pct":0.5,"reason":"SMART FLOW QUANT:: structure breakout"}
        with patch.object(platform, "klines", return_value=rows), patch.object(platform.market_strategies, "analyze", return_value=setup):
            signal = platform.build_signal("spot", {"symbol":"BTCUSDT","quote_volume":50000000}, "15m")
        self.assertEqual(signal["side"], "BUY")
        risk = signal["entry"] - signal["stop"]
        self.assertAlmostEqual(signal["tp1"] - signal["entry"], risk)
        self.assertAlmostEqual(signal["tp2"] - signal["entry"], 2 * risk)
        self.assertAlmostEqual(signal["tp3"] - signal["entry"], 3 * risk)
        self.assertIn("SMART FLOW QUANT:", signal["reason"])

    def test_only_15m_is_returned(self):
        self.assertEqual(platform.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        with platform.app.app_context():
            now = platform.utcnow()
            platform.db.session.add_all([
                platform.Trade(market="spot", symbol="OLDUSDT", side="BUY", entry=100, stop=95,
                    tp1=105, tp2=110, tp3=115, score=80, timeframe="1h",
                    reason="SMART FLOW QUANT:: old frame", expires_at=now + timedelta(hours=1)),
                platform.Trade(market="spot", symbol="NEWUSDT", side="BUY", entry=100, stop=95,
                    tp1=105, tp2=110, tp3=115, score=85, timeframe="15m",
                    reason="SMART FLOW QUANT:: current frame | bar_ts=123", expires_at=now + timedelta(hours=1)),
                platform.Setting(key="scan:spot", value=platform.iso(now)),
            ])
            platform.db.session.commit()
        response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        signals = response.get_json()["signals"]
        self.assertEqual([x["symbol"] for x in signals], ["NEWUSDT"])
        hourly = self.client.get("/api/markets/spot/signals?timeframe=1h").get_json()["signals"]
        self.assertEqual([x["symbol"] for x in hourly], ["OLDUSDT"])

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
            platform.db.session.add(platform.Trade(market="spot",symbol="CACHEUSDT",side="BUY",
                entry=100,stop=99,tp1=101,tp2=102,tp3=103,score=80,timeframe="15m",
                reason="SMART FLOW QUANT: existing current-engine signal",
                expires_at=platform.utcnow()+timedelta(hours=1)))
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

    # Current-strategy fixtures must use the same reason prefix as production signals.
    def test_scan_checks_rotating_batch_of_eligible_assets_on_15m_only(self):
        items = [{"symbol":f"COIN{i}USDT","price":1.0,"change_pct":float(i),"quote_volume":1_000_000.0+i} for i in range(70)]
        visited=[]
        def capture(market,item,timeframe):
            visited.append((item["symbol"], timeframe))
            return None
        with platform.app.app_context():
            with patch.object(platform,"market_tickers",return_value=items), patch.object(platform,"build_signal",side_effect=capture):
                result=platform.run_market_scan("futures",force=True)
        self.assertEqual(result["scan_universe"],70)
        self.assertEqual(result["scan_batch_size"],70)
        self.assertEqual(len(visited),70*len(platform.TIMEFRAMES))
        self.assertEqual({symbol for symbol, _ in visited}, {f"COIN{i}USDT" for i in range(70)})
        self.assertEqual({frame for _, frame in visited}, set(platform.TIMEFRAMES))

    def test_signals_must_match_market_direction(self):
        now_ms=int(platform.utcnow().timestamp()*1000)
        signal = {
            "symbol":"BTCUSDT","side":"BUY","entry":100.0,"stop":99.0,
            "tp1":101.0,"tp2":102.0,"tp3":103.0,"score":84.5,
            "change_pct":1.2,"timeframe":"15m","signal_candle_time":now_ms-900000-1000,
            "reason":"SMART FLOW QUANT:: confirmed."
        }
        def per_frame(market, item, timeframe):
            interval=platform.market_strategies.INTERVAL_MS[timeframe]
            return {**signal,"timeframe":timeframe,"signal_candle_time":now_ms-interval-1000}
        with platform.app.app_context():
            with patch.object(platform, "market_tickers", return_value=[
                {"symbol":"BTCUSDT","price":100.0,"change_pct":-2.0,"quote_volume":5000000}
            ]), patch.object(platform, "build_signal", side_effect=per_frame):
                result = platform.run_market_scan("futures", force=True)
                self.assertEqual(result["market_bias"], "SELL")
                self.assertEqual(len(result["signals"]), 0)
                self.assertEqual(platform.Trade.query.count(), 0)

    def test_same_15m_candle_does_not_create_duplicate_trades(self):
        now_ms=int(platform.utcnow().timestamp()*1000)
        signal = {
            "symbol":"BTCUSDT","side":"BUY","entry":100.0,"stop":99.0,
            "tp1":101.0,"tp2":102.0,"tp3":103.0,"score":84.5,
            "change_pct":1.2,"timeframe":"15m","signal_candle_time":now_ms-900000-1000,
            "reason":"SMART FLOW QUANT:: confirmed."
        }
        candle_time={}
        def per_frame(market, item, timeframe):
            interval=platform.market_strategies.INTERVAL_MS[timeframe]
            stamp=candle_time.setdefault(timeframe,now_ms-interval-1000)
            return {**signal,"timeframe":timeframe,"signal_candle_time":stamp}
        with platform.app.app_context():
            with patch.object(platform, "market_tickers", return_value=[
                {"symbol":"BTCUSDT","price":100.0,"change_pct":1.2,"quote_volume":5000000}
            ]), patch.object(platform, "build_signal", side_effect=per_frame):
                first = platform.run_market_scan("spot", force=True)
                self.assertEqual(len(first["signals"]), len(platform.TIMEFRAMES))
                self.assertEqual(platform.Trade.query.count(), len(platform.TIMEFRAMES))
                second = platform.run_market_scan("spot", force=True)
                self.assertEqual(platform.Trade.query.count(), len(platform.TIMEFRAMES))
                self.assertEqual(len(second["signals"]), len(platform.TIMEFRAMES))
                self.assertTrue(all(x.status == "active" for x in platform.Trade.query.all()))
                candle_time["15m"] += 1
                third = platform.run_market_scan("spot", force=True)
                trades = platform.Trade.query.order_by(platform.Trade.id.asc()).all()
                self.assertEqual(len(trades), len(platform.TIMEFRAMES)+1)
                self.assertEqual(sum(x.status == "superseded" for x in trades), 1)
                self.assertEqual(len(third["signals"]), len(platform.TIMEFRAMES))

    def test_stale_scan_hides_old_opportunities_instead_of_showing_stuck_coins(self):
        with platform.app.app_context():
            old = platform.Trade(market="spot", symbol="OLDUSDT", side="BUY", entry=100,
                stop=97, tp1=101, tp2=102, tp3=103, score=70, timeframe="15m",
                reason="VOLUME IMPULSE spot: old", expires_at=platform.utcnow()+timedelta(hours=1))
            platform.db.session.add(old)
            platform.db.session.add(platform.Setting(key="scan:spot",
                value=platform.iso(platform.utcnow()-timedelta(minutes=25))))
            platform.db.session.commit()
        response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["stale"])
        self.assertEqual(response.get_json()["signals"], [])

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

    def test_strategy_exposes_only_15m(self):
        self.assertEqual(platform.TIMEFRAMES, ("15m", "1h", "4h", "1d", "1w", "1M"))
        self.assertEqual(platform.provider_status("spot")["timeframes"], list(platform.TIMEFRAMES))

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
