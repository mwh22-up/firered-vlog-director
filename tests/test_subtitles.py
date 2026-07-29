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
                    {"start_sec": 0.5, "end_sec": 1.5, "text": "第一句{测试}"},
                ],
                output,
            )
            content = output.read_text(encoding="utf-8-sig")

            self.assertIn("Dialogue: 0,0:00:00.50,0:00:01.50", content)
            self.assertIn(r"第一句\{测试\}", content)
            self.assertLess(content.index("第一句"), content.index("第二句"))


if __name__ == "__main__":
    unittest.main()
