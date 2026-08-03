import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.renderers import (
    _anchor_expression,
    _ensure_runtime_treatments_supported,
    _gain_to_linear,
    _music_filter_chain,
    _treatment_filter_graph,
    render_enhanced_video,
)


def _treatment(segment_id: str = "segment-1") -> dict:
    return {
        "segment_id": segment_id,
        "stabilization": {"mode": "off", "strength": 0.0, "max_crop_percent": 0.0},
        "continuity": {
            "transition": "hard_cut",
            "duration_sec": 0.0,
            "match_action": False,
        },
        "audio": {
            "preserve_original": True,
            "normalize_dialogue": False,
            "gain_db": 0.0,
            "mute": False,
        },
        "visual": {"speed": 1.0},
    }


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _ready_music_metadata(project: Path, tracks: list[dict]) -> dict:
    manifest_path = project / "assets" / "music" / "rights.json"
    assets = []
    audition_assets = []
    for track in tracks:
        source = project / track["source"]
        assets.append(
            {
                "id": track["id"],
                "path": source.relative_to(manifest_path.parent).as_posix(),
                "size_bytes": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
        audition_assets.append(
            {"id": track["id"], "audition_status": "passed"}
        )
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
        {
            "status": "passed",
            "blocking_items": [],
            "assets": audition_assets,
        },
    )
    return {
        "rights_manifest": "assets/music/rights.json",
        "audition_report": "work/qa/audition.json",
    }


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


def _review_subtitle_source(project: Path, cues: list[dict]) -> dict:
    source_path = project / "work" / "subtitles" / "review-required.json"
    _write_json(
        source_path,
        {
            "status": "review_required",
            "coverage": {"status": "pending"},
            "cues": cues,
        },
    )
    return {
        "source": "work/subtitles/review-required.json",
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }


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
                    "status": "ready",
                    "tracks": [
                        {
                            "id": "bed",
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
            plan["music"].update(
                _ready_music_metadata(project, plan["music"]["tracks"])
            )
            captured: dict[str, str] = {}

            def capture_filter(command: list[str]) -> None:
                script_index = command.index("-filter_complex_script") + 1
                captured["filter"] = Path(command[script_index]).read_text(encoding="utf-8")

            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters") as require_filters,
                patch("vlog_director.renderers.run_command", side_effect=capture_filter),
            ):
                render_enhanced_video(project, base_video, plan, output)

            required = require_filters.call_args.args[1]
            self.assertNotIn("sidechaincompress", required)
            filter_text = captured["filter"]
            self.assertNotIn("sidechaincompress", filter_text)
            self.assertIn("[dialogue_normalized][music_bed]", filter_text)

    def test_treatment_graph_consumes_visual_and_audio_fields(self) -> None:
        treatment = _treatment()
        treatment["audio"]["gain_db"] = -6.0
        treatment["visual"] = {
            "exposure_ev": 0.25,
            "brightness": 0.04,
            "contrast": 1.08,
            "saturation": 0.92,
            "gamma": 1.03,
            "white_balance": {
                "red_shift": 0.02,
                "green_shift": 0.0,
                "blue_shift": -0.02,
            },
            "denoise": {
                "mode": "hqdn3d",
                "luma_spatial": 1.2,
                "chroma_spatial": 0.8,
                "luma_temporal": 2.4,
                "chroma_temporal": 1.6,
            },
            "sharpen": {"mode": "unsharp", "amount": 0.35},
            "reframe": {
                "mode": "crop",
                "width_percent": 92.0,
                "height_percent": 92.0,
                "x_percent": 45.0,
                "y_percent": 55.0,
            },
            "speed": 1.0,
        }
        graph, video, audio, normalize, required = _treatment_filter_graph(
            [treatment],
            {
                "duration_sec": 1.25,
                "segments": [
                    {"segment_id": "segment-1", "start_sec": 0.0, "end_sec": 1.25}
                ],
            },
            1920,
            1080,
            0.066,
            0.045,
        )
        text = ";".join(graph)

        self.assertEqual((video, audio, normalize), ("video_treated", "audio_treated", False))
        for expected in (
            "exposure=",
            "eq=",
            "colorbalance=",
            "hqdn3d=",
            "unsharp=",
            "crop=",
            "scale=1920:1080",
            "volume=-6.0000dB",
            "concat=n=1:v=1:a=1",
            "trim=start=0.066000:end=1.316000",
            "atrim=start=0.045000:end=1.295000",
            "[video_concat]setpts=PTS+0.021000/TB",
            "[audio_concat]asetpts=PTS+0.000000/TB",
        ):
            self.assertIn(expected, text)
        self.assertTrue(
            {"exposure", "eq", "colorbalance", "hqdn3d", "unsharp", "crop", "scale"}
            <= required
        )

    def test_treatment_graph_restores_stream_offset_only_after_concat(self) -> None:
        graph, *_ = _treatment_filter_graph(
            [_treatment("segment-1"), _treatment("segment-2")],
            {
                "duration_sec": 1.0,
                "segments": [
                    {"segment_id": "segment-1", "start_sec": 0.0, "end_sec": 0.4},
                    {"segment_id": "segment-2", "start_sec": 0.4, "end_sec": 1.0},
                ],
            },
            160,
            90,
            0.066,
            0.045,
        )
        text = ";".join(graph)

        self.assertIn("trim=start=0.066000:end=0.466000", text)
        self.assertIn("trim=start=0.466000:end=1.066000", text)
        self.assertIn("atrim=start=0.045000:end=0.445000", text)
        self.assertIn("atrim=start=0.445000:end=1.045000", text)
        self.assertNotIn("PTS-STARTPTS+0.021000/TB", text)
        self.assertEqual(text.count("[video_concat]setpts=PTS+0.021000/TB"), 1)

    def test_unconsumed_or_unsupported_runtime_treatments_raise(self) -> None:
        cases = []
        auto = _treatment()
        auto["stabilization"]["mode"] = "auto"
        cases.append(auto)
        speed = _treatment()
        speed["visual"]["speed"] = 1.1
        cases.append(speed)
        unknown = _treatment()
        unknown["visual"]["future_filter"] = True
        cases.append(unknown)

        for treatment in cases:
            with self.subTest(treatment=treatment):
                with self.assertRaises(ValueError):
                    _ensure_runtime_treatments_supported([treatment])

    def test_treatment_graph_rejects_wrong_realized_segment_order(self) -> None:
        with self.assertRaisesRegex(ValueError, "IDs and order"):
            _treatment_filter_graph(
                [_treatment("segment-1"), _treatment("segment-2")],
                {
                    "duration_sec": 2.0,
                    "segments": [
                        {"segment_id": "segment-2", "start_sec": 0.0, "end_sec": 1.0},
                        {"segment_id": "segment-1", "start_sec": 1.0, "end_sec": 2.0},
                    ],
                },
                160,
                90,
            )

    def test_renderer_rejects_wrong_base_hash_before_ffmpeg_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            base_video.write_bytes(b"not-the-approved-base")
            plan = {
                "video_treatments": [_treatment()],
                "music": {"tracks": []},
                "subtitles": {"cues": []},
                "illustration_motion": {"items": []},
            }
            realized = {
                "duration_sec": 1.0,
                "base_size_bytes": base_video.stat().st_size,
                "base_sha256": "0" * 64,
                "segments": [
                    {"segment_id": "segment-1", "start_sec": 0.0, "end_sec": 1.0}
                ],
            }
            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.probe_media") as probe,
                self.assertRaisesRegex(ValueError, "SHA-256"),
            ):
                render_enhanced_video(
                    project,
                    base_video,
                    plan,
                    project / "output.mp4",
                    realized_timeline=realized,
                )
            probe.assert_not_called()

    def test_renderer_consumes_overlay_animation_and_confines_asset_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            overlay = project / "assets" / "illustrations" / "title.png"
            base_video.write_bytes(b"base")
            overlay.parent.mkdir(parents=True)
            overlay.write_bytes(b"png")
            plan = {
                "music": {"status": "planned", "tracks": []},
                "subtitles": {"status": "planned", "cues": []},
                "illustration_motion": {
                    "status": "ready",
                    "items": [
                        {
                            "id": "title-1",
                            "type": "title_card",
                            "source": "assets/illustrations/title.png",
                            "start_sec": 1.0,
                            "end_sec": 5.0,
                            "anchor": "top_left",
                            "animation": "slide",
                            "animation_duration_sec": 0.4,
                            "scale_percent": 40.0,
                            "margin_percent": 6.0,
                        }
                    ],
                },
            }
            captured: dict[str, str] = {}

            def capture_filter(command: list[str]) -> None:
                script_index = command.index("-filter_complex_script") + 1
                captured["filter"] = Path(command[script_index]).read_text(
                    encoding="utf-8"
                )
                captured["command"] = " ".join(command)

            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters"),
                patch(
                    "vlog_director.renderers.probe_media",
                    return_value={"width": 1920, "height": 1080},
                ),
                patch("vlog_director.renderers.run_command", side_effect=capture_filter),
            ):
                render_enhanced_video(project, base_video, plan, project / "output.mp4")

            self.assertIn("scale=w=768:h=-1:flags=lanczos", captured["filter"])
            self.assertIn("if(lt(t,1.400)", captured["filter"])
            self.assertIn("if(lt(t,4.600)", captured["filter"])
            self.assertIn("-framerate 30", captured["command"])

            plan["illustration_motion"]["items"][0]["source"] = "../secret.png"
            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters"),
                self.assertRaisesRegex(ValueError, "asset validation failed"),
            ):
                render_enhanced_video(project, base_video, plan, project / "bad.mp4")

    def test_renderer_passes_subtitle_layout_and_uses_temporary_ass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            output = project / "output.mp4"
            base_video.write_bytes(b"base")
            plan = {
                "music": {"status": "planned", "tracks": []},
                "illustration_motion": {"status": "planned", "items": []},
                "subtitles": {
                    "status": "review",
                    "coverage": {"status": "verified"},
                    "cues": [
                        {
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "verified",
                            "review_status": "verified",
                            "position": "top_center",
                        }
                    ],
                    "style": {
                        "position": "bottom_center",
                        "max_lines": 2,
                        "safe_margin_percent": 9.0,
                        "font_name": "Arial",
                        "font_size": 64,
                        "margin_v": 72,
                        "outline": 4,
                        "shadow": 2,
                        "bold": True,
                        "max_chars_per_line": 16,
                        "background_opacity_percent": 48.0,
                        "background_padding": 8,
                    },
                },
            }
            plan["subtitles"].update(
                _review_subtitle_source(project, plan["subtitles"]["cues"])
            )
            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters"),
                patch(
                    "vlog_director.renderers.probe_media",
                    return_value={"width": 960, "height": 540},
                ),
                patch("vlog_director.renderers.write_ass_subtitles") as writer,
                patch("vlog_director.renderers.run_command"),
            ):
                render_enhanced_video(project, base_video, plan, output)

            kwargs = writer.call_args.kwargs
            self.assertEqual(kwargs["position"], "bottom_center")
            self.assertEqual(kwargs["max_lines"], 2)
            self.assertEqual(kwargs["safe_margin_percent"], 9.0)
            self.assertEqual(kwargs["font_size"], 32)
            self.assertEqual(kwargs["outline"], 2)
            self.assertEqual(kwargs["background_padding"], 4)
            self.assertFalse(output.with_suffix(".ass").exists())

    def test_renderer_rejects_unverified_subtitle_cue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            base_video.write_bytes(b"base")
            plan = {
                "music": {"tracks": []},
                "illustration_motion": {"items": []},
                "subtitles": {
                    "status": "ready",
                    "coverage": {"status": "verified"},
                    "cues": [
                        {
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "draft",
                            "review_status": "review_required",
                        }
                    ],
                },
            }
            plan["subtitles"].update(
                _ready_subtitle_source(project, plan["subtitles"]["cues"])
            )
            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                self.assertRaisesRegex(ValueError, "review_status"),
            ):
                render_enhanced_video(project, base_video, plan, project / "output.mp4")

    def test_renderer_burns_review_required_subtitle_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            base_video.write_bytes(b"base")
            cue = {
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "review subtitle",
                "review_status": "review_required",
            }
            plan = {
                "music": {"status": "planned", "tracks": []},
                "illustration_motion": {"status": "planned", "items": []},
                "subtitles": {
                    "status": "review",
                    "coverage": {"status": "pending"},
                    "cues": [cue],
                    "style": {
                        "position": "bottom_center",
                        "max_lines": 2,
                        "safe_margin_percent": 8.0,
                    },
                },
            }
            plan["subtitles"].update(_review_subtitle_source(project, [cue]))

            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                patch("vlog_director.renderers.require_filters"),
                patch(
                    "vlog_director.renderers.probe_media",
                    return_value={"width": 1920, "height": 1080},
                ),
                patch("vlog_director.renderers.write_ass_subtitles") as writer,
                patch("vlog_director.renderers.run_command"),
            ):
                render_enhanced_video(
                    project,
                    base_video,
                    plan,
                    project / "preview.mp4",
                )

            self.assertEqual(writer.call_args.args[0], [cue])

    def test_renderer_enforces_overlay_subtitle_safe_zone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            overlay = project / "assets" / "illustrations" / "lower-third.png"
            base_video.write_bytes(b"base")
            overlay.parent.mkdir(parents=True)
            overlay.write_bytes(b"png")
            plan = {
                "music": {"tracks": []},
                "illustration_motion": {
                    "status": "ready",
                    "subtitle_safe_zone": True,
                    "items": [
                        {
                            "id": "lower-third",
                            "type": "callout",
                            "source": "assets/illustrations/lower-third.png",
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "anchor": "bottom_left",
                            "animation": "none",
                        }
                    ],
                },
                "subtitles": {
                    "status": "review",
                    "coverage": {"status": "verified"},
                    "cues": [
                        {
                            "start_sec": 0.0,
                            "end_sec": 1.0,
                            "text": "verified",
                            "review_status": "verified",
                        }
                    ],
                    "style": {"position": "bottom_center"},
                },
            }
            plan["subtitles"].update(
                _review_subtitle_source(project, plan["subtitles"]["cues"])
            )
            with (
                patch("vlog_director.renderers.find_ffmpeg", return_value="ffmpeg"),
                self.assertRaisesRegex(ValueError, "subtitle safe zone"),
            ):
                render_enhanced_video(project, base_video, plan, project / "output.mp4")

    def test_renderer_rejects_non_finite_numbers_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            base_video = project / "base.mkv"
            base_video.write_bytes(b"base")
            treatment = _treatment()
            treatment["visual"]["gamma"] = float("nan")
            plan = {
                "video_treatments": [treatment],
                "music": {"tracks": []},
                "illustration_motion": {"items": []},
                "subtitles": {"cues": []},
            }

            with self.assertRaisesRegex(ValueError, "non-finite"):
                render_enhanced_video(
                    project,
                    base_video,
                    plan,
                    project / "output.mp4",
                )


if __name__ == "__main__":
    unittest.main()
