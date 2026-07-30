import unittest

from vlog_director.renderers import _anchor_expression, _gain_to_linear, _music_filter_chain


class RendererTests(unittest.TestCase):
    def test_gain_conversion(self) -> None:
        self.assertAlmostEqual(_gain_to_linear(-20), 0.1)
        self.assertAlmostEqual(_gain_to_linear(0), 1.0)

    def test_anchor_expressions(self) -> None:
        self.assertEqual(_anchor_expression("top_left"), ("40", "40"))
        self.assertEqual(_anchor_expression("bottom_right"), ("W-w-40", "H-h-40"))

    def test_music_filter_applies_fades_gain_and_delay(self) -> None:
        chain = _music_filter_chain(
            2,
            {
                "start_sec": 5.0,
                "end_sec": 15.0,
                "gain_db": -20.0,
                "fade_in_sec": 1.0,
                "fade_out_sec": 2.0,
            },
            "music_1",
        )
        self.assertIn("afade=t=in:st=0:d=1.000", chain)
        self.assertIn("afade=t=out:st=8.000:d=2.000", chain)
        self.assertIn("adelay=5000|5000", chain)
        self.assertIn("volume=0.10000000", chain)


if __name__ == "__main__":
    unittest.main()
