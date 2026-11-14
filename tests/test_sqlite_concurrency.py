import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ["ENABLE_AUTO_SCAN"] = "false"

import app as platform_app


class SQLiteConcurrencyTests(unittest.TestCase):
    def test_sqlite_connections_wait_for_transient_writer_locks(self):
        if not platform_app.SQLITE_DATABASE:
            self.skipTest("SQLite is not the configured database")
        with platform_app.app.app_context():
            with platform_app.db.engine.connect() as connection:
                timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
        self.assertGreaterEqual(timeout, 30000)

    def test_market_scans_are_serialized_across_markets(self):
        state_lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_scan(market, force=False):
            nonlocal active, maximum_active
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.04)
            with state_lock:
                active -= 1
            return {"ok": True, "market": market}

        original = platform_app._MARKET_SCAN_LOCK
        self.assertFalse(original.locked())
        with patch.object(platform_app, "_run_market_scan_unlocked", side_effect=fake_scan):
            threads = [
                threading.Thread(
                    target=platform_app.run_market_scan,
                    args=(market,),
                    kwargs={"force": True},
                )
                for market in ("spot", "futures", "saudi", "forex")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(maximum_active, 1)
        self.assertFalse(original.locked())


if __name__ == "__main__":
    unittest.main()
