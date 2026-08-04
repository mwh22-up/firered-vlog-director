from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from vlog_director.cli import _build_parser, main
from vlog_director.enhancement_assets import (
    subtitle_ready_evidence_contract_issues,
    validate_enhancement_assets,
)
from tests.test_subtitle_approval import _ApprovalFixture


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
READABILITY_SCHEMA = (
    REPOSITORY_ROOT / "schemas" / "subtitle-readability-qa.schema.json"
)


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_main(*arguments: object) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = ["vlog-director", *(str(argument) for argument in arguments)]
    with (
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = main()
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _bound_job_arguments(
    project: Path,
    job_kind: str,
    arguments: list[object],
    *,
    job_id: str = "a" * 32,
) -> tuple[Path, list[str]]:
    status_path = project / "work" / "jobs" / job_kind / job_id / "status.json"
    worker_arguments = [
        *(str(argument) for argument in arguments),
        "--job-status",
        str(status_path),
    ]
    _write_json(
        status_path.parent / "job.json",
        {
            "schema_version": "1.0",
            "job_kind": job_kind,
            "arguments": worker_arguments,
        },
    )
    _write_json(status_path, {"schema_version": "1.0", "status": "queued"})
    return status_path, worker_arguments


def _minimal_arguments(command: str) -> list[str]:
    common = {
        "project-subtitles": [
            "--project",
            "project",
            "--edit-plan",
            "edit.json",
            "--realized-timeline",
            "realized.json",
            "--analysis",
            "analysis-a.json",
            "--subtitle-version",
            "1",
            "--draft-output",
            "draft.json",
            "--review-output",
            "review.json",
        ],
        "audit-subtitles": [
            "--project",
            "project",
            "--subtitle-source",
            "subtitles.json",
            "--realized-timeline",
            "realized.json",
            "--output",
            "readability.json",
            "--mode",
            "preview",
        ],
        "probe-subtitle-layout": [
            "--project",
            "project",
            "--base-video",
            "base.mp4",
            "--subtitle-source",
            "subtitles.json",
            "--plan",
            "plan.json",
            "--realized-timeline",
            "realized.json",
            "--readability-qa",
            "readability.json",
            "--output",
            "layout.json",
            "--mode",
            "preview",
        ],
        "render-subtitle-preview": [
            "--project",
            "project",
            "--base-video",
            "explicit-user-preview.mp4",
            "--subtitle-source",
            "subtitles.json",
            "--realized-timeline",
            "realized.json",
            "--readability-qa",
            "readability.json",
            "--scope",
            "all",
            "--proxy-unit",
            "timeline",
        ],
        "qa-subtitles": [
            "--project",
            "project",
            "--preview-manifest",
            "preview-manifest.json",
            "--readability-qa",
            "readability.json",
            "--layout-qa",
            "layout.json",
            "--output",
            "visual-qa.json",
            "--evidence-directory",
            "evidence",
        ],
        "approve-subtitles": [
            "--project",
            "project",
            "--subtitle-source",
            "subtitles.json",
            "--plan",
            "plan.json",
            "--readability-qa",
            "readability.json",
            "--layout-qa",
            "layout.json",
            "--visual-qa",
            "visual-qa.json",
            "--human-review",
            "human-review.json",
            "--approved-by",
            "Subtitle Reviewer",
            "--approval-output",
            "approval.json",
            "--ready-source-output",
            "ready.json",
        ],
    }
    return [command, *common[command]]


def _projection_cli_fixture(root: Path) -> tuple[Path, list[object], dict[str, Path]]:
    project = root / "project"
    paths = {
        "edit_plan": project / "work" / "plans" / "edit.json",
        "timeline": project / "work" / "qa" / "realized.json",
        "analysis": project / "work" / "analysis" / "analysis-a.json",
        "draft": project / "work" / "subtitles" / "draft.json",
        "review": project / "work" / "subtitles" / "review.json",
        "srt": project / "work" / "subtitles" / "draft.srt",
    }
    for key in ("edit_plan", "timeline", "analysis"):
        _write_json(paths[key], {})
    arguments: list[object] = [
        "project-subtitles",
        "--project",
        project,
        "--edit-plan",
        paths["edit_plan"],
        "--realized-timeline",
        paths["timeline"],
        "--analysis",
        paths["analysis"],
        "--subtitle-version",
        "1",
        "--draft-output",
        paths["draft"],
        "--review-output",
        paths["review"],
        "--srt-output",
        paths["srt"],
    ]
    return project, arguments, paths


def _audit_cli_fixture(root: Path) -> tuple[Path, list[object], dict[str, Path]]:
    project = root / "project"
    paths = {
        "source": project / "work" / "subtitles" / "review.json",
        "timeline": project / "work" / "qa" / "realized.json",
        "policy": project / "work" / "qa" / "policy.json",
        "output": project / "work" / "qa" / "readability.json",
    }
    for key in ("source", "timeline", "policy"):
        _write_json(paths[key], {})
    arguments: list[object] = [
        "audit-subtitles",
        "--project",
        project,
        "--subtitle-source",
        paths["source"],
        "--realized-timeline",
        paths["timeline"],
        "--policy",
        paths["policy"],
        "--output",
        paths["output"],
        "--mode",
        "preview",
    ]
    return project, arguments, paths


class SubtitleCliContractTests(unittest.TestCase):
    COMMAND_OPTIONS = {
        "project-subtitles": {
            "--project",
            "--edit-plan",
            "--realized-timeline",
            "--analysis",
            "--subtitle-version",
            "--draft-output",
            "--review-output",
            "--srt-output",
        },
        "audit-subtitles": {
            "--project",
            "--subtitle-source",
            "--realized-timeline",
            "--output",
            "--policy",
            "--mode",
        },
        "probe-subtitle-layout": {
            "--project",
            "--base-video",
            "--subtitle-source",
            "--plan",
            "--realized-timeline",
            "--readability-qa",
            "--output",
            "--cache-directory",
            "--fonts-directory",
            "--ffmpeg-executable",
            "--mode",
        },
        "render-subtitle-preview": {
            "--project",
            "--base-video",
            "--subtitle-source",
            "--realized-timeline",
            "--plan",
            "--readability-qa",
            "--layout-qa",
            "--scope",
            "--proxy-unit",
            "--padding-sec",
            "--output-directory",
            "--manifest-output",
            "--ffmpeg-executable",
            "--foreground",
        },
        "qa-subtitles": {
            "--project",
            "--preview-manifest",
            "--readability-qa",
            "--layout-qa",
            "--output",
            "--evidence-directory",
            "--ffmpeg-executable",
            "--foreground",
        },
        "approve-subtitles": {
            "--project",
            "--subtitle-source",
            "--plan",
            "--readability-qa",
            "--layout-qa",
            "--visual-qa",
            "--human-review",
            "--approved-by",
            "--approval-output",
            "--ready-source-output",
            "--evidence-output",
        },
    }

    def test_every_subtitle_command_has_complete_help(self) -> None:
        for command, expected_options in self.COMMAND_OPTIONS.items():
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch.object(sys, "argv", ["vlog-director", command, "--help"]),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                    self.assertRaises(SystemExit) as raised,
                ):
                    main()
                self.assertEqual(raised.exception.code, 0)
                help_text = stdout.getvalue()
                self.assertIn(f"usage: vlog-director {command}", help_text)
                for option in expected_options:
                    self.assertIn(option, help_text)

    def test_unknown_options_and_missing_required_arguments_fail(self) -> None:
        for command in self.COMMAND_OPTIONS:
            with self.subTest(command=command, failure="missing-required"):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    _build_parser().parse_args([command])
                self.assertEqual(raised.exception.code, 2)
            with self.subTest(command=command, failure="unknown-option"):
                arguments = [*_minimal_arguments(command), "--unknown-field", "value"]
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    _build_parser().parse_args(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_argument_choices_and_repeatable_analysis_are_enforced(self) -> None:
        parser = _build_parser()
        projected = parser.parse_args(
            [
                *_minimal_arguments("project-subtitles"),
                "--analysis",
                "analysis-b.json",
                "--srt-output",
                "subtitles.srt",
            ]
        )
        self.assertEqual(
            projected.analysis,
            [Path("analysis-a.json"), Path("analysis-b.json")],
        )
        self.assertEqual(projected.srt_output, Path("subtitles.srt"))

        for command, option, bad_value in (
            ("audit-subtitles", "--mode", "unsafe"),
            ("probe-subtitle-layout", "--mode", "unsafe"),
            ("render-subtitle-preview", "--scope", "partial"),
            ("render-subtitle-preview", "--proxy-unit", "file"),
        ):
            arguments = _minimal_arguments(command)
            option_index = arguments.index(option)
            arguments[option_index + 1] = bad_value
            with self.subTest(command=command, option=option):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    parser.parse_args(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_project_subtitles_rejects_escaped_and_wrong_artifact_paths(self) -> None:
        cases = (
            ("edit-plan-outside", "--edit-plan", False, "edit-outside.json", True),
            ("timeline-wrong-root", "--realized-timeline", True, "work/plans/timeline-wrong.json", True),
            ("analysis-outside", "--analysis", False, "analysis-outside.json", True),
            ("draft-outside", "--draft-output", False, "draft-outside.json", False),
            ("review-wrong-root", "--review-output", True, "work/qa/review-wrong.json", False),
            ("srt-wrong-root", "--srt-output", True, "work/qa/draft-wrong.srt", False),
        )
        for name, option, inside_project, relative, is_input in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory(
                prefix="firered-project-subtitle-path-"
            ) as temporary:
                root = Path(temporary)
                project, arguments, paths = _projection_cli_fixture(root)
                invalid = (project if inside_project else root) / relative
                if is_input:
                    _write_json(invalid, {})
                arguments[arguments.index(option) + 1] = invalid

                exit_code, stdout, _ = _run_main(*arguments)

                self.assertEqual(exit_code, 2)
                result = json.loads(stdout)
                self.assertEqual(result["status"], "blocked")
                self.assertIn("must stay under", result["issues"][0]["message"])
                for key in ("draft", "review", "srt"):
                    self.assertFalse(paths[key].exists())
                if not is_input:
                    self.assertFalse(invalid.exists())

    def test_audit_subtitles_rejects_escaped_and_wrong_artifact_paths(self) -> None:
        cases = (
            ("source-outside", "--subtitle-source", False, "source-outside.json", True),
            ("source-wrong-root", "--subtitle-source", True, "work/qa/source-wrong.json", True),
            ("timeline-outside", "--realized-timeline", False, "timeline-outside.json", True),
            ("timeline-wrong-root", "--realized-timeline", True, "work/subtitles/timeline-wrong.json", True),
            ("policy-outside", "--policy", False, "policy-outside.json", True),
            ("policy-wrong-root", "--policy", True, "work/subtitles/policy-wrong.json", True),
            ("output-outside", "--output", False, "readability-outside.json", False),
            ("output-wrong-root", "--output", True, "work/subtitles/readability-wrong.json", False),
        )
        for name, option, inside_project, relative, is_input in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory(
                prefix="firered-audit-subtitle-path-"
            ) as temporary:
                root = Path(temporary)
                project, arguments, paths = _audit_cli_fixture(root)
                invalid = (project if inside_project else root) / relative
                if is_input:
                    _write_json(invalid, {})
                arguments[arguments.index(option) + 1] = invalid

                exit_code, stdout, _ = _run_main(*arguments)

                self.assertEqual(exit_code, 2)
                result = json.loads(stdout)
                self.assertEqual(result["status"], "blocked")
                self.assertIn("must stay under", result["issues"][0]["message"])
                self.assertFalse(paths["output"].exists())
                if not is_input:
                    self.assertFalse(invalid.exists())

    def test_project_subtitle_outputs_are_distinct_and_never_overwritten(self) -> None:
        for scenario in ("duplicate", "existing"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(
                prefix="firered-project-subtitle-output-"
            ) as temporary:
                _, arguments, paths = _projection_cli_fixture(Path(temporary))
                if scenario == "duplicate":
                    arguments[arguments.index("--review-output") + 1] = paths["draft"]
                    expected_message = "must be distinct"
                    original = None
                else:
                    original = b"existing subtitle draft must survive\n"
                    paths["draft"].parent.mkdir(parents=True, exist_ok=True)
                    paths["draft"].write_bytes(original)
                    expected_message = "already exists"

                exit_code, stdout, _ = _run_main(*arguments)

                self.assertEqual(exit_code, 2)
                result = json.loads(stdout)
                self.assertIn(expected_message, result["issues"][0]["message"])
                if original is None:
                    self.assertFalse(paths["draft"].exists())
                else:
                    self.assertEqual(paths["draft"].read_bytes(), original)
                self.assertFalse(paths["review"].exists())
                self.assertFalse(paths["srt"].exists())

    def test_audit_output_cannot_overwrite_inputs_or_existing_artifacts(self) -> None:
        for scenario in ("timeline-input", "existing-output"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory(
                prefix="firered-audit-subtitle-output-"
            ) as temporary:
                _, arguments, paths = _audit_cli_fixture(Path(temporary))
                if scenario == "timeline-input":
                    protected = paths["timeline"]
                    original = protected.read_bytes()
                    arguments[arguments.index("--output") + 1] = protected
                    expected_message = "must not overwrite an input"
                else:
                    protected = paths["output"]
                    original = b"existing readability QA must survive\n"
                    protected.write_bytes(original)
                    expected_message = "already exists"

                exit_code, stdout, _ = _run_main(*arguments)

                self.assertEqual(exit_code, 2)
                result = json.loads(stdout)
                self.assertIn(expected_message, result["issues"][0]["message"])
                self.assertEqual(protected.read_bytes(), original)

    def test_risk_scope_without_readability_qa_blocks_before_media_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-risk-cli-") as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            base_video = project / "explicit-base.mp4"
            base_video.write_bytes(b"explicit synthetic placeholder")
            subtitle_source = project / "work" / "subtitles" / "review.json"
            realized = project / "work" / "qa" / "realized.json"
            _write_json(
                subtitle_source,
                {
                    "project_id": "risk-test",
                    "status": "review_required",
                    "coverage": {"status": "pending"},
                    "cues": [],
                },
            )
            _write_json(realized, {"duration_sec": 1.0, "segments": []})

            exit_code, stdout, _ = _run_main(
                "render-subtitle-preview",
                "--project",
                project,
                "--base-video",
                base_video,
                "--subtitle-source",
                subtitle_source,
                "--realized-timeline",
                realized,
                "--scope",
                "risk",
                "--proxy-unit",
                "cue",
                "--foreground",
            )

        self.assertEqual(exit_code, 2)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "blocked")
        codes = set(result.get("blocker_codes", [])) | {
            issue["code"] for issue in result.get("issues", [])
        }
        self.assertIn("subtitle_readability_qa_required_for_risk_scope", codes)

    def test_hidden_job_status_is_confined_and_records_preview_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-job-status-") as temporary:
            root = Path(temporary)
            project = root / "project"
            source = project / "work" / "subtitles" / "review.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base = root / "explicit-base.mp4"
            _write_json(
                source,
                {
                    "schema_version": "1.0",
                    "project_id": "job-status",
                    "status": "review_required",
                    "coverage": {"status": "pending"},
                    "cues": [],
                },
            )
            _write_json(
                timeline,
                {"duration_sec": 1.0, "segments": []},
            )
            base.write_bytes(b"explicit synthetic placeholder")
            escaped_status = root / "escaped-status.json"
            common = [
                "render-subtitle-preview",
                "--project",
                project,
                "--base-video",
                base,
                "--subtitle-source",
                source,
                "--realized-timeline",
                timeline,
                "--scope",
                "all",
                "--proxy-unit",
                "timeline",
                "--foreground",
            ]

            exit_code, stdout, _ = _run_main(
                *common,
                "--job-status",
                escaped_status,
            )
            self.assertEqual(exit_code, 2)
            self.assertFalse(escaped_status.exists())
            self.assertIn(
                "subtitle_job_status_path_invalid",
                json.loads(stdout)["blocker_codes"],
            )

            legacy_status = (
                project
                / "work"
                / "jobs"
                / "subtitle-preview"
                / "job-1"
                / "status.json"
            )
            _write_json(legacy_status, {"schema_version": "1.0", "status": "queued"})
            exit_code, stdout, _ = _run_main(
                *common,
                "--job-status",
                legacy_status,
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(
                json.loads(legacy_status.read_text(encoding="utf-8"))["status"],
                "queued",
            )
            self.assertIn(
                "subtitle_job_status_path_invalid",
                json.loads(stdout)["blocker_codes"],
            )

            mismatched_status, mismatched_arguments = _bound_job_arguments(
                project,
                "subtitle-preview",
                common,
                job_id="b" * 32,
            )
            mismatched_spec = json.loads(
                (mismatched_status.parent / "job.json").read_text(encoding="utf-8")
            )
            mismatched_spec["arguments"] = ["render-subtitle-preview", "--foreground"]
            _write_json(mismatched_status.parent / "job.json", mismatched_spec)
            exit_code, stdout, _ = _run_main(*mismatched_arguments)
            self.assertEqual(exit_code, 2)
            self.assertIn(
                "subtitle_job_status_path_invalid",
                json.loads(stdout)["blocker_codes"],
            )

            status_path, worker_arguments = _bound_job_arguments(
                project,
                "subtitle-preview",
                common,
            )
            with patch(
                "vlog_director.subtitle_preview.render_subtitle_preview",
                return_value={"status": "completed", "manifest_path": "work/proxy/manifest.json"},
            ):
                exit_code, _, _ = _run_main(*worker_arguments)
            self.assertEqual(exit_code, 0)
            completed = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["exit_code"], 0)

            _write_json(status_path, {"schema_version": "1.0", "status": "queued"})
            with patch(
                "vlog_director.subtitle_preview.render_subtitle_preview",
                side_effect=ValueError("synthetic renderer failure"),
            ):
                exit_code, _, _ = _run_main(*worker_arguments)
            self.assertEqual(exit_code, 2)
            failed = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["exit_code"], 2)

    def test_detached_launcher_never_overwrites_a_fast_worker_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-job-race-") as temporary:
            project = Path(temporary) / "project"

            class Process:
                pid = 2468

            def finish_immediately(command: list[str], **_: object) -> Process:
                status_argument = command.index("--job-status") + 1
                status_path = Path(command[status_argument])
                _write_json(
                    status_path,
                    {"schema_version": "1.0", "status": "completed", "exit_code": 0},
                )
                return Process()

            with patch(
                "vlog_director.cli.subprocess.Popen",
                side_effect=finish_immediately,
            ):
                exit_code, stdout, _ = _run_main(
                    "render-subtitle-preview",
                    "--project",
                    project,
                    "--base-video",
                    Path(temporary) / "base.mkv",
                    "--subtitle-source",
                    project / "work" / "subtitles" / "source.json",
                    "--realized-timeline",
                    project / "work" / "qa" / "timeline.json",
                    "--scope",
                    "all",
                    "--proxy-unit",
                    "timeline",
                )

            self.assertEqual(exit_code, 0)
            submission = json.loads(stdout)
            status = json.loads(
                Path(submission["job_status"]).read_text(encoding="utf-8")
            )
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["exit_code"], 0)
    def test_visual_qa_job_status_records_blocked_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-visual-job-status-") as temporary:
            project = Path(temporary) / "project"
            manifest = project / "work" / "proxy" / "manifest.json"
            readability = project / "work" / "qa" / "readability.json"
            layout = project / "work" / "qa" / "layout.json"
            output = project / "work" / "qa" / "visual.json"
            evidence = project / "work" / "qa" / "visual-evidence"
            _write_json(readability, {"schema_version": "1.0"})
            _write_json(layout, {"schema_version": "1.0"})
            _write_json(
                manifest,
                {
                    "bindings": {
                        "readability_qa": {
                            "sha256": hashlib.sha256(readability.read_bytes()).hexdigest()
                        },
                        "layout_qa": {
                            "sha256": hashlib.sha256(layout.read_bytes()).hexdigest()
                        },
                    }
                },
            )
            common = [
                "qa-subtitles",
                "--project",
                project,
                "--preview-manifest",
                manifest,
                "--readability-qa",
                readability,
                "--layout-qa",
                layout,
                "--output",
                output,
                "--evidence-directory",
                evidence,
                "--foreground",
            ]
            status_path, worker_arguments = _bound_job_arguments(
                project,
                "subtitle-visual-qa",
                common,
            )

            with patch(
                "vlog_director.subtitle_visual_qa.qa_subtitles",
                return_value={
                    "status": "blocked",
                    "report_path": "work/qa/visual.json",
                },
            ):
                exit_code, _, _ = _run_main(*worker_arguments)
            self.assertEqual(exit_code, 2)
            blocked = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(blocked["status"], "blocked")
            self.assertEqual(blocked["exit_code"], 2)

    def test_base_video_is_explicit_and_no_nordic_r3_fallback_is_embedded(self) -> None:
        parser = _build_parser()
        arguments = _minimal_arguments("render-subtitle-preview")
        parsed = parser.parse_args(arguments)
        self.assertEqual(parsed.base_video, Path("explicit-user-preview.mp4"))

        missing_base = list(arguments)
        index = missing_base.index("--base-video")
        del missing_base[index : index + 2]
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            parser.parse_args(missing_base)
        self.assertEqual(raised.exception.code, 2)

        cli_source = (
            REPOSITORY_ROOT / "src" / "vlog_director" / "cli.py"
        ).read_text(encoding="utf-8").casefold()
        for forbidden in (
            "preview.enhanced.v4.r3.mp4",
            "nordic-v4-render",
            "subtitle-review-nordic",
        ):
            self.assertNotIn(forbidden, cli_source)

    def test_audit_subtitles_writes_schema_valid_readability_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-audit-cli-") as temporary:
            root = Path(temporary)
            project = root / "project"
            subtitle_source = project / "work" / "subtitles" / "subtitles.json"
            realized = project / "work" / "qa" / "realized.json"
            output = project / "work" / "qa" / "readability-qa.json"
            _write_json(
                subtitle_source,
                {
                    "schema_version": "1.0",
                    "document_type": "subtitle_review_draft",
                    "project_id": "audit-cli-test",
                    "status": "review_required",
                    "coverage": {"status": "pending"},
                    "segment_coverage": [
                        {
                            "segment_id": "segment-1",
                            "actual_start_sec": 0.0,
                            "actual_end_sec": 2.0,
                        }
                    ],
                    "cues": [
                        {
                            "cue_id": "stable-cue-1",
                            "segment_id": "segment-1",
                            "chapter_id": "chapter-1",
                            "start_sec": 0.5,
                            "end_sec": 1.5,
                            "text": "你好，世界。",
                            "position": "bottom_center",
                            "review_status": "review_required",
                            "risk_flags": [],
                        }
                    ],
                },
            )
            _write_json(
                realized,
                {
                    "duration_sec": 2.0,
                    "segments": [
                        {
                            "segment_id": "segment-1",
                            "start_sec": 0.0,
                            "end_sec": 2.0,
                        }
                    ],
                },
            )

            exit_code, _, _ = _run_main(
                "audit-subtitles",
                "--project",
                project,
                "--subtitle-source",
                subtitle_source,
                "--realized-timeline",
                realized,
                "--output",
                output,
                "--mode",
                "preview",
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            payload = output.read_bytes()
            self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))
            report = json.loads(payload.decode("utf-8"))
            schema = json.loads(READABILITY_SCHEMA.read_text(encoding="utf-8"))
            self.assertEqual(
                list(Draft202012Validator(schema).iter_errors(report)), []
            )
            self.assertEqual(report["document_type"], "subtitle_readability_qa")
            self.assertEqual(report["cue_count"], 1)
            self.assertEqual(report["cue_ids"], ["stable-cue-1"])
            self.assertEqual(report["mode"], "preview")

    def test_layout_probe_recomputes_policy_hash_before_media_work(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="firered-subtitle-layout-policy-cli-"
        ) as temporary:
            project = Path(temporary) / "project"
            source = project / "work" / "subtitles" / "source.json"
            plan = project / "work" / "enhancement" / "plan.json"
            timeline = project / "work" / "qa" / "timeline.json"
            readability = project / "work" / "qa" / "readability.json"
            output = project / "work" / "qa" / "layout.json"
            source_document = {
                "project_id": "layout-policy-cli",
                "cues": [],
            }
            timeline_document = {"duration_sec": 1.0, "segments": []}
            policy = {
                "policy_version": "1.0",
                "min_duration_sec": 0.8,
            }
            _write_json(source, source_document)
            _write_json(plan, {"subtitles": {"style": {}}})
            _write_json(timeline, timeline_document)
            _write_json(
                readability,
                {
                    "subtitle_source_sha256": hashlib.sha256(
                        source.read_bytes()
                    ).hexdigest(),
                    "realized_timeline_sha256": hashlib.sha256(
                        timeline.read_bytes()
                    ).hexdigest(),
                    "policy_version": "1.0",
                    "policy_sha256": "0" * 64,
                    "policy": policy,
                },
            )

            exit_code, stdout, _ = _run_main(
                "probe-subtitle-layout",
                "--project",
                project,
                "--base-video",
                Path(temporary) / "missing-base.mkv",
                "--subtitle-source",
                source,
                "--plan",
                plan,
                "--realized-timeline",
                timeline,
                "--readability-qa",
                readability,
                "--output",
                output,
                "--mode",
                "release",
            )

            self.assertEqual(exit_code, 2)
            result = json.loads(stdout)
            self.assertIn("policy SHA-256", result["issues"][0]["message"])
            self.assertFalse(output.exists())

    def test_approve_subtitles_outputs_are_confined_by_artifact_type(self) -> None:
        cases = (
            ("approval", "work/subtitles/approval.json"),
            ("ready", "work/qa/ready.json"),
            ("evidence", "work/subtitles/evidence.json"),
        )
        for invalid_kind, invalid_path in cases:
            with self.subTest(invalid_kind=invalid_kind), tempfile.TemporaryDirectory(
                prefix="firered-subtitle-approve-path-"
            ) as temporary:
                project = Path(temporary) / "project"
                project.mkdir()
                fixture = _ApprovalFixture(project)
                plan = project / "work" / "enhancement" / "plan.json"
                _write_json(plan, {"subtitles": {"style": fixture.style}})
                approval = project / "work" / "qa" / "approval.json"
                ready = project / "work" / "subtitles" / "ready.json"
                evidence = project / "work" / "qa" / "evidence.json"
                selected = project / invalid_path
                if invalid_kind == "approval":
                    approval = selected
                elif invalid_kind == "ready":
                    ready = selected
                else:
                    evidence = selected

                exit_code, stdout, _ = _run_main(
                    "approve-subtitles",
                    "--project",
                    project,
                    "--subtitle-source",
                    fixture.source,
                    "--plan",
                    plan,
                    "--readability-qa",
                    fixture.readability,
                    "--layout-qa",
                    fixture.layout,
                    "--visual-qa",
                    fixture.visual,
                    "--human-review",
                    fixture.human,
                    "--approved-by",
                    "Human Reviewer",
                    "--approval-output",
                    approval,
                    "--ready-source-output",
                    ready,
                    "--evidence-output",
                    evidence,
                )

                self.assertEqual(exit_code, 2)
                result = json.loads(stdout)
                self.assertEqual(result["status"], "blocked")
                self.assertIn("must stay under", result["issues"][0]["message"])
                self.assertFalse(approval.is_file())
                self.assertFalse(ready.is_file())
                self.assertFalse(evidence.is_file())

    def test_approve_subtitles_generates_plan_ready_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="firered-subtitle-approve-cli-"
        ) as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            fixture = _ApprovalFixture(project)
            plan = project / "work" / "enhancement" / "plan.json"
            _write_json(plan, {"subtitles": {"style": fixture.style}})
            approval = project / "work" / "qa" / "subtitle-approval.json"
            ready = project / "work" / "subtitles" / "ready.json"
            evidence_output = project / "work" / "qa" / "ready-evidence.json"

            exit_code, stdout, _ = _run_main(
                "approve-subtitles",
                "--project",
                project,
                "--subtitle-source",
                fixture.source,
                "--plan",
                plan,
                "--readability-qa",
                fixture.readability,
                "--layout-qa",
                fixture.layout,
                "--visual-qa",
                fixture.visual,
                "--human-review",
                fixture.human,
                "--approved-by",
                "Human Reviewer",
                "--approval-output",
                approval,
                "--ready-source-output",
                ready,
                "--evidence-output",
                evidence_output,
            )

            self.assertEqual(exit_code, 0, stdout)
            evidence = json.loads(evidence_output.read_text(encoding="utf-8"))
            self.assertEqual(subtitle_ready_evidence_contract_issues(evidence), [])
            self.assertEqual(evidence["contract_version"], "subtitle-ready-evidence-v1")
            expected_paths = {
                "readability": fixture.readability,
                "layout": fixture.layout,
                "visual": fixture.visual,
                "human_review": fixture.human,
                "approval": approval,
            }
            for name, artifact in expected_paths.items():
                self.assertEqual(
                    evidence[name]["path"],
                    artifact.relative_to(project).as_posix(),
                )
                self.assertEqual(
                    evidence[name]["sha256"],
                    hashlib.sha256(artifact.read_bytes()).hexdigest(),
                )
            ready_document = json.loads(ready.read_text(encoding="utf-8"))
            ready_plan = {
                "subtitles": {
                    "status": "ready",
                    "language": ready_document["language"],
                    "source": ready.relative_to(project).as_posix(),
                    "source_sha256": hashlib.sha256(ready.read_bytes()).hexdigest(),
                    "coverage": {"status": "verified"},
                    "cues": [
                        {
                            "cue_id": cue["cue_id"],
                            "segment_id": cue["segment_id"],
                            "chapter_id": cue["chapter_id"],
                            "start_sec": cue["start_sec"],
                            "end_sec": cue["end_sec"],
                            "text": cue["text"],
                            "review_status": cue["review_status"],
                            "position": cue["position"],
                        }
                        for cue in ready_document["cues"]
                    ],
                    "style": fixture.style,
                    "evidence": evidence,
                }
            }
            self.assertEqual(validate_enhancement_assets(project, ready_plan), [])

            result = json.loads(stdout)
            self.assertEqual(
                Path(result["evidence_output"]).resolve(),
                evidence_output.resolve(),
            )
            self.assertEqual(result["ready_evidence"], evidence)
            self.assertTrue(ready.is_file())
            self.assertTrue(approval.is_file())

if __name__ == "__main__":
    unittest.main()
