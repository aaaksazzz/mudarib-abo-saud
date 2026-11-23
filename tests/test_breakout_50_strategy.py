import unittest
import breakout_50_strategy as strategy


class FalseBreakoutCloseReversalTests(unittest.TestCase):
    def test_last_forming_candle_is_excluded(self):
        rows=[[i,100,101,99,100,10] for i in range(50)]
        self.assertEqual(len(strategy._bars(rows)),49)

    def test_targets_are_one_two_three_r_for_both_sides(self):
        self.assertEqual(strategy.target_prices(100,"BUY",98),(102,104,106))
        self.assertEqual(strategy.target_prices(100,"SELL",102),(98,96,94))
        self.assertIsNone(strategy.target_prices(100,"BUY",101))

    def test_downside_break_then_close_above_break_candle_is_buy(self):
        bars=[{"time":i,"open":11,"high":12,"low":11,"close":11.5,"volume":10} for i in range(20)]
        bars[5].update({"low":10.0})
        bars[10].update({"open":9.8,"high":10.2,"low":9.0,"close":9.5})
        bars[-1].update({"open":10.0,"high":10.6,"low":9.9,"close":10.3})
        setup=strategy._find_reversal(bars,1.0)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"],"BUY")
        self.assertGreater(bars[-1]["close"],setup["break_candle_high"])
        self.assertLess(setup["stop"],setup["break_candle_low"])

    def test_upside_break_then_close_below_break_candle_is_sell(self):
        bars=[{"time":i,"open":11,"high":11.5,"low":10.5,"close":11,"volume":10} for i in range(20)]
        bars[5].update({"high":12.0})
        bars[10].update({"open":12.2,"high":13.0,"low":12.1,"close":12.5})
        bars[-1].update({"open":12.0,"high":12.1,"low":11.4,"close":11.8})
        setup=strategy._find_reversal(bars,1.0)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"],"SELL")
        self.assertLess(bars[-1]["close"],setup["break_candle_low"])
        self.assertGreater(setup["stop"],setup["break_candle_high"])

    def test_no_signal_without_opposite_edge_close(self):
        bars=[{"time":i,"open":11,"high":12,"low":11,"close":11.5,"volume":10} for i in range(20)]
        bars[5]["low"]=10
        bars[10].update({"open":9.8,"high":10.2,"low":9,"close":9.5})
        bars[-1].update({"open":9.6,"high":10.0,"low":9.4,"close":10.1})
        self.assertIsNone(strategy._find_reversal(bars,1.0))

    def test_all_markets_and_timeframes_supported(self):
        self.assertEqual(len(strategy.MARKETS),7)
        self.assertEqual(strategy.TIMEFRAMES,("15m","1h","4h","1d","1w","1M"))
        self.assertEqual(set(strategy.FRAME_PROFILES),set(strategy.TIMEFRAMES))

    def test_engine_self_test(self):
        result=strategy.diagnostic_self_test()
        self.assertTrue(result["ok"],result)
        self.assertEqual(result["strategy_mode"],"FALSE_BREAKOUT_CLOSE_REVERSAL")


if __name__=="__main__":
    unittest.main()
