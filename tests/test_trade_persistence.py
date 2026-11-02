import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


def sample_signal():
    return {
        "symbol": "TESTUSDT",
        "timeframe": "15m",
        "signal_candle_time": 1_800_000_000_000,
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

    def test_same_completed_candle_is_not_issued_twice(self):
        self.assertEqual(len(app_module.save_new_trades("spot", [sample_signal()])), 1)
        with app_module.db() as connection:
            connection.execute(
                "UPDATE trades SET status='TP3', closed_at=created_at WHERE market='spot' AND symbol='TESTUSDT'"
            )
        self.assertEqual(app_module.save_new_trades("spot", [sample_signal()]), [])

    def test_new_completed_candle_can_issue_another_trade(self):
        self.assertEqual(len(app_module.save_new_trades("spot", [sample_signal()])), 1)
        next_candle = sample_signal()
        next_candle["signal_candle_time"] += 15 * 60 * 1000
        self.assertEqual(len(app_module.save_new_trades("spot", [next_candle])), 1)

    def test_same_candle_on_another_timeframe_is_independent(self):
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
