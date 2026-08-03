from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vlog_director.subtitle_render_contract import (
    build_subtitle_render_contract,
    subtitle_filter_expression,
    write_contract_ass,
)


class SubtitleRenderContractTests(unittest.TestCase):
    def test_effective_style_scales_from_1080p_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            contract = build_subtitle_render_contract(
                project,
                {
                    "font_name": "Arial",
                    "font_size": 64,
                    "margin_v": 72,
                    "outline": 4,
                    "shadow": 1,
                    "bold": True,
                    "position": "bottom_center",
                    "max_lines": 2,
                    "safe_margin_percent": 8.0,
                    "max_chars_per_line": 18,
                    "background_opacity_percent": 42.0,
                    "background_padding": 8,
                },
                canvas_width=960,
                canvas_height=540,
            )

            self.assertEqual(contract.font_size, 32)
            self.assertEqual(contract.minimum_font_size, 30)
            self.assertEqual(contract.margin_v, 36)
            self.assertEqual(contract.outline, 2)
            self.assertEqual(contract.background_padding, 4)
            self.assertEqual(contract.canvas_width, 960)
            self.assertEqual(contract.canvas_height, 540)

    def test_ass_and_filter_use_the_same_contract_and_optional_fonts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            fonts = project / "assets" / "fonts"
            fonts.mkdir(parents=True)
            output = project / "work" / "subtitles" / "preview.ass"
            contract = build_subtitle_render_contract(
                project,
                {"font_name": "Arial", "font_size": 64},
                canvas_width=640,
                canvas_height=360,
            )

            write_contract_ass(
                [{"cue_id": "cue-a", "start_sec": 0.0, "end_sec": 1.0, "text": "字幕"}],
                contract,
                output,
            )
            expression = subtitle_filter_expression(output, contract)

            self.assertIn("subtitles=filename=", expression)
            self.assertIn("fontsdir=", expression)
            self.assertIn("WrapStyle: 2", output.read_text(encoding="utf-8"))

    def test_invalid_canvas_and_boolean_numeric_style_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            with self.assertRaises(ValueError):
                build_subtitle_render_contract(
                    project,
                    {},
                    canvas_width=0,
                    canvas_height=1080,
                )
            with self.assertRaises(ValueError):
                build_subtitle_render_contract(
                    project,
                    {"font_size": True},
                    canvas_width=1920,
                    canvas_height=1080,
                )


if __name__ == "__main__":
    unittest.main()
