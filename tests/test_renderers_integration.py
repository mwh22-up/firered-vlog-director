from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageDraw

from vlog_director.audio_qa import parse_ebur128
from vlog_director.ffmpeg import probe_media, run_command
from vlog_director.renderers import render_enhanced_video


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _ready_subtitle_source(project: Path, cues: list[dict]) -> dict:
    source_path = project / "work" / "subtitles" / "reviewed.json"
    _write_json(
        source_path,
        {
            "status": "ready",
            "coverage": {"status": "verified"},
            "cues": cues,
        },
    )
    return {
        "source": "work/subtitles/reviewed.json",
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }


def _ready_music_metadata(project: Path, tracks: list[dict]) -> dict:
    manifest_path = project / "assets" / "music" / "rights.json"
    assets = []
    auditions = []
    for track in tracks:
        source_path = project / track["source"]
        assets.append(
            {
                "id": track["id"],
                "path": source_path.relative_to(manifest_path.parent).as_posix(),
                "size_bytes": source_path.stat().st_size,
                "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            }
        )
        auditions.append({"id": track["id"], "audition_status": "passed"})
    _write_json(
        manifest_path,
        {
            "rights_approval": {
                "status": "approved",
                "rights_holder": "Project Owner",
                "approved_by": "Project Owner",
                "approved_at": "2026-08-03T12:00:00Z",
                "required_scope": [
                    "synchronize",
                    "modify",
                    "render",
                    "distribute_with_project",
                ],
            },
            "assets": assets,
        },
    )
    audition_path = project / "work" / "qa" / "audition.json"
    _write_json(
        audition_path,
        {"status": "passed", "blocking_items": [], "assets": auditions},
    )
    return {
        "rights_manifest": "assets/music/rights.json",
        "audition_report": "work/qa/audition.json",
    }


class RendererIntegrationTests(unittest.TestCase):
    @staticmethod
    def _frame_bytes(ffmpeg: str, media: Path, time_sec: float) -> bytes:
        return subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(time_sec),
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            capture_output=True,
        ).stdout

    @staticmethod
    def _mean_volume(
        ffmpeg: str,
        media: Path,
        start_sec: float,
        *,
        audio_filter: str = "volumedetect",
    ) -> float:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-ss",
                str(start_sec),
                "-i",
                str(media),
                "-t",
                "0.35",
                "-map",
                "0:a:0",
                "-af",
                audio_filter,
                "-f",
                "null",
                os.devnull,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        match = re.search(
            r"mean_volume:\s*(-?inf|-?\d+(?:\.\d+)?) dB",
            completed.stderr,
        )
        if match is None:
            raise AssertionError("FFmpeg did not report mean_volume")
        return -120.0 if match.group(1) == "-inf" else float(match.group(1))

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
                video_preset="veryfast",
                video_crf=24,
            )

            self.assertEqual(rendered, output_video)
            self.assertTrue(output_video.is_file())
            self.assertGreater(output_video.stat().st_size, 0)
            self.assertFalse(output_video.with_suffix(".filters.txt").exists())
            self.assertFalse(output_video.with_suffix(".ass").exists())
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

    def test_realized_segment_treatments_change_pixels_audio_and_keep_tail(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-treatments-") as temporary:
            project = Path(temporary)
            base_video = project / "base.mkv"
            output_video = project / "treated.mp4"
            run_command(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-itsoffset",
                    "0.066",
                    "-i",
                    "color=c=gray:size=160x90:rate=20:duration=3.234",
                    "-f",
                    "lavfi",
                    "-itsoffset",
                    "0.045",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=3.255",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    str(base_video),
                ]
            )

            def treatment(
                segment_id: str,
                *,
                gain_db: float = 0.0,
                preserve: bool = True,
                mute: bool = False,
                exposure_ev: float = 0.0,
            ) -> dict:
                return {
                    "segment_id": segment_id,
                    "stabilization": {
                        "mode": "off",
                        "strength": 0.0,
                        "max_crop_percent": 0.0,
                    },
                    "continuity": {
                        "transition": "hard_cut",
                        "duration_sec": 0.0,
                        "match_action": False,
                    },
                    "audio": {
                        "preserve_original": preserve,
                        "normalize_dialogue": False,
                        "gain_db": gain_db,
                        "mute": mute,
                    },
                    "visual": {"exposure_ev": exposure_ev, "speed": 1.0},
                }

            plan = {
                "video_treatments": [
                    treatment("segment-1", gain_db=-12.0, exposure_ev=0.6),
                    treatment("segment-2", preserve=False, mute=True),
                    treatment("segment-3"),
                ],
                "music": {"tracks": []},
                "subtitles": {"cues": []},
                "illustration_motion": {"items": []},
            }
            realized = {
                "duration_sec": 3.3,
                "base_size_bytes": base_video.stat().st_size,
                "base_sha256": hashlib.sha256(base_video.read_bytes()).hexdigest(),
                "segments": [
                    {"segment_id": "segment-1", "start_sec": 0.0, "end_sec": 0.9},
                    {"segment_id": "segment-2", "start_sec": 0.9, "end_sec": 2.1},
                    {"segment_id": "segment-3", "start_sec": 2.1, "end_sec": 3.3},
                ],
            }
            render_enhanced_video(
                project,
                base_video,
                plan,
                output_video,
                executable=ffmpeg,
                realized_timeline=realized,
                video_preset="veryfast",
                video_crf=24,
            )

            def frame_mean(time_sec: float) -> float:
                frame = self._frame_bytes(ffmpeg, output_video, time_sec)
                self.assertTrue(frame)
                return sum(frame) / len(frame)

            def video_frame_stats() -> list[tuple[float, float]]:
                completed = subprocess.run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-nostats",
                        "-i",
                        str(output_video),
                        "-map",
                        "0:v:0",
                        "-vf",
                        "showinfo",
                        "-an",
                        "-f",
                        "null",
                        os.devnull,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                frames: list[tuple[float, float]] = []
                for line in completed.stderr.splitlines():
                    timestamp = re.search(r"pts_time:([-+0-9.eE]+)", line)
                    mean = re.search(r"mean:\[([0-9.]+)", line)
                    if timestamp and mean:
                        frames.append((float(timestamp.group(1)), float(mean.group(1))))
                self.assertTrue(frames)
                return frames

            self.assertGreater(frame_mean(0.4), frame_mean(2.7) + 20.0)
            quiet = self._mean_volume(ffmpeg, output_video, 0.3)
            muted = self._mean_volume(ffmpeg, output_video, 1.3)
            normal = self._mean_volume(ffmpeg, output_video, 2.6)
            self.assertGreater(normal - quiet, 9.0)
            self.assertLess(muted, quiet - 20.0)
            output_media = probe_media(ffmpeg, output_video)
            base_media = probe_media(ffmpeg, base_video)
            self.assertAlmostEqual(float(output_media["duration_sec"]), 3.3, delta=0.06)
            self.assertAlmostEqual(
                float(output_media["video_start_sec"])
                - float(output_media["audio_start_sec"]),
                float(base_media["video_start_sec"])
                - float(base_media["audio_start_sec"]),
                delta=1 / 20,
            )
            frames = video_frame_stats()
            threshold = (
                max(mean for _, mean in frames) + min(mean for _, mean in frames)
            ) / 2
            first_normal_pts = next(pts for pts, mean in frames if mean < threshold)
            self.assertAlmostEqual(
                first_normal_pts,
                0.9 + float(output_media["video_start_sec"]),
                delta=1 / 20,
            )
            self.assertGreaterEqual(frames[-1][0], 3.2)
            self.assertGreater(frame_mean(3.2), 0.0)

    def test_real_ffmpeg_composes_fade_overlay_and_verified_subtitle(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.skipTest("system ffmpeg is unavailable")
        available = subprocess.run(
            [ffmpeg, "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        if " subtitles " not in available:
            self.skipTest("system ffmpeg has no subtitles/libass filter")

        width = 640
        height = 360
        with tempfile.TemporaryDirectory(prefix="firered-compose-") as temporary:
            project = Path(temporary)
            base_video = project / "base.mkv"
            output_video = project / "composed.mp4"
            overlay_path = project / "assets" / "illustrations" / "title.png"
            overlay_path.parent.mkdir(parents=True)
            overlay = Image.new("RGBA", (300, 80), (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rectangle(
                (0, 0, 299, 79),
                fill=(220, 30, 30, 230),
            )
            overlay.save(overlay_path)
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
                    f"color=c=gray:size={width}x{height}:rate=10:duration=3",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        "aevalsrc=0.7*sin(2*PI*1000*t)*"
                        "between(t\\,1\\,2):s=48000:d=3"
                    ),
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base_video),
                ]
            )

            plan = {
                "music": {"status": "planned", "tracks": []},
                "illustration_motion": {
                    "status": "ready",
                    "items": [
                        {
                            "id": "title",
                            "type": "title_card",
                            "source": "assets/illustrations/title.png",
                            "start_sec": 0.5,
                            "end_sec": 2.5,
                            "anchor": "top_left",
                            "animation": "fade",
                            "animation_duration_sec": 0.3,
                            "scale_percent": 40.0,
                            "margin_percent": 5.0,
                        }
                    ],
                },
                "subtitles": {
                    "status": "ready",
                    "coverage": {"status": "verified"},
                    "cues": [
                        {
                            "start_sec": 0.5,
                            "end_sec": 2.5,
                            "text": "Verified subtitle",
                            "review_status": "verified",
                        }
                    ],
                    "style": {
                        "position": "bottom_center",
                        "max_lines": 2,
                        "safe_margin_percent": 8.0,
                        "font_name": "Arial",
                        "font_size": 64,
                        "margin_v": 72,
                        "outline": 4,
                        "shadow": 1,
                        "bold": True,
                        "max_chars_per_line": 18,
                        "background_opacity_percent": 45.0,
                        "background_padding": 8,
                    },
                },
            }
            plan["subtitles"].update(
                _ready_subtitle_source(project, plan["subtitles"]["cues"])
            )
            render_enhanced_video(
                project,
                base_video,
                plan,
                output_video,
                executable=ffmpeg,
                video_preset="veryfast",
                video_crf=24,
            )

            before = self._frame_bytes(ffmpeg, output_video, 0.2)
            active = self._frame_bytes(ffmpeg, output_video, 1.2)
            after = self._frame_bytes(ffmpeg, output_video, 2.8)
            self.assertEqual(len(active), width * height * 3)
            overlay_pixel = (30 * width + 50) * 3
            self.assertGreater(active[overlay_pixel], active[overlay_pixel + 1] + 80)
            self.assertLess(abs(before[overlay_pixel] - before[overlay_pixel + 1]), 8)
            self.assertLess(abs(after[overlay_pixel] - after[overlay_pixel + 1]), 8)
            bottom_start = width * (height // 2) * 3
            bottom_differences = sum(
                abs(active[index] - before[index]) > 15
                for index in range(bottom_start, len(active))
            )
            self.assertGreater(bottom_differences, 300)
            self.assertFalse(output_video.with_suffix(".ass").exists())
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

    def test_music_ducking_master_targets_loudness_and_true_peak(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-music-") as temporary:
            project = Path(temporary)
            base_video = project / "base.mkv"
            music = project / "assets" / "music" / "bed.wav"
            output_video = project / "mixed.mp4"
            unducked_output = project / "mixed-unducked.mp4"
            music.parent.mkdir(parents=True)
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
                    "color=c=gray:size=160x90:rate=10:duration=3",
                    "-f",
                    "lavfi",
                    "-i",
                    (
                        "aevalsrc=0.7*sin(2*PI*1000*t)*"
                        "between(t\\,1\\,2):s=48000:d=3"
                    ),
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base_video),
                ]
            )
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
                    "sine=frequency=220:sample_rate=48000:duration=3",
                    "-af",
                    "volume=12dB",
                    "-c:a",
                    "pcm_s16le",
                    str(music),
                ]
            )
            plan = {
                "music": {
                    "status": "ready",
                    "tracks": [
                        {
                            "id": "bed",
                            "source": "assets/music/bed.wav",
                            "start_sec": 0.0,
                            "end_sec": 3.0,
                            "gain_db": -3.0,
                            "fade_in_sec": 0.2,
                            "fade_out_sec": 0.2,
                        }
                    ],
                    "ducking": {
                        "enabled": True,
                        "threshold": 0.03,
                        "ratio": 20.0,
                        "attack_ms": 20,
                        "release_ms": 250,
                    },
                },
                "subtitles": {"cues": []},
                "illustration_motion": {"items": []},
            }
            plan["music"].update(
                _ready_music_metadata(project, plan["music"]["tracks"])
            )
            render_enhanced_video(
                project,
                base_video,
                plan,
                output_video,
                executable=ffmpeg,
                video_preset="veryfast",
                video_crf=24,
            )
            measured = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(output_video),
                    "-map",
                    "0:a:0",
                    "-af",
                    "ebur128=peak=true",
                    "-f",
                    "null",
                    os.devnull,
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            levels = parse_ebur128(measured.stderr)
            self.assertIsNotNone(levels["integrated_lufs"])
            self.assertIsNotNone(levels["true_peak_dbfs"])
            self.assertGreaterEqual(levels["integrated_lufs"], -18.0)
            self.assertLessEqual(levels["integrated_lufs"], -14.0)
            self.assertLessEqual(levels["true_peak_dbfs"], -1.0)
            plan["music"]["ducking"]["enabled"] = False
            render_enhanced_video(
                project,
                base_video,
                plan,
                unducked_output,
                executable=ffmpeg,
                video_preset="veryfast",
                video_crf=24,
            )
            music_band_filter = "bandpass=f=220:width_type=h:w=30,volumedetect"
            dialogue_band_filter = (
                "bandpass=f=1000:width_type=h:w=60,volumedetect"
            )

            def music_to_dialogue_ratio(media: Path) -> float:
                music_level = self._mean_volume(
                    ffmpeg,
                    media,
                    1.35,
                    audio_filter=music_band_filter,
                )
                dialogue_level = self._mean_volume(
                    ffmpeg,
                    media,
                    1.35,
                    audio_filter=dialogue_band_filter,
                )
                return music_level - dialogue_level

            ducked_ratio = music_to_dialogue_ratio(output_video)
            unducked_ratio = music_to_dialogue_ratio(unducked_output)
            self.assertGreater(unducked_ratio - ducked_ratio, 4.0)

            ducked_music_without_dialogue = self._mean_volume(
                ffmpeg,
                output_video,
                0.45,
                audio_filter=music_band_filter,
            )
            ducked_music_with_dialogue = self._mean_volume(
                ffmpeg,
                output_video,
                1.35,
                audio_filter=music_band_filter,
            )
            unducked_music_without_dialogue = self._mean_volume(
                ffmpeg,
                unducked_output,
                0.45,
                audio_filter=music_band_filter,
            )
            unducked_music_with_dialogue = self._mean_volume(
                ffmpeg,
                unducked_output,
                1.35,
                audio_filter=music_band_filter,
            )
            ducked_attenuation = (
                ducked_music_without_dialogue - ducked_music_with_dialogue
            )
            unducked_window_delta = (
                unducked_music_without_dialogue - unducked_music_with_dialogue
            )
            self.assertGreater(ducked_attenuation, 4.0)
            self.assertLess(abs(unducked_window_delta), 2.0)
            self.assertGreater(ducked_attenuation - unducked_window_delta, 4.0)

            dialogue_without_dialogue = self._mean_volume(
                ffmpeg,
                output_video,
                0.45,
                audio_filter=dialogue_band_filter,
            )
            dialogue_with_dialogue = self._mean_volume(
                ffmpeg,
                output_video,
                1.35,
                audio_filter=dialogue_band_filter,
            )
            self.assertGreater(dialogue_with_dialogue - dialogue_without_dialogue, 12.0)


if __name__ == "__main__":
    unittest.main()
