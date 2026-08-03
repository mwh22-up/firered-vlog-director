import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.ffmpeg import FFmpegError, find_ffmpeg, require_filters


class FFmpegResolutionTests(unittest.TestCase):
    def test_vlog_ffmpeg_home_resolves_bundled_tools_before_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ffprobe = Path(directory) / "ffprobe.exe"
            ffprobe.write_bytes(b"tool")
            with (
                patch.dict(os.environ, {"VLOG_FFMPEG_HOME": directory}),
                patch("vlog_director.ffmpeg.shutil.which", return_value=None),
            ):
                resolved = find_ffmpeg("ffprobe")

        self.assertEqual(Path(resolved), ffprobe.resolve())

    def test_path_lookup_remains_the_fallback(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "vlog_director.ffmpeg.shutil.which",
                return_value="C:/tools/ffmpeg.exe",
            ),
        ):
            self.assertEqual(find_ffmpeg(), "C:/tools/ffmpeg.exe")

    def test_filter_inventory_requires_an_exact_filter_name(self) -> None:
        inventory = " ... ass V->V Render ASS subtitles onto input video using libass.\n"
        completed = subprocess.CompletedProcess(
            args=["ffmpeg", "-filters"],
            returncode=0,
            stdout=inventory,
            stderr="",
        )
        with (
            patch("vlog_director.ffmpeg.find_ffmpeg", return_value="ffmpeg"),
            patch("vlog_director.ffmpeg.subprocess.run", return_value=completed),
            self.assertRaisesRegex(FFmpegError, "subtitles"),
        ):
            require_filters("ffmpeg", {"subtitles"})


if __name__ == "__main__":
    unittest.main()
