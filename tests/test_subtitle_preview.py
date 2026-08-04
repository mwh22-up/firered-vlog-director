from __future__ import annotations

import json
import os
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from vlog_director.subtitle_preview import (
    create_unique_preview_directory,
    render_subtitle_preview,
    run_subtitle_preview_job,
    select_preview_units,
    submit_subtitle_preview_job,
)
from vlog_director.subtitle_readability import audit_subtitle_readability


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document) + "\n", encoding="utf-8")


def _subtitle_document() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "preview-unit",
        "status": "review_required",
        "language": "en",
        "style": {"font_name": "Arial", "font_size": 64, "max_lines": 2,
                  "max_chars_per_line": 18, "safe_margin_percent": 8.0,
                  "position": "bottom_center"},
        "cues": [
            {"cue_id": "cue-a", "segment_id": "segment-a", "chapter_id": "chapter-a",
             "start_sec": 0.4, "end_sec": 0.9, "text": "first risk cue",
             "review_status": "review_required"},
            {"cue_id": "cue-b", "segment_id": "segment-a", "chapter_id": "chapter-a",
             "start_sec": 1.1, "end_sec": 1.8, "text": "second cue",
             "review_status": "review_required"},
            {"cue_id": "cue-c", "segment_id": "segment-b", "chapter_id": "chapter-b",
             "start_sec": 2.1, "end_sec": 2.8, "text": "third cue",
             "review_status": "review_required"},
        ],
    }


def _timeline() -> dict:
    return {
        "schema_version": "1.0", "project_id": "preview-unit", "duration_sec": 3.0,
        "segments": [
            {"segment_id": "segment-a", "start_sec": 0.0, "end_sec": 2.0},
            {"segment_id": "segment-b", "start_sec": 2.0, "end_sec": 3.0},
        ],
    }


