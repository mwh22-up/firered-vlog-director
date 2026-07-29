import unittest

from vlog_director.renderers import _anchor_expression, _gain_to_linear


class RendererTests(unittest.TestCase):
    def test_gain_conversion(self) -> None:
        self.assertAlmostEqual(_gain_to_linear(-20), 0.1)
        self.assertAlmostEqual(_gain_to_linear(0), 1.0)

    def test_anchor_expressions(self) -> None:
        self.assertEqual(_anchor_expression("top_left"), ("40", "40"))
        self.assertEqual(_anchor_expression("bottom_right"), ("W-w-40", "H-h-40"))


if __name__ == "__main__":
    unittest.main()
