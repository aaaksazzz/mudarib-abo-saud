import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


def sample_signal():
    return {
        "symbol": "TESTUSDT",
        "timeframe": "15m",
        "signal_candle_time": 1760000000,
        "side": "BUY",
        "entry": 100.0,
        "stop_loss": 98.0,
        "tp1": 102.0,
        "tp2": 104.0,
        "tp3": 106.0,
    }


class TradePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "trades.sqlite3"
        self.db_patch = patch.object(app_module, "DB_PATH", self.db_path)
        self.db_patch.start()
        with app_module.db() as connection:
            connection.execute("DELETE FROM trades")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_new_signal_is_saved_once_and_only_returned_once(self):
        first = app_module.save_new_trades("spot", [sample_signal()])
        second = app_module.save_new_trades("spot", [sample_signal()])

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        with app_module.db() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM trades WHERE market=? AND symbol=? AND timeframe=?",
                ("spot", "TESTUSDT", "15m"),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_same_candle_is_not_reissued_even_after_trade_closes(self):
        self.assertEqual(len(app_module.save_new_trades("spot", [sample_signal()])), 1)
        with app_module.db() as connection:
            connection.execute(
                "UPDATE trades SET status='TP3', closed_at=created_at WHERE market='spot' AND symbol='TESTUSDT'"
            )

        self.assertEqual(app_module.save_new_trades("spot", [sample_signal()]), [])

    def test_same_symbol_can_create_new_trade_on_next_completed_candle(self):
        self.assertEqual(len(app_module.save_new_trades("spot", [sample_signal()])), 1)
        next_candle = sample_signal()
        next_candle["signal_candle_time"] += 15 * 60
        self.assertEqual(len(app_module.save_new_trades("spot", [next_candle])), 1)

    def test_same_symbol_on_another_timeframe_is_independent(self):
        self.assertEqual(len(app_module.save_new_trades("spot", [sample_signal()])), 1)
        other_timeframe = sample_signal()
        other_timeframe["timeframe"] = "1h"

        self.assertEqual(len(app_module.save_new_trades("spot", [other_timeframe])), 1)

    def test_repeated_candidates_do_not_block_three_new_top_opportunities(self):
        app_module.save_new_trades("spot", [sample_signal()])
        candidates = [sample_signal()]
        for symbol in ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"):
            signal = sample_signal()
            signal["symbol"] = symbol
            candidates.append(signal)

        saved = app_module.save_new_trades("spot", candidates)
        self.assertEqual([row["symbol"] for row in saved], ["AAAUSDT", "BBBUSDT", "CCCUSDT"])

    def test_database_uses_configured_path_and_survives_new_connections(self):
        app_module.save_new_trades("spot", [sample_signal()])
        self.assertTrue(self.db_path.exists())
        with app_module.db() as connection:
            row = connection.execute(
                "SELECT symbol FROM trades WHERE market='spot'"
            ).fetchone()
        self.assertEqual(row["symbol"], "TESTUSDT")


if __name__ == "__main__":
    unittest.main()


    def test_market_scan_snapshot_persists_full_results_per_market_and_timeframe(self):
        payload = {
            "ok": True,
            "market": "spot",
            "timeframe": "15m",
            "direction": "BUY",
            "signals": [{"symbol": "BTCUSDT", "side": "BUY", "entry": 100.0}],
            "open_trades": [{"symbol": "BTCUSDT", "status": "OPEN"}],
            "scan_diagnostics": {"candidates_scanned": 12},
        }
        app_module.save_market_scan_snapshot("spot", "15m", payload)
        restored = app_module.load_market_scan_snapshot("spot", "15m")
        self.assertIsNotNone(restored)
        self.assertEqual(restored["payload"], payload)
        self.assertGreater(restored["updated_at"], 0)
        self.assertIsNone(app_module.load_market_scan_snapshot("spot", "1h"))


    def test_market_endpoint_reuses_saved_scan_for_15_minutes_without_provider_scan(self):
        with patch.object(app_module, "AUTH_CONFIGURED", True), \
             patch.object(app_module, "ADMIN_EMAIL", "owner@example.test"), \
             patch.object(app_module, "ADMIN_PASSWORD", "owner-password-123"):
            with app_module.db() as connection:
                admin = connection.execute(
                    "SELECT id FROM users WHERE email=?", ("owner@example.test",)
                ).fetchone()
            client = app_module.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = admin["id"]
            payload = {
                "ok": True, "market": "spot", "timeframe": "15m", "direction": "BUY",
                "up": 10, "down": 2, "flat": 1, "total": 13,
                "signals": [{"symbol": "BTCUSDT", "side": "BUY"}],
                "open_trades": [], "scan_diagnostics": {"candidates_scanned": 12},
            }
            app_module.save_market_scan_snapshot("spot", "15m", payload)
            with patch.object(app_module, "market_tickers", side_effect=AssertionError("should use saved scan")):
                response = client.get("/api/market/spot?timeframe=15m")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["scan_cached"])
            self.assertEqual(response.json["signals"][0]["symbol"], "BTCUSDT")
            self.assertGreater(response.json["seconds_until_next_scan"], 0)
