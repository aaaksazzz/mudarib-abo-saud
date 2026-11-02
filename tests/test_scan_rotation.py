import unittest

from scan_rotation import select_scan_batch, select_priority_scan_batch


class ScanRotationTests(unittest.TestCase):
    def test_batches_cover_full_universe_without_duplicates(self):
        rows = list(range(95))
        seen = []
        offset = 0
        for _ in range(3):
            batch, offset, _ = select_scan_batch(rows, offset, 40)
            seen.extend(batch)
        self.assertEqual(len(seen), 95)
        self.assertEqual(set(seen), set(rows))

    def test_twenty_asset_batches_move_forward_without_repeating(self):
        rows = list(range(53))
        seen = []
        offset = 0
        sizes = []
        for _ in range(3):
            batch, offset, start = select_scan_batch(rows, offset, 20)
            seen.extend(batch)
            sizes.append(len(batch))
        self.assertEqual(sizes, [20, 20, 13])
        self.assertEqual(seen, rows)
        self.assertEqual(offset, 0)

    def test_small_universe_returns_all_rows(self):
        batch, next_offset, start = select_scan_batch(["a", "b"], 0, 40)
        self.assertEqual(batch, ["a", "b"])
        self.assertEqual(next_offset, 0)
        self.assertEqual(start, 0)

    def test_last_batch_does_not_wrap_and_duplicate_prior_assets(self):
        batch, next_offset, start = select_scan_batch([0, 1, 2, 3, 4], 4, 3)
        self.assertEqual(batch, [4])
        self.assertEqual(next_offset, 0)
        self.assertEqual(start, 4)

    def test_priority_assets_are_rescanned_and_remainder_rotates(self):
        rows = list(range(100))
        first, offset, _, priority = select_priority_scan_batch(rows, 0, 40, 10)
        second, offset2, _, priority2 = select_priority_scan_batch(rows, offset, 40, 10)
        self.assertEqual(first[:10], list(range(10)))
        self.assertEqual(second[:10], list(range(10)))
        self.assertEqual(first[10:], list(range(10, 40)))
        self.assertEqual(second[10:], list(range(40, 70)))
        self.assertEqual(priority, 10)
        self.assertEqual(priority2, 10)
        self.assertEqual(offset2, 60)

    def test_priority_scan_handles_small_universe(self):
        rows = ["a", "b", "c"]
        batch, next_offset, start, priority = select_priority_scan_batch(rows, 0, 40, 10)
        self.assertEqual(batch, rows)
        self.assertEqual((next_offset, start, priority), (0, 0, 3))

    def test_empty_universe_is_safe(self):
        self.assertEqual(select_scan_batch([], 0, 40), ([], 0, 0))


if __name__ == "__main__":
    unittest.main()
