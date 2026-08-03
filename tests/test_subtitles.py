import tempfile
import unittest
from pathlib import Path

from vlog_director.subtitles import write_ass_subtitles


class SubtitleTests(unittest.TestCase):
    def test_ass_writer_sorts_and_escapes_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "captions.ass"
            write_ass_subtitles(
                [
                    {"start_sec": 2.0, "end_sec": 3.25, "text": "第二句"},
                    {
                        "start_sec": 0.5,
                        "end_sec": 1.5,
                        "text": "第一句{测试}",
                        "position": "top_center",
                    },
                ],
                output,
            )
            raw = output.read_bytes()
            content = raw.decode("utf-8")

            self.assertIn("Dialogue: 0,0:00:00.50,0:00:01.50", content)
            self.assertIn("Style: Bottom", content)
            self.assertIn("Style: Top", content)
            self.assertIn("TopBox,,0,0,0,,", content)
            self.assertIn("Dialogue: 1,0:00:00.50,0:00:01.50,Top", content)
            self.assertIn(r"第一句\{测试\}", content)
            self.assertLess(content.index("第一句"), content.index("第二句"))
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_ass_writer_applies_safe_area_wrap_and_background(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "captions.ass"
            write_ass_subtitles(
                [
                    {
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "text": "一二三四五六七八九十十一十二",
                    }
                ],
                output,
                font_size=64,
                minimum_font_size=42,
                max_lines=2,
                max_chars_per_line=6,
                safe_margin_percent=10,
                background_opacity_percent=50,
            )
            content = output.read_text(encoding="utf-8")

            self.assertIn("PlayResX: 1920", content)
            self.assertIn("PlayResY: 1080", content)
            self.assertIn(",192,192,108,1", content)
            self.assertIn("&H80101010", content)
            self.assertIn(r"\N", content)

    def test_ass_writer_ignores_far_away_punctuation_when_balancing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "captions.ass"
            write_ass_subtitles(
                [
                    {
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "text": "一，二三四五六七八九十一二三四五六七八",
                    }
                ],
                output,
                font_size=60,
                minimum_font_size=60,
                max_chars_per_line=10,
            )
            content = output.read_text(encoding="utf-8")

            self.assertIn(r"一，二三四五六七八\N九十一二三四五六七八", content)
            self.assertNotIn(r"一，\N", content)

    def test_ass_writer_rejects_more_than_configured_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "max_lines"):
                write_ass_subtitles(
                    [
                        {
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "第一行\n第二行\n第三行",
                        }
                    ],
                    Path(temporary_directory) / "captions.ass",
                    max_lines=2,
                )

    def test_ass_writer_rejects_cue_that_rounds_to_zero_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "rounds to zero duration"):
                write_ass_subtitles(
                    [{"start_sec": 0.001, "end_sec": 0.004, "text": "brief"}],
                    Path(temporary_directory) / "captions.ass",
                )


if __name__ == "__main__":
    unittest.main()
