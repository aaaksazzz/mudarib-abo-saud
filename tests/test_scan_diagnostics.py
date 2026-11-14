import os
import unittest
from unittest.mock import patch

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

    def test_market_signals_route_reads_frame_cache_without_running_scan(self):
        with patch.object(platform_app, "gate_section", return_value=None), patch.object(
            platform_app.db.session, "get", return_value=None
        ), patch.object(platform_app, "run_market_scan") as scan:
            response = platform_app.app.test_client().get(
                "/api/markets/spot/signals?timeframe=1h"
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["timeframe"], "1h")
        self.assertEqual(payload["signals"], [])
        self.assertTrue(payload["stale"])
        self.assertEqual(payload["data_status"], "pending")
        scan.assert_not_called()

    def test_trade_json_includes_calculated_reward_risk(self):
        trade = platform_app.Trade(
            market="futures", symbol="BTCUSDT", side="BUY", entry=100,
            stop=95, tp1=105, tp2=110, tp3=115, score=90,
            timeframe="15m", reason="test", expires_at=platform_app.utcnow()
        )
        self.assertEqual(platform_app.trade_json(trade)["reward_risk"], 3.0)

    def test_scan_filters_signals_against_market_bias(self):
        signals = [
            {"symbol": "LONG", "side": "BUY", "timeframe": "15m"},
            {"symbol": "SHORT", "side": "SELL", "timeframe": "15m"},
        ]
        aligned, rejected = platform_app.align_signals_with_market_bias(signals, "SELL")
        self.assertEqual([signal["symbol"] for signal in aligned], ["SHORT"])
        self.assertEqual(rejected, 1)
        neutral, neutral_rejected = platform_app.align_signals_with_market_bias(signals, None)
        self.assertEqual(neutral, [])
        self.assertEqual(neutral_rejected, 2)

    def test_legacy_market_signals_route_rejects_unknown_timeframe(self):
        response = platform_app.app.test_client().get(
            "/api/markets/spot/signals?timeframe=5m"
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
