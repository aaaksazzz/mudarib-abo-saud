import unittest
import breakout_50_strategy as strategy


class ASDayTraderEngineTests(unittest.TestCase):
    def test_last_forming_candle_is_excluded(self):
        rows=[[i,100,101,99,100,10] for i in range(50)]
        self.assertEqual(len(strategy._bars(rows)),49)

    def test_targets_are_one_two_three_r_for_both_sides(self):
        self.assertEqual(strategy.target_prices(100,"BUY",98),(102,104,106))
        self.assertEqual(strategy.target_prices(100,"SELL",102),(98,96,94))
        self.assertIsNone(strategy.target_prices(100,"BUY",101))

    def test_trade_direction_is_not_inverted(self):
        self.assertEqual(strategy.inverted_side("BUY"),"BUY")
        self.assertEqual(strategy.inverted_side("SELL"),"SELL")
        self.assertIsNone(strategy.inverted_side("NEUTRAL"))

    def test_structural_stops_are_on_correct_side(self):
        setup={"swing_low":97,"setup_low":96,"swing_high":103,"setup_high":104}
        self.assertLess(strategy.structural_stop(setup,"BUY",2,100),100)
        self.assertGreater(strategy.structural_stop(setup,"SELL",2,100),100)

    def test_volume_profile_and_vwap(self):
        bars=[{"open":100+i*.05,"high":101+i*.05,"low":99+i*.05,
               "close":100.5+i*.05,"volume":10+i} for i in range(30)]
        profile=strategy._volume_profile(bars)
        self.assertIsNotNone(profile)
        self.assertLessEqual(profile["val"],profile["poc"])
        self.assertGreaterEqual(profile["vah"],profile["poc"])
        self.assertGreaterEqual(profile["coverage"],.70)
        self.assertEqual(profile["method"],"candle_typical_price_volume_approximation")
        self.assertAlmostEqual(strategy._vwap([
            {"high":11,"low":9,"close":10,"volume":2},
            {"high":21,"low":19,"close":20,"volume":1}]),40/3)

    def test_all_supported_markets_and_timeframes(self):
        self.assertEqual(len(strategy.MARKETS),7)
        self.assertEqual(strategy.TIMEFRAMES,("15m","1h","4h","1d","1w","1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES),set(strategy.TIMEFRAMES))

    def test_engine_self_test(self):
        result=strategy.diagnostic_self_test()
        self.assertTrue(result["ok"],result)
        self.assertEqual(result["strategy_mode"],"MULTI_SETUP_STANDARD_DIRECTION")
        self.assertTrue(result["checks"]["directions_not_inverted"])


if __name__=="__main__":
    unittest.main()
