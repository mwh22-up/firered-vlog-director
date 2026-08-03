import unittest

from vlog_director.overlays import anchor_expression, build_overlay_filters


class OverlayTests(unittest.TestCase):
    def test_anchor_uses_canvas_relative_safe_margin(self) -> None:
        self.assertEqual(
            anchor_expression("top_left", 5.0),
            ("W*0.050000", "H*0.050000"),
        )
        self.assertEqual(
            anchor_expression("bottom_right", 8.0),
            ("W-w-W*0.080000", "H-h-H*0.080000"),
        )

    def test_fade_overlay_consumes_timing_scale_and_animation(self) -> None:
        filters, label, required = build_overlay_filters(
            1,
            1,
            "base",
            {
                "start_sec": 10.0,
                "end_sec": 14.0,
                "anchor": "top_left",
                "animation": "fade",
                "animation_duration_sec": 0.4,
                "scale_percent": 40.0,
                "margin_percent": 6.0,
            },
            1920,
        )
        text = ";".join(filters)

        self.assertEqual(label, "video_overlay_1")
        self.assertIn("scale=w=768:h=-1:flags=lanczos", text)
        self.assertIn("fade=t=in:st=10.000:d=0.400:alpha=1", text)
        self.assertIn("fade=t=out:st=13.600:d=0.400:alpha=1", text)
        self.assertIn("between(t,10.000,14.000)", text)
        self.assertTrue({"scale", "format", "setpts", "overlay", "fade"} <= required)

    def test_slide_overlay_animates_in_and_out_from_nearest_edge(self) -> None:
        filters, _, required = build_overlay_filters(
            2,
            3,
            "base",
            {
                "start_sec": 2.0,
                "end_sec": 6.0,
                "anchor": "top_right",
                "animation": "slide",
                "scale_percent": 30.0,
            },
            1280,
        )
        text = ";".join(filters)

        self.assertIn("scale=w=384:h=-1:flags=lanczos", text)
        self.assertIn("if(lt(t,2.350)", text)
        self.assertIn("if(lt(t,5.650)", text)
        self.assertIn("(W)-(", text)
        self.assertNotIn("fade=", text)
        self.assertEqual(required, {"scale", "format", "setpts", "overlay"})

    def test_unknown_or_overlong_animation_fails_closed(self) -> None:
        for animation, duration in (("pop", None), ("fade", 1.0)):
            with self.subTest(animation=animation, duration=duration):
                item = {
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "anchor": "center",
                    "animation": animation,
                    "scale_percent": 25.0,
                }
                if duration is not None:
                    item["animation_duration_sec"] = duration
                with self.assertRaises(ValueError):
                    build_overlay_filters(1, 1, "base", item, 1920)


if __name__ == "__main__":
    unittest.main()
