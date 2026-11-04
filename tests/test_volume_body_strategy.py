import unittest

from app import volume_body_setup


def candle(open_price, high, low, close, volume, stamp):
    return [stamp, open_price, high, low, close, volume]


class VolumeBodyStrategyTests(unittest.TestCase):
    def make_rows(self, side):
        rows = [candle(100, 140, 60, 100, 100, i) for i in range(20)]
        if side == "BUY":
            rows.append(candle(100, 150, 50, 110, 250, 20))
            rows.append(candle(110, 115, 105, 108, 100, 21))
            rows.append(candle(108, 112, 106, 107, 100, 22))
        else:
            rows.append(candle(110, 150, 50, 100, 250, 20))
            rows.append(candle(100, 105, 95, 98, 100, 21))
            rows.append(candle(98, 102, 94, 103, 100, 22))
        rows.append(candle(103, 120, 80, 110, 100, 23))
        return rows

    def test_buy_uses_body_midpoint_stop_and_extended_targets(self):
        setup = volume_body_setup(self.make_rows("BUY"))
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "BUY")
        self.assertAlmostEqual(setup["entry"], 107)
        self.assertAlmostEqual(setup["stop"], 104.5)
        self.assertAlmostEqual(setup["tp1"], 128.16)
        self.assertAlmostEqual(setup["tp2"], 129.16)
        self.assertAlmostEqual(setup["tp3"], 130.0)
        self.assertLess(setup["stop"], 105)
        self.assertLess(setup["entry"], setup["tp1"] < setup["tp2"] < setup["tp3"])

    def test_sell_is_inverse_and_uses_body_only(self):
        setup = volume_body_setup(self.make_rows("SELL"))
        self.assertIsNotNone(setup)
        self.assertEqual(setup["side"], "SELL")
        self.assertAlmostEqual(setup["entry"], 103)
        self.assertAlmostEqual(setup["stop"], 105.5)
        self.assertAlmostEqual(setup["tp1"], 81.84)
        self.assertAlmostEqual(setup["tp2"], 80.84)
        self.assertAlmostEqual(setup["tp3"], 80.0)
        self.assertGreater(setup["stop"], 105)
        self.assertGreater(setup["entry"], setup["tp1"] > setup["tp2"] > setup["tp3"])

    def test_rejects_volume_below_threshold(self):
        rows = self.make_rows("BUY")
        rows[20][5] = 150
        self.assertIsNone(volume_body_setup(rows))


if __name__ == "__main__":
    unittest.main()
