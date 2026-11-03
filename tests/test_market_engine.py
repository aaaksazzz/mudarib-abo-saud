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
        self.assertFalse(ready.get_json()["checks"]["market_scheduler"])

    def test_public_signal_read_does_not_start_synchronous_scan(self):
        with patch.object(platform, "run_market_scan", side_effect=AssertionError("HTTP request must not scan")) as scan:
            response = self.client.get("/api/markets/spot/signals")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["signals"], [])
        scan.assert_not_called()

    def test_unintegrated_market_never_returns_fabricated_data(self):
        snapshot = self.client.get("/api/markets/saudi/snapshot").get_json()
        signals = self.client.get("/api/markets/saudi/signals").get_json()
        self.assertFalse(snapshot["ready"])
        self.assertEqual(snapshot["assets"], [])
        self.assertIsNone(snapshot["up"])
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

    def test_signal_uses_closed_15m_candles_and_higher_timeframe_agreement(self):
        series = {
            "15m": candle_rows([100 + index * 0.1 for index in range(100)]),
            "4h": candle_rows([100 + index for index in range(80)]),
            "1d": candle_rows([100 + index * 0.5 for index in range(60)]),
        }
        # The final row simulates a still-forming candle and must not affect the signal.
        series["15m"][-1][4] = 1
        with patch.object(platform, "klines", side_effect=lambda market, symbol, interval, limit=120: series[interval]):
            signal = platform.build_signal("spot", {"symbol": "BTCUSDT", "change_pct": 4.0, "quote_volume": 50_000_000})
        self.assertIsNotNone(signal)
        self.assertEqual(signal["side"], "BUY")
        self.assertGreater(signal["change_15m_pct"], 0)
        self.assertLess(signal["score"], 96)
        self.assertLess(signal["stop"], signal["entry"])
        self.assertGreater(signal["tp3"], signal["tp2"])

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
