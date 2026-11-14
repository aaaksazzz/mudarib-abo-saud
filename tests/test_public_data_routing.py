import unittest
from unittest.mock import patch, Mock

import requests
import public_data_routing as routing


class PublicDataRoutingTests(unittest.TestCase):
    def setUp(self):
        with routing._LOCK:
            for key in routing.ROUTES:
                routing._STATE[key] = {"index": 0, "successes": 0, "last_error": None}

    @patch("public_data_routing.requests.request")
    def test_rotates_after_twenty_successful_fetches(self, request):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        request.return_value = response

        for _ in range(20):
            routing.request_json("https://api.binance.com/api/v3/time")

        status = routing.provider_route_status()["binance_spot"]
        self.assertEqual(status["preferred_host"], "https://api1.binance.com")
        self.assertEqual(status["successful_fetches_on_host"], 0)
        self.assertEqual(request.call_count, 20)

    @patch("public_data_routing.requests.request")
    def test_fails_over_immediately_when_primary_is_unavailable(self, request):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        request.side_effect = [requests.ConnectionError("offline"), response]

        payload = routing.request_json("https://api.binance.com/api/v3/time")

        self.assertEqual(payload, {"ok": True})
        self.assertIn("api.binance.com", request.call_args_list[0].args[1])
        self.assertIn("api1.binance.com", request.call_args_list[1].args[1])
        self.assertEqual(routing.provider_route_status()["binance_spot"]["preferred_host"],
                         "https://api1.binance.com")

    def test_routes_are_public_and_do_not_require_api_keys(self):
        for status in routing.provider_route_status().values():
            self.assertFalse(status["requires_api_key"])


if __name__ == "__main__":
    unittest.main()
