import unittest

from app import liquidity_sweep_3r_setup


def candle(open_price, high, low, close, volume, stamp):
    return [stamp, open_price, high, low, close, volume]


class LiquiditySweep3RTests(unittest.TestCase):
    def make_rows(self, side):
        rows = [candle(100.2, 101, 100, 100.5, 100, i) for i in range(20)]
        if side == "BUY":
            rows.extend([
                candle(100.2, 101, 99.5, 100.7, 100, 20),
                candle(100.7, 102, 100.6, 101.6, 160, 21),
                candle(101.0, 101.5, 100.9, 101.2, 100, 22),
            ])
        else:
            rows.extend([
                candle(100.8, 101.5, 100, 100.3, 100, 20),
                candle(100.3, 100.4, 99, 99.4, 160, 21),
                candle(99.8, 99.8, 99.4, 99.7, 100, 22),
            ])
        rows.append(candle(100, 101, 99, 100, 100, 23))  # forming candle; ignored
        return rows

    def test_buy_levels_are_exactly_one_two_and_three_r(self):
        setup = liquidity_sweep_3r_setup(self.make_rows("BUY"))
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")
        risk = setup["entry"] - setup["stop"]
        self.assertAlmostEqual(setup["tp1"] - setup["entry"], risk)
        self.assertAlmostEqual(setup["tp2"] - setup["entry"], 2 * risk)
        self.assertAlmostEqual(setup["tp3"] - setup["entry"], 3 * risk)
        self.assertLess(setup["stop"], setup["entry"])

    def test_sell_levels_are_exactly_one_two_and_three_r(self):
        setup = liquidity_sweep_3r_setup(self.make_rows("SELL"))
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "SELL")
        risk = setup["stop"] - setup["entry"]
        self.assertAlmostEqual(setup["entry"] - setup["tp1"], risk)
        self.assertAlmostEqual(setup["entry"] - setup["tp2"], 2 * risk)
        self.assertAlmostEqual(setup["entry"] - setup["tp3"], 3 * risk)
        self.assertGreater(setup["stop"], setup["entry"])

    def test_rejects_weak_breakout_volume(self):
        rows = self.make_rows("BUY")
        rows[-3][5] = 100
        self.assertIsNone(liquidity_sweep_3r_setup(rows))

    def test_ignores_unclosed_forming_candle(self):
        rows = self.make_rows("BUY")
        rows[-1] = candle(100, 200, 1, 199, 100000, 24)
        setup = liquidity_sweep_3r_setup(rows)
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")


if __name__ == "__main__":
    unittest.main()
