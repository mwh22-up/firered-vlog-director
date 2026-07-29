import unittest

from vlog_director.intervals import interval_coverage, merge_intervals


class IntervalTests(unittest.TestCase):
    def test_merge_intervals_avoids_double_counting(self) -> None:
        self.assertEqual(merge_intervals([(1, 5), (3, 7), (8, 9)]), [(1.0, 7.0), (8.0, 9.0)])

    def test_coverage_clips_to_required_interval(self) -> None:
        self.assertEqual(interval_coverage(10, 20, [(0, 12), (18, 30)]), 0.4)


if __name__ == "__main__":
    unittest.main()
