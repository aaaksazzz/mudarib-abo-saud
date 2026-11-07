import unittest
from unittest.mock import patch

import market_adapters


class YahooHistoryWindowTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "chart": {
                "result": [{
                    "timestamp": [1_800_000_000],
                    "indicators": {
                        "quote": [{
                            "open": [100.0],
                            "high": [101.0],
                            "low": [99.0],
                            "close": [100.5],
                            "volume": [1000.0],
                        }]
                    },
                }],
                "error": None,
            }
        }

    @patch("market_adapters._get")
    def test_15m_requests_enough_history_for_sma200(self, get):
        get.return_value = self.payload
        rows = market_adapters._chart("2222.SR", "15m")
        self.assertEqual(len(rows), 1)
        params = get.call_args.args[1]
        self.assertEqual(params["interval"], "15m")
        self.assertEqual(params["range"], "60d")

    @patch("market_adapters._get")
    def test_empty_primary_host_falls_back_to_secondary_host(self, get):
        empty = {"chart": {"result": [], "error": None}}
        get.side_effect = [empty, self.payload]
        rows = market_adapters._chart("2222.SR", "15m")
        self.assertEqual(len(rows), 1)
        self.assertEqual(get.call_count, 2)


    @patch("market_adapters._get")
    def test_monthly_requests_maximum_available_history(self, get):
        get.return_value = self.payload
        market_adapters._chart("2222.SR", "1mo")
        self.assertEqual(get.call_args.args[1]["range"], "max")


if __name__ == "__main__":
    unittest.main()
