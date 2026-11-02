import unittest

from scan_rotation import select_scan_batch


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

    def test_empty_universe_is_safe(self):
        self.assertEqual(select_scan_batch([], 0, 40), ([], 0, 0))


if __name__ == "__main__":
    unittest.main()
