import unittest
from market_adapters import _aggregate_4h

class FourHourAggregationTests(unittest.TestCase):
    def test_aggregates_four_consecutive_bars_and_preserves_ohlcv(self):
        base = 1_800_000_000_000
        rows = [
            [base + i * 3_600_000, 100+i, 105+i, 98+i, 103+i, 10+i]
            for i in range(4)
        ]
        result = _aggregate_4h(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], [base, 100.0, 108.0, 98.0, 106.0, 46.0])

    def test_does_not_join_bars_across_overnight_gap(self):
        base = 1_800_000_000_000
        session_one = [
            [base + i * 3_600_000, 100, 102, 99, 101, 10]
            for i in range(3)
        ]
        next_day = base + 24 * 3_600_000
        session_two = [
            [next_day + i * 3_600_000, 200, 202, 199, 201, 20]
            for i in range(4)
        ]
        result = _aggregate_4h(session_one + session_two)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], next_day)
        self.assertEqual(result[0][1], 200.0)
        self.assertEqual(result[0][4], 201.0)
        self.assertEqual(result[0][5], 80.0)

    def test_drops_incomplete_four_hour_group(self):
        base = 1_800_000_000_000
        rows = [[base + i * 3_600_000, 1, 2, 0.5, 1.5, 3] for i in range(3)]
        self.assertEqual(_aggregate_4h(rows), [])

if __name__ == "__main__":
    unittest.main()
