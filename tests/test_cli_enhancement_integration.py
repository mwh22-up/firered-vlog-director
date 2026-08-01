from __future__ import annotations

import io
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

            exit_code, enhancement_guard = _run_cli(
                "guard-enhancement",
                "--project",
                project,
                "--version",
                1,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(enhancement_guard["status"], "passed")

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
            self.assertEqual(rendered["status"], "ready")
            self.assertEqual(rendered["qa_status"], "passed")
            self.assertTrue(final_video.is_file())
            self.assertGreater(final_video.stat().st_size, 0)
            self.assertEqual(
                json.loads(qa_output.read_text(encoding="utf-8"))["status"],
                "passed",
            )

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
