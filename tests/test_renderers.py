import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.renderers import (
    _anchor_expression,
    _gain_to_linear,
    _music_filter_chain,
    render_enhanced_video,
)


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

    def test_music_filter_defaults_missing_fades_to_no_fade(self) -> None:
        chain = _music_filter_chain(
            1,
            {
                "start_sec": 0.0,
                "end_sec": 4.0,
                "gain_db": -18.0,
            },
            "music_1",
        )

        self.assertNotIn("afade=", chain)
        self.assertIn("adelay=0|0", chain)

    def test_renderer_respects_disabled_ducking_with_legacy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            music = project / "assets" / "music" / "bed.wav"
            output = project / "output.mp4"
            base_video.write_bytes(b"base")
            music.parent.mkdir(parents=True)
            music.write_bytes(b"music")
            plan = {
                "music": {
                    "tracks": [
                        {
                            "source": "assets/music/bed.wav",
                            "start_sec": 0.0,
                            "end_sec": 4.0,
                            "gain_db": -20.0,
                        }
                    ],
                    "ducking": {"enabled": False},
                },
                "subtitles": {"cues": []},
                "illustration_motion": {"items": []},
            }

            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters") as require_filters,
                patch("vlog_director.renderers.run_command"),
            ):
                render_enhanced_video(project, base_video, plan, output)

            required = require_filters.call_args.args[1]
            self.assertNotIn("sidechaincompress", required)
            filter_text = output.with_suffix(".filters.txt").read_text(encoding="utf-8")
            self.assertNotIn("sidechaincompress", filter_text)
            self.assertIn("[dialogue_normalized][music_bed]", filter_text)


if __name__ == "__main__":
    unittest.main()
