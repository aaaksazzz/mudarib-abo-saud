import os
import unittest\nfrom datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace

os.environ["ENABLE_AUTO_SCAN"] = "false"

import app as platform_app


class ScanDiagnosticsTests(unittest.TestCase):
    def test_timeout_is_classified_without_exposing_provider_message(self):
        exc = platform_app.requests.exceptions.Timeout("secret query token")
        self.assertEqual(platform_app.scan_failure_code(exc), "provider_timeout")

    def test_http_429_is_classified_as_rate_limit(self):
        response = platform_app.requests.Response()
        response.status_code = 429
        exc = platform_app.requests.exceptions.HTTPError("rate limited", response=response)
        self.assertEqual(platform_app.scan_failure_code(exc), "provider_rate_limited")

    def test_build_signal_distinguishes_empty_and_short_history(self):
        with patch.object(platform_app, "klines", return_value=[]):
            empty = platform_app.build_signal("alpha", {"symbol": "ALPHAUSDT"}, "1M")
        self.assertEqual(empty["_diagnostic_code"], "empty_candle_response")
        self.assertEqual(empty["_candles_received"], 0)

        with patch.object(platform_app, "klines", return_value=[[i, 1, 2, 0.5, 1.5, 10] for i in range(12)]):
            short = platform_app.build_signal("alpha", {"symbol": "ALPHAUSDT"}, "1M")
        self.assertEqual(short["_diagnostic_code"], "insufficient_history")
        self.assertEqual(short["_candles_received"], 12)

    def test_build_signal_uses_timeframe_specific_history_requirement(self):
        monthly_rows=[[i, 100, 101, 99, 100, 10] for i in range(43)]
        with patch.object(platform_app, "klines", return_value=monthly_rows), patch.object(
            platform_app.market_strategies, "analyze_all", return_value=None
        ) as analyze:
            result=platform_app.build_signal("alpha", {"symbol":"ALPHAUSDT"}, "1M")
        self.assertNotIn("_data_incomplete", result)
        self.assertTrue(result["_strategy_rejected"])
        analyze.assert_called_once()
        self.assertEqual(analyze.call_args.kwargs["timeframe"], "1M")
        self.assertIn("diagnostics", analyze.call_args.kwargs)

    def test_scan_failure_samples_are_bounded_and_counted(self):
        stats = {"15m": {"failure_reasons": {}, "failure_samples": []}}
        for index in range(8):
            platform_app.record_scan_failure(
                stats, "15m", {"symbol": f"TEST{index}"}, "provider_timeout"
            )
        self.assertEqual(stats["15m"]["failure_reasons"]["provider_timeout"], 8)
        self.assertEqual(len(stats["15m"]["failure_samples"]), 5)
        self.assertTrue(all(sample["timeframe"] == "15m" for sample in stats["15m"]["failure_samples"]))


    def test_retired_signal_lab_bookmark_redirects_to_current_terminal(self):
        response = platform_app.app.test_client().get("/signal-lab", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/intelligence")

    def test_legacy_market_signals_route_uses_current_scanner_and_filters_frame(self):
        current = {
            "signals": [
                {"symbol": "BTCUSDT", "timeframe": "15m"},
                {"symbol": "ETHUSDT", "timeframe": "1h"},
            ],
            "updated_at": "2026-11-14T12:00:00+00:00",
            "analysis_completed": 12,
            "analysis_failed": 2,
            "strategy_matches": 2,
            "rejected_stale_candle": 0,
            "rejected_late_price": 0,
            "data_status": "partial",
            "incomplete_timeframes": {"1M": {"completed": 2, "required": 8}},
            "frame_diagnostics": {},
        }
        with patch.object(platform_app, "gate_section", return_value=None), patch.object(
            platform_app, "run_market_scan", return_value=current
        ) as scan:
            response = platform_app.app.test_client().get(
                "/api/markets/spot/signals?timeframe=1h"
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual([item["symbol"] for item in payload["signals"]], ["ETHUSDT"])
        self.assertEqual(payload["timeframe"], "1h")
        self.assertEqual(payload["data_status"], "partial")
        scan.assert_called_once_with("spot", force=False)

    def test_trade_json_includes_calculated_reward_risk(self):
        trade = platform_app.Trade(
            market="futures", symbol="BTCUSDT", side="BUY", entry=100,
            stop=95, tp1=105, tp2=110, tp3=115, score=90,
            timeframe="15m", reason="test", expires_at=platform_app.utcnow()
        )
        self.assertEqual(platform_app.trade_json(trade)["reward_risk"], 3.0)

    def test_scan_filters_signals_only_when_market_breadth_is_decisive(self):
        signals = [
            {"symbol": "LONG", "side": "BUY", "timeframe": "15m"},
            {"symbol": "SHORT", "side": "SELL", "timeframe": "15m"},
        ]
        bias, strength = platform_app.classify_market_breadth(70, 30)
        self.assertEqual(bias, "BUY")
        self.assertEqual(strength, 0.7)
        aligned, rejected = platform_app.align_signals_with_market_bias(signals, bias)
        self.assertEqual([signal["symbol"] for signal in aligned], ["LONG"])
        self.assertEqual(rejected, 1)
        weak_bias, _ = platform_app.classify_market_breadth(54, 46)
        self.assertIsNone(weak_bias)
        neutral, neutral_rejected = platform_app.align_signals_with_market_bias(signals, weak_bias)
        self.assertEqual(neutral, signals)
        self.assertEqual(neutral_rejected, 0)

    def test_cached_trade_risk_limit_matches_its_timeframe_profile(self):
        trade = platform_app.Trade(
            market="futures", symbol="BTCUSDT", side="BUY", entry=100,
            stop=90, tp1=110, tp2=120, tp3=130, score=90,
            timeframe="1w", reason="test", expires_at=platform_app.utcnow()
        )
        self.assertTrue(platform_app.trade_within_frame_risk_limit(trade))
        trade.timeframe="15m"
        self.assertFalse(platform_app.trade_within_frame_risk_limit(trade))

    def test_trade_json_exposes_risk_targets_and_real_reason(self):
        trade = platform_app.Trade(
            market="futures", symbol="BTCUSDT", side="BUY", entry=100,
            stop=95, tp1=105, tp2=110, tp3=115, score=90,
            timeframe="15m", reason="ADAPTIVE-TREND: EMA_PULLBACK | bar_ts=123",
            expires_at=platform_app.utcnow()
        )
        payload=platform_app.trade_json(trade)
        self.assertEqual(payload["risk_pct"], 5.0)
        self.assertEqual(payload["tp1_r"], 1.0)
        self.assertEqual(payload["tp2_r"], 2.0)
        self.assertEqual(payload["tp3_r"], 3.0)
        self.assertEqual(payload["reason"], "ADAPTIVE-TREND: EMA_PULLBACK")
        self.assertEqual(payload["score_type"], "technical_quality_not_probability")

    def test_monthly_outcome_tracker_uses_calendar_months_and_ignores_pre_entry_bar(self):
        created=datetime(2026,1,15,tzinfo=timezone.utc)
        trade=platform_app.Trade(
            market="futures",symbol="BTCUSDT",side="BUY",entry=100,
            stop=95,tp1=105,tp2=110,tp3=115,score=90,timeframe="1M",
            reason="test",created_at=created,expires_at=created+timedelta(days=90),
            status="active"
        )
        jan=int(datetime(2026,1,1,tzinfo=timezone.utc).timestamp()*1000)
        feb=int(datetime(2026,2,1,tzinfo=timezone.utc).timestamp()*1000)
        mar=int(datetime(2026,3,1,tzinfo=timezone.utc).timestamp()*1000)
        rows=[
            [jan,100,120,99,110,10],
            [feb,100,106,99,105,10],
            [mar,105,120,104,118,10],
        ]
        now=int(datetime(2026,3,1,tzinfo=timezone.utc).timestamp()*1000)
        status,completed=platform_app.evaluate_trade_outcome_from_bars(trade,rows,now)
        self.assertEqual(status,"tp1_hit")
        self.assertEqual(completed,1)

    def test_legacy_market_signals_route_rejects_unknown_timeframe(self):
        response = platform_app.app.test_client().get(
            "/api/markets/spot/signals?timeframe=5m"
        )
        self.assertEqual(response.status_code, 400)


    def test_active_trade_is_not_retired_when_scan_has_no_replacement(self):
        trade=SimpleNamespace(id=1,market="futures",symbol="BTCUSDT",timeframe="15m")
        self.assertFalse(platform_app.trade_should_be_superseded(trade,set()))

    def test_new_signal_for_another_symbol_does_not_retire_existing_trade(self):
        trade=SimpleNamespace(id=1,market="futures",symbol="BTCUSDT",timeframe="15m")
        replacements={("futures","ETHUSDT","15m")}
        self.assertFalse(platform_app.trade_should_be_superseded(trade,replacements))

    def test_new_signal_retires_only_same_symbol_and_timeframe_trade(self):
        trade=SimpleNamespace(id=1,market="futures",symbol="BTCUSDT",timeframe="15m")
        replacements={("futures","BTCUSDT","15m"),("futures","ETHUSDT","1h")}
        self.assertTrue(platform_app.trade_should_be_superseded(trade,replacements))
        self.assertFalse(platform_app.trade_should_be_superseded(trade,replacements,{1}))

    def test_duplicate_candle_keeps_existing_trade_active(self):
        trade=SimpleNamespace(id=7,market="futures",symbol="BTCUSDT",timeframe="15m")
        replacements={("futures","BTCUSDT","15m")}
        self.assertFalse(platform_app.trade_should_be_superseded(trade,replacements,{7}))


if __name__ == "__main__":
    unittest.main()