class SubtitlePreviewUnitTests(unittest.TestCase):
    def test_default_directories_are_unique_confined_and_cleanable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            (project / "work" / "proxy").mkdir(parents=True)
            first = create_unique_preview_directory(project)
            second = create_unique_preview_directory(project)
            self.assertNotEqual(first, second)
            self.assertEqual(first.relative_to(project.resolve()).parts[:3],
                             ("work", "proxy", "subtitle-preview"))

    def test_risk_cue_scope_distinguishes_trigger_and_scope_exclusion(self) -> None:
        units, selection = select_preview_units(
            _subtitle_document(), _timeline(), scope="risk", proxy_unit="cue",
            padding_sec=0.2, high_risk_cue_ids={"cue-a"})
        self.assertEqual(units[0]["trigger_cue_ids"], ["cue-a"])
        self.assertEqual(units[0]["rendered_cue_ids"], ["cue-a"])
        self.assertEqual(selection["unrendered_due_to_scope_cue_ids"], ["cue-b", "cue-c"])
        self.assertEqual(selection["missing_selected_cue_ids"], [])

    def test_risk_segment_renders_context_without_promoting_it_to_trigger(self) -> None:
        units, selection = select_preview_units(
            _subtitle_document(), _timeline(), scope="risk", proxy_unit="segment",
            padding_sec=0.2, high_risk_cue_ids={"cue-a"})
        self.assertEqual(units[0]["unit_id"], "segment-a")
        self.assertEqual(units[0]["trigger_cue_ids"], ["cue-a"])
        self.assertEqual(units[0]["rendered_cue_ids"], ["cue-a", "cue-b"])
        self.assertEqual(selection["unrendered_due_to_scope_cue_ids"], ["cue-c"])

    def test_chapter_and_timeline_use_realized_bounds(self) -> None:
        chapters, _ = select_preview_units(
            _subtitle_document(), _timeline(), scope="all", proxy_unit="chapter",
            padding_sec=0.5, high_risk_cue_ids=set())
        timeline, _ = select_preview_units(
            _subtitle_document(), _timeline(), scope="all", proxy_unit="timeline",
            padding_sec=0.5, high_risk_cue_ids=set())
        self.assertEqual([(u["unit_id"], u["start_sec"], u["end_sec"]) for u in chapters],
                         [("chapter-a", 0.0, 2.0), ("chapter-b", 2.0, 3.0)])
        self.assertEqual((timeline[0]["start_sec"], timeline[0]["end_sec"]), (0.0, 3.0))

    def test_metadata_paths_cannot_escape_project_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = root / "outside.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            with self.assertRaisesRegex(ValueError, "subtitle source"):
                render_subtitle_preview(project=project, base_video=base,
                                        subtitle_source=source, realized_timeline=timeline,
                                        executable="not-invoked")

    def test_cleanup_directory_can_never_be_the_proxy_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            with self.assertRaisesRegex(ValueError, "below work/proxy"):
                render_subtitle_preview(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                    output_directory=project / "work" / "proxy",
                    executable="not-invoked",
                )

    def test_cleanup_schema_requires_a_strict_proxy_or_qa_descendant(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "subtitle-preview-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = json.loads(
            (
                ROOT
                / "src"
                / "vlog_director"
                / "schemas"
                / "subtitle-preview-manifest.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(schema, runtime)
        cleanup_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": schema["$defs"],
            **schema["properties"]["cleanup_paths"],
        }
        validator = Draft202012Validator(cleanup_schema)
        for invalid in (
            ["work/proxy"],
            ["work/qa"],
            ["work/render/job"],
            ["work/proxy/../qa/job"],
            [r"work/proxy\job"],
            ["work/proxy//job"],
        ):
            with self.subTest(path=invalid[0]):
                self.assertTrue(list(validator.iter_errors(invalid)))
        self.assertEqual(
            list(validator.iter_errors(["work/proxy/subtitle-preview/job-id"])),
            [],
        )

    def test_preview_recomputes_readability_policy_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            readability_path = project / "work" / "qa" / "readability.json"
            base.write_bytes(b"media")
            source_document = _subtitle_document()
            source_document["coverage"] = {"status": "pending"}
            source_document["segment_coverage"] = [
                {
                    "segment_id": item["segment_id"],
                    "actual_start_sec": item["start_sec"],
                    "actual_end_sec": item["end_sec"],
                }
                for item in _timeline()["segments"]
            ]
            _write_json(source, source_document)
            _write_json(timeline, _timeline())
            readability = audit_subtitle_readability(
                source_document,
                mode="preview",
                subtitle_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                realized_timeline_sha256=hashlib.sha256(timeline.read_bytes()).hexdigest(),
            )
            readability["policy"]["max_duration_sec"] = 5.25
            _write_json(readability_path, readability)

            with self.assertRaisesRegex(ValueError, "policy SHA"):
                render_subtitle_preview(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                    readability_qa=readability_path,
                    output_directory=project / "work" / "proxy" / "policy-stale",
                    executable="not-invoked",
                )
    def test_provided_readability_qa_must_be_schema_valid_and_sha_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            readability = project / "work" / "qa" / "readability.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            _write_json(
                readability,
                {
                    "schema_version": "1.0",
                    "document_type": "subtitle_readability_qa",
                    "policy_version": "1.0",
                    "project_id": "preview-unit",
                    "subtitle_source_sha256": "0" * 64,
                    "realized_timeline_sha256": "0" * 64,
                    "cue_count": 0,
                    "cues": [],
                },
            )
            with self.assertRaisesRegex(ValueError, "readability QA schema invalid"):
                render_subtitle_preview(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                    readability_qa=readability,
                    scope="risk",
                    proxy_unit="cue",
                    output_directory=project / "work" / "proxy" / "strict-qa",
                    executable="not-invoked",
                )
    def test_background_submission_uses_detached_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            with patch("vlog_director.subtitle_preview_runtime.subprocess.Popen") as popen:
                popen.return_value.pid = 4321
                result = submit_subtitle_preview_job(
                    project=project, base_video=base, subtitle_source=source,
                    realized_timeline=timeline)
            self.assertEqual(result["status"], "queued")
            self.assertTrue(Path(result["job_spec"]).is_file())
            kwargs = popen.call_args.kwargs
            self.assertIs(kwargs["stdin"], __import__("subprocess").DEVNULL)
            self.assertTrue(kwargs["creationflags"] if os.name == "nt"
                            else kwargs["start_new_session"])

    def test_worker_job_spec_is_confined_and_output_must_equal_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            with patch("vlog_director.subtitle_preview_runtime.subprocess.Popen") as popen:
                popen.return_value.pid = 4321
                submission = submit_subtitle_preview_job(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                )
            valid_spec = Path(submission["job_spec"])
            escaped_spec = project / "work" / "proxy" / "job.json"
            escaped_status = escaped_spec.parent / "status.json"
            escaped_spec.write_bytes(valid_spec.read_bytes())
            _write_json(escaped_status, {"schema_version": "1.0", "status": "queued"})
            with patch(
                "vlog_director.subtitle_preview_runtime.render_subtitle_preview",
                return_value={"status": "completed"},
            ), self.assertRaisesRegex(ValueError, "unique subtitle preview directory"):
                run_subtitle_preview_job(escaped_spec)

            spec = json.loads(valid_spec.read_text(encoding="utf-8"))
            spec["output_directory"] = str(valid_spec.parent / "different")
            _write_json(valid_spec, spec)
            with patch(
                "vlog_director.subtitle_preview_runtime.render_subtitle_preview",
                return_value={"status": "completed"},
            ), self.assertRaisesRegex(ValueError, "output_directory"):
                run_subtitle_preview_job(valid_spec)

    def test_worker_rejects_existing_evidence_and_job_replay(self) -> None:
        artifacts = (
            ("manifest.json", "{}\n"),
            ("existing.ass", "[Script Info]\n"),
            ("existing.mkv", "media"),
            ("ffmpeg.log", "old log\n"),
            ("progress.jsonl", '{"stage":"manifest","status":"completed"}\n'),
        )
        for name, content in artifacts:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                project = root / "project"
                base = root / "base.mkv"
                source = project / "work" / "subtitles" / "source.json"
                timeline = project / "work" / "qa" / "timeline.json"
                base.write_bytes(b"media")
                _write_json(source, _subtitle_document())
                _write_json(timeline, _timeline())
                with patch("vlog_director.subtitle_preview_runtime.subprocess.Popen") as popen:
                    popen.return_value.pid = 4321
                    submission = submit_subtitle_preview_job(
                        project=project,
                        base_video=base,
                        subtitle_source=source,
                        realized_timeline=timeline,
                    )
                spec_path = Path(submission["job_spec"])
                (spec_path.parent / name).write_text(content, encoding="utf-8")
                with patch(
                    "vlog_director.subtitle_preview_runtime.render_subtitle_preview",
                    return_value={"status": "completed"},
                ), self.assertRaises((FileExistsError, ValueError)):
                    run_subtitle_preview_job(spec_path)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())
            with patch("vlog_director.subtitle_preview_runtime.subprocess.Popen") as popen:
                popen.return_value.pid = 4321
                submission = submit_subtitle_preview_job(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                )
            spec_path = Path(submission["job_spec"])
            _write_json(
                Path(submission["job_status"]),
                {"schema_version": "1.0", "status": "completed", "exit_code": 0},
            )
            with patch(
                "vlog_director.subtitle_preview_runtime.render_subtitle_preview",
                return_value={"status": "completed"},
            ), self.assertRaisesRegex(ValueError, "queued"):
                run_subtitle_preview_job(spec_path)

    def test_preview_launcher_never_overwrites_fast_worker_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "base.mkv"
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            base.write_bytes(b"media")
            _write_json(source, _subtitle_document())
            _write_json(timeline, _timeline())

            class Process:
                pid = 4321

            def finish_immediately(command: list[str], **_: object) -> Process:
                spec_path = Path(command[-1])
                _write_json(
                    spec_path.parent / "status.json",
                    {"schema_version": "1.0", "status": "completed", "exit_code": 0},
                )
                return Process()

            with patch(
                "vlog_director.subtitle_preview_runtime.subprocess.Popen",
                side_effect=finish_immediately,
            ):
                submission = submit_subtitle_preview_job(
                    project=project,
                    base_video=base,
                    subtitle_source=source,
                    realized_timeline=timeline,
                )
            status = json.loads(
                Path(submission["job_status"]).read_text(encoding="utf-8")
            )
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
