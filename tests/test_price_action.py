import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "ci-price-action-test-secret-key-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///ci-market-tests.db")

import app as platform
import market_price_action as engine


def candle_set(kind="buy_sweep"):
    rows = []
    for i in range(24):
        rows.append([i * 3600000, 100.0, 100.5, 99.5, 100.1, 1000.0])
    if kind == "buy_sweep":
        rows.append([24 * 3600000, 99.8, 100.5, 99.0, 100.3, 1600.0])
    elif kind == "sell_sweep":
        rows.append([24 * 3600000, 100.2, 101.0, 99.5, 99.7, 1600.0])
    elif kind == "buy_breakout":
        rows.append([24 * 3600000, 100.4, 102.0, 100.2, 101.9, 1600.0])
    elif kind == "sell_breakout":
        rows.append([24 * 3600000, 99.6, 99.8, 98.0, 98.1, 1600.0])
    rows.append([25 * 3600000, 100.0, 105.0, 95.0, 100.0, 999999.0])
    return rows


class ClassicPriceActionTests(unittest.TestCase):
    def setUp(self):
        with engine._lock:
            engine._cache.pop("unit-test", None)
            engine._cursor.pop("unit-test", None)

    def test_fingerprint_and_internal_contexts(self):
        self.assertEqual(engine.STRATEGY_FINGERPRINT, "CLASSIC-PRICE-ACTION-15M-V2-20261109")
        self.assertEqual(engine.TIMEFRAMES, ("15m",))

    def test_detects_closed_bullish_and_bearish_liquidity_sweeps(self):
        self.assertEqual(engine._pattern(candle_set("buy_sweep"))["side"], "BUY")
        self.assertEqual(engine._pattern(candle_set("sell_sweep"))["side"], "SELL")

    def test_detects_confirmed_breakout_closes(self):
        self.assertEqual(engine._pattern(candle_set("buy_breakout"))["kind"], "اختراق مقاومة بإغلاق مؤكد")
        self.assertEqual(engine._pattern(candle_set("sell_breakout"))["kind"], "كسر دعم بإغلاق مؤكد")

    def test_forming_candle_does_not_change_signal(self):
        rows = candle_set("buy_sweep")
        original = engine._pattern(rows)
        rows[-1] = [rows[-1][0], 1.0, 500.0, 0.1, 2.0, 1e12]
        self.assertEqual(engine._pattern(rows), original)

    def test_requires_two_matching_timeframe_confirmations(self):
        def provider(market, symbol, timeframe, limit):
            if timeframe == "1h":
                return candle_set("buy_sweep")
            if timeframe == "4h":
                return candle_set("flat")
            return candle_set("sell_sweep")
        result = engine._inspect({"symbol": "TESTUSDT", "price": 100.3}, "futures", provider)
        self.assertIsNone(result)

    def test_cash_only_markets_reject_sell_signals(self):
        def provider(market, symbol, timeframe, limit):
            return candle_set("sell_sweep")
        for market in ("spot", "alpha", "us-stocks", "saudi"):
            with self.subTest(market=market):
                result = engine._inspect(
                    {"symbol": "TEST", "price": 99.7, "quote_volume": 2_000_000},
                    market,
                    provider,
                )
                self.assertIsNone(result)

    def test_inspect_builds_levels_after_two_confirmations(self):
        def provider(market, symbol, timeframe, limit):
            return candle_set("buy_sweep")
        result = engine._inspect(
            {"symbol": "TESTUSDT", "price": 100.3, "quote_volume": 2_000_000},
            "futures",
            provider,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "BUY")
        self.assertGreaterEqual(result["confirmations"], 2)
        self.assertLess(result["stop"], result["entry"])
        self.assertLess(result["entry"], result["tp1"])
        self.assertLess(result["tp1"], result["tp2"])
        self.assertLess(result["tp2"], result["tp3"])
        self.assertGreaterEqual(result["reward_risk_tp3"], 2.9)

    def test_provider_failure_is_not_silently_reported_as_no_signal(self):
        def broken(*args, **kwargs):
            raise OSError("provider offline")
        with self.assertRaisesRegex(RuntimeError, "Insufficient completed 15m candles"):
            engine._inspect({"symbol": "TESTUSDT"}, "futures", broken)

    def test_small_universe_is_not_duplicated_to_fill_scan_batch(self):
        universe = [
            {"symbol": "AAAUSDT", "quote_volume": 2_000_000},
            {"symbol": "BBBUSDT", "quote_volume": 1_500_000},
        ]
        with patch.object(engine, "_inspect", return_value=None):
            result = engine.scan_market("unit-test", universe, lambda *args: [], limit=30)
        self.assertEqual(result["checked_assets"], 2)
        self.assertEqual(result["universe_total"], 2)
        self.assertEqual(result["analysis_errors"], 0)

    def test_all_candle_provider_failures_return_provider_error_not_empty_success(self):
        universe = [{"symbol": "AAAUSDT", "quote_volume": 2_000_000}]
        def broken(*args, **kwargs):
            raise OSError("provider offline")
        result = engine.scan_market("unit-test", universe, broken, limit=1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["provider_error"])
        self.assertEqual(result["error_code"], "all_candle_requests_failed")
        self.assertEqual(result["signals"], [])

    def test_journal_serializer_and_current_strategy_status(self):
        now = datetime.now(timezone.utc)
        trade = SimpleNamespace(
            id=7, market="futures", symbol="TESTUSDT", side="BUY", entry=100.0,
            stop=98.0, tp1=102.0, tp2=104.0, tp3=106.0, score=80,
            timeframe="15m", reason="historical paper trade", status="active",
            created_at=now, expires_at=now, result_pct=None, change_15m_pct=0.2,
        )
        payload = platform.trade_json(trade)
        self.assertEqual(payload["symbol"], "TESTUSDT")
        self.assertEqual(payload["change_pct"], 0.2)
        platform.app.config.update(TESTING=True)
        with platform.app.app_context():
            platform.db.create_all()
        client = platform.app.test_client()
        journal = client.get("/api/trades")
        self.assertEqual(journal.status_code, 200)
        self.assertIn("active_trades", journal.get_json())
        status = client.get("/api/strategy/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.get_json()["fingerprint"], engine.STRATEGY_FINGERPRINT)
        ready = client.get("/ready").get_json()
        self.assertIn("price_action_engine", ready["checks"])
        self.assertNotIn("sentiment_engine", ready["checks"])


if __name__ == "__main__":
    unittest.main()
