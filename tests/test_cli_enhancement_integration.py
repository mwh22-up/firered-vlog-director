from __future__ import annotations

import io
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from imageio_ffmpeg import get_ffmpeg_exe
from jsonschema import Draft202012Validator

from vlog_director.cli import main
from vlog_director.ffmpeg import run_command


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENHANCEMENT_SCHEMA = REPOSITORY_ROOT / "schemas" / "enhancement-plan.schema.json"


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_cli(*arguments: object) -> tuple[int, dict]:
    stdout = io.StringIO()
    argv = ["vlog-director", *(str(argument) for argument in arguments)]
    with patch.object(sys, "argv", argv), redirect_stdout(stdout):
        exit_code = main()
    return exit_code, json.loads(stdout.getvalue())


class EnhancementCliIntegrationTests(unittest.TestCase):
    def test_generated_plan_runs_through_cli_render_and_qa(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        self.assertTrue(Path(ffmpeg).is_file())

        with tempfile.TemporaryDirectory(prefix="firered-cli-render-") as temporary:
            projects_root = Path(temporary) / "projects"
            project_id = "synthetic-e2e"
            project = projects_root / project_id

            exit_code, initialized = _run_cli(
                "init-project",
                "--root",
                projects_root,
                "--project-id",
                project_id,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(initialized["status"], "ready")

            edit_plan = {
                "schema_version": "1.0",
                "project_id": project_id,
                "version": 1,
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "Synthetic fixture",
                        "segments": [
                            {
                                "source": "raw/synthetic.mkv",
                                "in_sec": 0.0,
                                "out_sec": 2.0,
                                "keep_original_audio": True,
                            }
                        ],
                    }
                ],
            }
            moments = {
                "schema_version": "1.0",
                "project_id": project_id,
                "moments": [
                    {
                        "id": "moment_locked_synthetic",
                        "source": "raw/synthetic.mkv",
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "types": ["key_event"],
                        "importance_score": 1.0,
                        "fun_score": 0.0,
                        "quality_score": 1.0,
                        "confidence": 1.0,
                        "keep_level": "locked",
                        "reason": "Synthetic locked interval for the CLI gate.",
                        "evidence": [{"type": "user", "value": "test fixture"}],
                    }
                ],
                "groups": [],
            }
            edit_plan_path = project / "work" / "plans" / "edit_plan.v1.json"
            moments_path = project / "work" / "analysis" / "moments.json"
            _write_json(edit_plan_path, edit_plan)
            _write_json(moments_path, moments)

            exit_code, render_guard = _run_cli(
                "guard-render",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(render_guard["status"], "passed")

            exit_code, enhancement_init = _run_cli(
                "init-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(enhancement_init["status"], "ready")

            enhancement_path = (
                project / "work" / "enhancement" / "enhancement_plan.v1.json"
            )
            enhancement = json.loads(enhancement_path.read_text(encoding="utf-8"))
            schema = json.loads(ENHANCEMENT_SCHEMA.read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema).iter_errors(enhancement))
            self.assertEqual(errors, [])

            invalid_render_plan = dict(enhancement)
            del invalid_render_plan["edit_plan_version"]
            invalid_render_path = project / "work" / "enhancement" / "invalid.json"
            _write_json(invalid_render_path, invalid_render_plan)
            exit_code, invalid_render = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                project / "output" / "missing.mkv",
                "--plan",
                invalid_render_path,
                "--output",
                project / "output" / "never.mp4",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(invalid_render["status"], "blocked")
            self.assertIn(
                "enhancement_schema_invalid",
                {issue["code"] for issue in invalid_render["issues"]},
            )

            invalid_enhancement = dict(enhancement)
            del invalid_enhancement["schema_version"]
            _write_json(enhancement_path, invalid_enhancement)
            exit_code, invalid_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(invalid_guard["status"], "blocked")
            self.assertIn(
                "enhancement_schema_invalid",
                {issue["code"] for issue in invalid_guard["issues"]},
            )
            _write_json(enhancement_path, enhancement)

            missing_music_asset = json.loads(json.dumps(enhancement))
            missing_music_asset["music"] = {
                "status": "ready",
                "rights_manifest": "assets/music/missing-rights.json",
                "audition_report": "assets/music/missing-audition.json",
                "tracks": [
                    {
                        "id": "missing-track",
                        "source": "assets/music/missing.wav",
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "gain_db": -20.0,
                    }
                ],
                "ducking": {
                    "enabled": True,
                    "threshold": 0.125,
                    "ratio": 8.0,
                    "attack_ms": 20,
                    "release_ms": 250,
                },
            }
            _write_json(enhancement_path, missing_music_asset)
            exit_code, missing_asset_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(missing_asset_guard["status"], "blocked")
            self.assertGreater(missing_asset_guard["blocking_count"], 0)
            self.assertIn(
                "enhancement_asset_missing",
                {issue["code"] for issue in missing_asset_guard["issues"]},
            )
            exit_code, missing_asset_render = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                project / "output" / "not-needed-before-asset-gate.mkv",
                "--plan",
                enhancement_path,
                "--output",
                project / "output" / "not-rendered.mp4",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(missing_asset_render["status"], "blocked")
            self.assertIn(
                "enhancement_asset_missing",
                {issue["code"] for issue in missing_asset_render["issues"]},
            )
            _write_json(enhancement_path, enhancement)

            exit_code, enhancement_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(enhancement_guard["status"], "preview_ready")

            base_video = project / "output" / "preview.mkv"
            final_video = project / "output" / "final.mp4"
            qa_output = project / "work" / "qa" / "music-mix.json"
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
                    "testsrc2=size=160x90:rate=10:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=2",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base_video),
                ]
            )

            audition_music = project / "assets" / "music" / "audition.wav"
            audition_music.parent.mkdir(parents=True, exist_ok=True)
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
                    "sine=frequency=220:sample_rate=48000:duration=2",
                    "-c:a",
                    "pcm_s16le",
                    str(audition_music),
                ]
            )
            _write_json(
                project / "assets" / "music" / "rights.json",
                {
                    "rights_approval": {
                        "status": "pending_user_confirmation",
                        "rights_holder": None,
                        "approved_by": None,
                        "approved_at": None,
                        "required_scope": [
                            "synchronize",
                            "modify",
                            "render",
                            "distribute_with_project",
                        ],
                    },
                    "assets": [
                        {
                            "id": "audition-bed",
                            "path": "audition.wav",
                            "size_bytes": audition_music.stat().st_size,
                            "sha256": hashlib.sha256(
                                audition_music.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                },
            )
            _write_json(
                project / "work" / "qa" / "audition.json",
                {
                    "status": "pending",
                    "blocking_items": ["Listen in context"],
                    "assets": [
                        {"id": "audition-bed", "audition_status": "pending"}
                    ],
                },
            )
            audition_plan = json.loads(json.dumps(enhancement))
            audition_plan["music"].update(
                {
                    "status": "audition",
                    "rights_manifest": "assets/music/rights.json",
                    "audition_report": "work/qa/audition.json",
                    "tracks": [
                        {
                            "id": "audition-bed",
                            "source": "assets/music/audition.wav",
                            "start_sec": 0.0,
                            "end_sec": 2.0,
                            "gain_db": -24.0,
                            "fade_in_sec": 0.1,
                            "fade_out_sec": 0.1,
                        }
                    ],
                }
            )
            audition_plan["subtitles"]["status"] = "disabled"
            audition_plan["illustration_motion"]["status"] = "disabled"
            _write_json(enhancement_path, audition_plan)

            exit_code, audition_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(audition_guard["status"], "preview_ready")

            exit_code, audition_release_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
                "--mode",
                "release",
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(audition_release_guard["status"], "blocked")
            self.assertIn(
                "release_section_not_ready",
                {issue["code"] for issue in audition_release_guard["issues"]},
            )

            exit_code, audition_render = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                base_video,
                "--plan",
                enhancement_path,
                "--output",
                project / "output" / "audition-preview.mp4",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(audition_render["status"], "preview_ready")
            self.assertEqual(audition_render["qa_status"], "passed")
            _write_json(enhancement_path, enhancement)

            subtitle_source_path = (
                project / "work" / "subtitles" / "review-required.json"
            )
            review_cue = {
                "start_sec": 0.25,
                "end_sec": 1.5,
                "text": "Review subtitle",
                "review_status": "review_required",
            }
            _write_json(
                subtitle_source_path,
                {
                    "status": "review_required",
                    "coverage": {"status": "pending"},
                    "cues": [
                        {
                            **review_cue,
                            "cue_id": "subtitle-review-1",
                        }
                    ],
                },
            )
            review_plan = json.loads(json.dumps(enhancement))
            review_plan["music"]["status"] = "disabled"
            review_plan["illustration_motion"]["status"] = "disabled"
            review_plan["subtitles"].update(
                {
                    "status": "review",
                    "source": "work/subtitles/review-required.json",
                    "source_sha256": hashlib.sha256(
                        subtitle_source_path.read_bytes()
                    ).hexdigest(),
                    "coverage": {"status": "pending"},
                    "cues": [review_cue],
                }
            )
            _write_json(enhancement_path, review_plan)

            exit_code, review_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(review_guard["status"], "preview_ready")

            exit_code, review_release_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
                "--mode",
                "release",
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(review_release_guard["status"], "blocked")
            self.assertIn(
                "release_section_not_ready",
                {issue["code"] for issue in review_release_guard["issues"]},
            )

            exit_code, review_render = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                base_video,
                "--plan",
                enhancement_path,
                "--output",
                project / "output" / "subtitle-review-preview.mp4",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(review_render["status"], "preview_ready")
            self.assertEqual(review_render["qa_status"], "passed")
            _write_json(enhancement_path, enhancement)

            exit_code, rendered = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                base_video,
                "--plan",
                enhancement_path,
                "--output",
                final_video,
                "--qa-output",
                qa_output,
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(rendered["status"], "preview_ready")
            self.assertEqual(rendered["mode"], "preview")
            self.assertEqual(rendered["qa_status"], "passed")
            verification = rendered["render_verification"]
            self.assertEqual(verification["probe"]["video_stream_count"], 1)
            self.assertEqual(verification["probe"]["audio_stream_count"], 1)
            self.assertEqual(verification["full_decode"]["status"], "passed")
            self.assertTrue(final_video.is_file())
            self.assertGreater(final_video.stat().st_size, 0)
            self.assertEqual(
                json.loads(qa_output.read_text(encoding="utf-8"))["status"],
                "passed",
            )
            self.assertEqual(
                json.loads(qa_output.read_text(encoding="utf-8"))["mode"],
                "preview",
            )

            exit_code, blocked_release = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                base_video,
                "--plan",
                enhancement_path,
                "--output",
                project / "output" / "release-blocked.mp4",
                "--mode",
                "release",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(blocked_release["status"], "blocked")
            self.assertEqual(blocked_release["mode"], "release")
            self.assertEqual(
                {issue["code"] for issue in blocked_release["issues"]},
                {"release_section_planned"},
            )

            for section_name in ("music", "subtitles", "illustration_motion"):
                enhancement[section_name]["status"] = "disabled"
            _write_json(enhancement_path, enhancement)
            exit_code, release_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
                "--mode",
                "release",
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(release_guard["status"], "ready")
            self.assertEqual(release_guard["mode"], "release")

            exit_code, released = _run_cli(
                "render-enhancement",
                "--project",
                project,
                "--base-video",
                base_video,
                "--plan",
                enhancement_path,
                "--output",
                project / "output" / "release.mp4",
                "--mode",
                "release",
                "--ffmpeg-executable",
                ffmpeg,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(released["status"], "ready")
            self.assertEqual(released["mode"], "release")

            run_command(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(final_video),
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
