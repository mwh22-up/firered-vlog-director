import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.ffmpeg import find_ffmpeg


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


if __name__ == "__main__":
    unittest.main()