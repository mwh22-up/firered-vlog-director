from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from vlog_director.ffmpeg import run_command
from vlog_director.renderers import render_enhanced_video


class RendererIntegrationTests(unittest.TestCase):
    def test_lavfi_source_runs_through_real_enhancement_renderer(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        self.assertTrue(Path(ffmpeg).is_file())

        with tempfile.TemporaryDirectory(prefix="firered-ffmpeg-") as temporary:
            project = Path(temporary)
            base_video = project / "synthetic-base.mkv"
            output_video = project / "rendered.mp4"

            run_command(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=10:duration=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base_video),
                ]
            )

            rendered = render_enhanced_video(
                project,
                base_video,
                {
                    "music": {"tracks": []},
                    "subtitles": {"cues": []},
                    "illustration_motion": {"items": []},
                },
                output_video,
                executable=ffmpeg,
            )

            self.assertEqual(rendered, output_video)
            self.assertTrue(output_video.is_file())
            self.assertGreater(output_video.stat().st_size, 0)
            filter_script = output_video.with_suffix(".filters.txt")
            self.assertIn("loudnorm", filter_script.read_text(encoding="utf-8"))

            run_command(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(output_video),
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a:0",
                    "-f",
                    "null",
                    os.devnull,
                ]
            )


if __name__ == "__main__":
    unittest.main()
