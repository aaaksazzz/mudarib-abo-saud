import unittest

import as_market_tools as tools


class MarketCoverageTests(unittest.TestCase):
    def test_all_seven_markets_have_all_six_timeframes(self):
        status = tools.status()
        self.assertEqual(set(status["markets"]), set(tools.MARKETS))
        for market, config in status["markets"].items():
            self.assertEqual(tuple(config["timeframes"]), tools.TIMEFRAMES)
            self.assertEqual(len(config["timeframes"]), 6)

    def test_us_equity_modules_are_scoped(self):
        us = tools.module_coverage("us-stocks")
        self.assertEqual(us["sec_xbrl_analyst"], "enabled")
        self.assertEqual(us["institutional_13f_copycat"], "enabled")
        self.assertEqual(us["us_tax_lots_wash_sales"], "enabled")
        for market in set(tools.MARKETS) - {"us-stocks"}:
            coverage = tools.module_coverage(market)
            self.assertEqual(coverage["sec_xbrl_analyst"], "not_applicable")
            self.assertEqual(coverage["institutional_13f_copycat"], "not_applicable")

    def test_broker_execution_is_disabled_everywhere(self):
        for market in tools.MARKETS:
            self.assertEqual(tools.module_coverage(market)["broker_execution"],
                             "disabled_manual_only")

    def test_buy_and_sell_geometry_passes_all_frames(self):
        for frame in tools.TIMEFRAMES:
            buy = {"side": "BUY", "entry": 100, "stop": 98, "tp1": 102,
                   "tp2": 104, "tp3": 106, "symbol": "TEST"}
            sell = {"side": "SELL", "entry": 100, "stop": 102, "tp1": 98,
                    "tp2": 96, "tp3": 94, "symbol": "TEST"}
            self.assertTrue(tools.validate_signal(buy, frame)["ok"], frame)
            self.assertTrue(tools.validate_signal(sell, frame)["ok"], frame)

    def test_invalid_stop_is_rejected(self):
        signal = {"side": "BUY", "entry": 100, "stop": 101, "tp3": 106}
        self.assertFalse(tools.validate_signal(signal, "15m")["ok"])

    def test_every_market_and_frame_accepts_valid_signal(self):
        for market in tools.MARKETS:
            for frame in tools.TIMEFRAMES:
                signal = {"side": "BUY", "entry": 100, "stop": 98,
                          "tp1": 102, "tp2": 104, "tp3": 106,
                          "symbol": "TEST"}
                out = tools.apply_skill_stack(market, frame, signal)
                self.assertIsNotNone(out, (market, frame))
                self.assertEqual(out["skill_suite"]["market"], market)
                self.assertEqual(out["skill_suite"]["timeframe"], frame)
                self.assertFalse(out["skill_suite"]["broker"]["execution_enabled"])


if __name__ == "__main__":
    unittest.main()
