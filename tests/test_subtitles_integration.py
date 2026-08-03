from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vlog_director.subtitles import write_ass_subtitles


class SubtitleIntegrationTests(unittest.TestCase):
    def test_libass_renders_translucent_box_and_top_bottom_positions(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("ffmpeg is unavailable")
        filters = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        if " subtitles " not in filters:
            self.skipTest("ffmpeg subtitles/libass filter is unavailable")

        width = 640
        height = 360
        frame_bytes = width * height * 3
        with tempfile.TemporaryDirectory(prefix="firered-subtitles-") as temporary:
            subtitle_path = Path(temporary) / "captions.ass"
            write_ass_subtitles(
                [
                    {
                        "start_sec": 0.0,
                        "end_sec": 0.9,
                        "text": "Top subtitle background",
                        "position": "top_center",
                    },
                    {
                        "start_sec": 1.0,
                        "end_sec": 1.9,
                        "text": "Bottom subtitle background",
                        "position": "bottom_center",
                    },
                ],
                subtitle_path,
                font_name="Arial",
                font_size=32,
                minimum_font_size=24,
                margin_v=20,
                safe_margin_percent=10,
                canvas_width=width,
                canvas_height=height,
                max_chars_per_line=30,
                background_opacity_percent=50,
                background_padding=6,
            )
            escaped = str(subtitle_path).replace("\\", "/").replace(":", r"\:")
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=white:s={width}x{height}:r=1:d=2",
                    "-vf",
                    f"subtitles=filename='{escaped}'",
                    "-frames:v",
                    "2",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
                check=True,
                capture_output=True,
            )

        self.assertEqual(len(result.stdout), frame_bytes * 2)
        frames = [
            result.stdout[index * frame_bytes : (index + 1) * frame_bytes]
            for index in range(2)
        ]
        centroids = []
        for frame in frames:
            changed_y = []
            translucent_pixels = 0
            for pixel in range(width * height):
                red, green, blue = frame[pixel * 3 : pixel * 3 + 3]
                if min(red, green, blue) < 245:
                    changed_y.append(pixel // width)
                if 80 <= red <= 200 and abs(red - green) <= 3 and abs(red - blue) <= 3:
                    translucent_pixels += 1
            self.assertGreater(translucent_pixels, 100)
            self.assertTrue(changed_y)
            centroids.append(sum(changed_y) / len(changed_y))
        self.assertLess(centroids[0], height / 2)
        self.assertGreater(centroids[1], height / 2)
