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


if __name__ == "__main__":
    unittest.main()
