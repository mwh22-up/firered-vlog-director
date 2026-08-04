import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.media_features import probe_media


class MediaFeatureProbeTests(unittest.TestCase):
    def test_analysis_probe_uses_ffmpeg_without_resolving_ffprobe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "clip.mp4"
            media.write_bytes(b"media")
            with (
                patch(
                    "vlog_director.media_features.find_ffmpeg",
                    return_value="C:/tools/ffmpeg.exe",
                ) as resolve,
                patch(
                    "vlog_director.media_features.probe_media_with_ffmpeg",
                    return_value={
                        "duration_sec": 3.25,
                        "width": 1920,
                        "height": 1080,
                        "has_video": True,
                        "has_audio": True,
                        "video_start_sec": 0.0,
                        "audio_start_sec": 0.0,
                    },
                ) as ffmpeg_probe,
            ):
                result = probe_media(media)

        resolve.assert_called_once_with()
        ffmpeg_probe.assert_called_once_with(
            "C:/tools/ffmpeg.exe",
            media.resolve(),
        )
        self.assertEqual(result["duration_sec"], 3.25)
        self.assertEqual(result["size_bytes"], 5)
        self.assertEqual(
            [stream["codec_type"] for stream in result["streams"]],
            ["video", "audio"],
        )


if __name__ == "__main__":
    unittest.main()
