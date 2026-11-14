import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import market_adapters


class AlphaMonthlyHistoryTests(unittest.TestCase):
    def test_weekly_ohlcv_aggregates_to_utc_calendar_months(self):
        def stamp(value):
            return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)

        rows = [
            [stamp("2026-01-02"), 10, 12, 9, 11, 100],
            [stamp("2026-01-09"), 11, 13, 10, 12, 150],
            [stamp("2026-02-06"), 12, 14, 11, 13, 200],
        ]
        monthly = market_adapters._aggregate_monthly(rows)
        self.assertEqual(len(monthly), 2)
        self.assertEqual(monthly[0][1:], [10, 13, 9, 12, 250])
        self.assertEqual(monthly[1][1:], [12, 14, 11, 13, 200])

    @patch("market_adapters._get")
    def test_alpha_monthly_uses_real_weekly_provider_candles(self, get):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        candles = []
        for i in range(60):
            stamp = int((start + timedelta(days=7 * i)).timestamp() * 1000)
            candles.append([stamp, "100", "105", "95", "102", "1000"])
        get.return_value = {"data": candles}

        rows = market_adapters.klines("alpha", "TESTUSDT", "1M", 250)

        self.assertGreaterEqual(len(rows), 12)
        self.assertEqual(get.call_args.args[1]["interval"], "1w")
        self.assertEqual(get.call_args.args[1]["limit"], 1000)
        self.assertTrue(all(len(row) == 6 for row in rows))


if __name__ == "__main__":
    unittest.main()
