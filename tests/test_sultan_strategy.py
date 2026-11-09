import unittest

import market_sultan_strategy as s


def trend_rows(slope=1.0, count=65):
    rows = []
    wave = (0, 1, 2, 1, 0, -1, -2, -1)
    for i in range(count):
        base = 100 + slope * i + wave[i % len(wave)] * 2.0
        close = base + (0.15 if slope > 0 else -0.15)
        rows.append([i * 3_600_000, close - 0.1, base + 1.5, base - 1.5, close, 1000])
    # The last row represents the still-open candle and is deliberately ignored.
    rows.append([count * 3_600_000, 1, 999, 0.1, 1, 999999])
    return rows


class SultanDirectionTests(unittest.TestCase):
    def test_detects_rising_structure(self):
        self.assertEqual(s._direction(trend_rows(1.0)), "UP")

    def test_detects_falling_structure(self):
        self.assertEqual(s._direction(trend_rows(-1.0)), "DOWN")

    def test_neutral_market_does_not_force_direction(self):
        self.assertEqual(s._direction(trend_rows(0.0)), "NEUTRAL")

    def test_two_timeframes_can_align_when_third_is_neutral(self):
        side, details = s.direction_stack(trend_rows(1.0), trend_rows(1.0), trend_rows(0.0))
        self.assertEqual(side, "BUY")
        self.assertEqual(details, {"1w": "UP", "1d": "UP", "4h": "NEUTRAL"})

    def test_opposing_higher_timeframe_blocks_entry(self):
        side, _ = s.direction_stack(trend_rows(1.0), trend_rows(1.0), trend_rows(-1.0))
        self.assertIsNone(side)

    def test_strategy_uses_only_higher_timeframe_context_and_15m_entry(self):
        self.assertEqual(s.TIMEFRAMES, ("1w", "1d", "4h", "15m"))
        self.assertEqual(s.ENTRY_TIMEFRAME, "15m")
        self.assertEqual(s.DIRECTION_TIMEFRAMES, ("1w", "1d", "4h"))


if __name__ == "__main__":
    unittest.main()
