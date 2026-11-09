import math
import unittest
from rebuild.strategy import analyze, read_frame


def trend_rows(up=True, n=80):
    rows = []
    for i in range(n):
        drift = 0.45 * i if up else -0.45 * i
        wave = math.sin(i * math.pi / 2) * 1.8
        close = 100 + drift + wave
        op = close - (0.25 if up else -0.25)
        high = max(op, close) + 0.25
        low = min(op, close) - 0.25
        rows.append([i, op, high, low, close, 1000 + i * 5])
    rows.append([n, rows[-1][4], rows[-1][4] + 0.2, rows[-1][4] - 0.2, rows[-1][4], 1000])
    return rows


class StrategyTests(unittest.TestCase):
    def test_insufficient_data_waits(self):
        self.assertEqual(read_frame("1w", []).direction, "WAIT")

    def test_conflicting_daily_blocks(self):
        result = analyze({"1w": trend_rows(True), "1d": trend_rows(False), "4h": trend_rows(True)}, "futures")
        self.assertEqual(result.status, "BLOCKED")

    def test_cash_market_does_not_short(self):
        result = analyze({"1w": trend_rows(False), "1d": trend_rows(False), "4h": trend_rows(False)}, "spot")
        self.assertEqual(result.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
