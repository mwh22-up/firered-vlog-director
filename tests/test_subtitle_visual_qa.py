from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from imageio_ffmpeg import get_ffmpeg_exe
from jsonschema import Draft202012Validator

from vlog_director.subtitle_preview import render_subtitle_preview
from vlog_director.subtitle_readability import audit_subtitle_readability
from vlog_director.subtitle_visual_qa import HUMAN_REVIEW_LIMITATION, qa_subtitles


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _style_sha(style: dict, cue: dict) -> str:
    effective = dict(style)
    effective["position"] = cue.get(
        "position",
        style.get("position", "bottom_center"),
    )
    serialized = json.dumps(
        effective,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _inputs(root: Path, ffmpeg: str) -> tuple[Path, ...]:
    project, base = root / "project", root / "base.mkv"
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=white:s=320x180:r=10:d=2", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "ffv1",
        "-c:a", "pcm_s16le", "-shortest", str(base)], check=True)
    source = project / "work" / "subtitles" / "source.json"
    timeline = project / "work" / "qa" / "timeline.json"
    readability = project / "work" / "qa" / "readability.json"
    _write(source, {"schema_version": "1.0", "project_id": "visual-qa",
        "status": "review_required", "language": "en",
        "style": {"font_name": "Arial", "font_size": 64, "margin_v": 72,
            "outline": 4, "shadow": 1, "bold": True, "position": "bottom_center",
            "max_lines": 2, "safe_margin_percent": 8.0, "max_chars_per_line": 18,
            "background_opacity_percent": 42.0, "background_padding": 8},
        "cues": [
            {"cue_id": "cue-short", "segment_id": "s1", "chapter_id": "c1",
             "start_sec": 0.2, "end_sec": 0.7, "text": "two line\nsubtitle",
             "position": "top_center", "review_status": "review_required"},
            {"cue_id": "cue-normal", "segment_id": "s2", "chapter_id": "c2",
             "start_sec": 1.0, "end_sec": 1.8, "text": "bottom subtitle",
             "position": "bottom_center", "review_status": "review_required"}]})
    _write(timeline, {"schema_version": "1.0", "project_id": "visual-qa",
        "duration_sec": 2.0, "segments": [
            {"segment_id": "s1", "start_sec": 0.0, "end_sec": 0.8},
            {"segment_id": "s2", "start_sec": 0.8, "end_sec": 2.0}]})
    source_document = json.loads(source.read_text(encoding="utf-8"))
    source_document["coverage"] = {"status": "pending"}
    source_document["segment_coverage"] = [
        {"segment_id": "s1", "actual_start_sec": 0.0, "actual_end_sec": 0.8},
        {"segment_id": "s2", "actual_start_sec": 0.8, "actual_end_sec": 2.0},
    ]
    for cue in source_document["cues"]:
        cue["risk_flags"] = []
    _write(source, source_document)
    _write(
        readability,
        audit_subtitle_readability(
            source_document,
            mode="preview",
            subtitle_source_sha256=_sha(source),
            realized_timeline_sha256=_sha(timeline),
        ),
    )
    return project, base, source, timeline, readability


class SubtitleVisualQaTests(unittest.TestCase):
    def test_evidence_cleanup_directory_cannot_be_the_qa_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-evidence-root-") as temporary:
            project = Path(temporary) / "project"
            manifest = project / "work" / "proxy" / "manifest.json"
            _write(manifest, {})
            with self.assertRaisesRegex(ValueError, "below work/qa"):
                qa_subtitles(
                    project=project,
                    preview_manifest=manifest,
                    evidence_directory=project / "work" / "qa",
                    executable="not-invoked",
                )
    def test_all_scope_generates_evidence_but_never_human_approval(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-visual-") as temporary:
            project, base, source, timeline, readability = _inputs(Path(temporary), ffmpeg)
            manifest = render_subtitle_preview(
                project=project, base_video=base, subtitle_source=source,
                realized_timeline=timeline, readability_qa=readability,
                scope="all", proxy_unit="timeline", executable=ffmpeg)
            manifest_path = project / manifest["manifest_path"]
            report = qa_subtitles(project=project, preview_manifest=manifest_path,
                                  executable=ffmpeg)
            schema = json.loads((ROOT / "schemas" / "subtitle-visual-qa.schema.json").read_text())
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(report)), [])
            self.assertEqual(report["human_review"]["status"], "pending")
            self.assertIn(HUMAN_REVIEW_LIMITATION, report["limitations"])
            self.assertEqual(report["actual_rendered_cue_count"], 2)
            self.assertEqual(report["missing_cue_ids"], [])
            self.assertEqual({item["cue_id"] for item in report["cue_evidence"]},
                             {"cue-short", "cue-normal"})
            risk = report["high_risk_review_queue"][0]
            self.assertEqual(set(risk["frames"]), {"entry", "middle", "exit"})
            self.assertGreaterEqual(risk["distinct_frame_count"], 1)
            self.assertEqual(set(report["contact_sheets"]), {
                "two_line", "dense_segment", "position_change", "cut_boundary",
                "ultra_short"})
            self.assertEqual(report["bindings"]["subtitle_source_sha256"], _sha(source))
            self.assertEqual(report["bindings"]["preview_manifest_sha256"], _sha(manifest_path))

    def test_layout_contract_mismatches_block_but_keep_visual_frames(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-layout-stale-") as temporary:
            project, base, source, timeline, readability = _inputs(
                Path(temporary),
                ffmpeg,
            )
            source_document = json.loads(source.read_text(encoding="utf-8"))
            style = source_document["style"]
            plan = project / "work" / "enhancement" / "plan.json"
            layout = project / "work" / "qa" / "layout.json"
            _write(
                plan,
                {
                    "schema_version": "2.0",
                    "project_id": "visual-qa",
                    "subtitles": {"style": style},
                },
            )
            layout_cues = []
            for cue in source_document["cues"]:
                layout_cues.append(
                    {
                        "cue_id": cue["cue_id"],
                        "text_sha256": hashlib.sha256(
                            cue["text"].encode("utf-8")
                        ).hexdigest(),
                        "style_sha256": _style_sha(style, cue),
                        "position": cue["position"],
                        "clipped": False,
                        "inside_safe_area": True,
                        "real_layout_verified": True,
                        "line_count": cue["text"].count("\n") + 1,
                    }
                )
            layout_cues[0].update(
                {
                    "style_sha256": "0" * 64,
                    "position": "bottom_center",
                    "clipped": True,
                    "inside_safe_area": False,
                    "real_layout_verified": False,
                }
            )
            _write(
                layout,
                {
                    "schema_version": "1.0",
                    "document_type": "subtitle_layout_qa",
                    "probe_version": "libass-rgb24-bbox-v1",
                    "status": "passed",
                    "probe_mode": "real_libass",
                    "bindings": {
                        "subtitle_source_sha256": "1" * 64,
                        "realized_timeline_sha256": "2" * 64,
                        "enhancement_plan_sha256": "3" * 64,
                        "readability_policy_version": "stale-policy",
                    },
                    "cues": layout_cues,
                },
            )
            manifest = render_subtitle_preview(
                project=project,
                base_video=base,
                subtitle_source=source,
                realized_timeline=timeline,
                enhancement_plan=plan,
                readability_qa=readability,
                scope="all",
                proxy_unit="timeline",
                executable=ffmpeg,
            )
            manifest_path = project / manifest["manifest_path"]
            manifest_document = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_document["bindings"]["layout_qa"] = {
                "path": layout.relative_to(project).as_posix(),
                "sha256": _sha(layout),
                "probe_version": "libass-rgb24-bbox-v1",
                "probe_mode": "real_libass",
                "status": "passed",
            }
            manifest_document["bindings"]["layout_probe_version"] = "stale-probe"
            _write(manifest_path, manifest_document)
            report = qa_subtitles(
                project=project,
                preview_manifest=manifest_path,
                executable=ffmpeg,
            )

            codes = {item["code"] for item in report["blockers"]}
            self.assertTrue(
                {
                    "layout_subtitle_source_mismatch",
                    "layout_realized_timeline_mismatch",
                    "layout_enhancement_plan_mismatch",
                    "layout_readability_policy_mismatch",
                    "layout_probe_version_mismatch",
                    "layout_ffmpeg_identity_mismatch",
                    "layout_canvas_mismatch",
                    "subtitle_layout_style_mismatch",
                    "subtitle_layout_position_mismatch",
                    "subtitle_layout_clipped",
                    "subtitle_layout_outside_safe_area",
                    "subtitle_real_layout_unverified",
                }.issubset(codes)
            )
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(
                {item["cue_id"] for item in report["cue_evidence"]},
                {"cue-short", "cue-normal"},
            )
            self.assertTrue((project / report["ffmpeg_log_path"]).is_file())
            self.assertTrue((project / report["report_path"]).is_file())

    def test_unknown_manifest_field_fails_closed_but_keeps_visual_frames(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-manifest-schema-") as temporary:
            project, base, source, timeline, readability = _inputs(
                Path(temporary),
                ffmpeg,
            )
            manifest = render_subtitle_preview(
                project=project,
                base_video=base,
                subtitle_source=source,
                realized_timeline=timeline,
                readability_qa=readability,
                scope="all",
                proxy_unit="timeline",
                executable=ffmpeg,
            )
            manifest_path = project / manifest["manifest_path"]
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            document["unknown_contract_field"] = True
            _write(manifest_path, document)

            report = qa_subtitles(
                project=project,
                preview_manifest=manifest_path,
                executable=ffmpeg,
            )
            self.assertIn(
                "subtitle_preview_manifest_schema_invalid",
                {item["code"] for item in report["blockers"]},
            )
            self.assertEqual(
                {item["cue_id"] for item in report["cue_evidence"]},
                {"cue-short", "cue-normal"},
            )

    def test_empty_manifest_cannot_claim_all_source_cues_passed(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-empty-manifest-") as temporary:
            project, base, source, timeline, readability = _inputs(
                Path(temporary),
                ffmpeg,
            )
            manifest = render_subtitle_preview(
                project=project,
                base_video=base,
                subtitle_source=source,
                realized_timeline=timeline,
                readability_qa=readability,
                scope="all",
                proxy_unit="timeline",
                executable=ffmpeg,
            )
            manifest_path = project / manifest["manifest_path"]
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            empty_bundle_sha = hashlib.sha256(b"[]").hexdigest()
            document["cue_count"] = 0
            document["actual_rendered_cue_count"] = 0
            document["selection"] = {
                "planned_cue_ids": [],
                "selected_trigger_cue_ids": [],
                "planned_rendered_cue_ids": [],
                "missing_selected_cue_ids": [],
                "unrendered_due_to_scope_cue_ids": [],
            }
            document["outputs"] = []
            document["ass_bundle_sha256"] = empty_bundle_sha
            document["media_bundle_sha256"] = empty_bundle_sha
            _write(manifest_path, document)

            report = qa_subtitles(
                project=project,
                preview_manifest=manifest_path,
                executable=ffmpeg,
            )
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["machine_status"], "blocked")
            self.assertIn(
                "subtitle_manifest_cue_set_mismatch",
                {item["code"] for item in report["blockers"]},
            )
            self.assertEqual(report["cue_evidence"], [])
    def test_manifest_artifact_bindings_are_confined_by_type(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-binding-roots-") as temporary:
            project, base, source, timeline, readability = _inputs(
                Path(temporary),
                ffmpeg,
            )
            manifest = render_subtitle_preview(
                project=project,
                base_video=base,
                subtitle_source=source,
                realized_timeline=timeline,
                readability_qa=readability,
                scope="all",
                proxy_unit="timeline",
                executable=ffmpeg,
            )
            cases = {
                "source": (
                    lambda value: value["bindings"]["subtitle_source"].update(
                        {"path": "work/qa/source.json"}
                    ),
                    "subtitle_source_path_invalid",
                ),
                "timeline": (
                    lambda value: value["bindings"]["realized_timeline"].update(
                        {"path": "work/subtitles/timeline.json"}
                    ),
                    "realized_timeline_path_invalid",
                ),
                "readability": (
                    lambda value: value["bindings"]["readability_qa"].update(
                        {"path": "work/subtitles/readability.json"}
                    ),
                    "readability_qa_path_invalid",
                ),
                "layout": (
                    lambda value: value["bindings"].update(
                        {
                            "layout_qa": {
                                "path": "work/subtitles/layout.json",
                                "sha256": "0" * 64,
                                "probe_version": "probe-v1",
                            },
                            "layout_probe_version": "probe-v1",
                        }
                    ),
                    "layout_qa_path_invalid",
                ),
                "ass": (
                    lambda value: value["outputs"][0].update(
                        {"ass_path": "work/qa/proxy.ass"}
                    ),
                    "preview_ass_path_invalid",
                ),
                "media": (
                    lambda value: value["outputs"][0].update(
                        {"media_path": "work/qa/proxy.mkv"}
                    ),
                    "preview_media_path_invalid",
                ),
            }
            for name, (mutate, expected_code) in cases.items():
                with self.subTest(binding=name):
                    forged = json.loads(json.dumps(manifest))
                    mutate(forged)
                    forged_path = project / "work" / "proxy" / f"forged-{name}.json"
                    _write(forged_path, forged)
                    report = qa_subtitles(
                        project=project,
                        preview_manifest=forged_path,
                        executable=ffmpeg,
                    )
                    self.assertIn(
                        expected_code,
                        {item["code"] for item in report["blockers"]},
                    )
                    self.assertEqual(report["machine_status"], "blocked")
    def test_qa_ffmpeg_identity_mismatch_uses_actual_identity(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-ffmpeg-stale-") as temporary:
            project, base, source, timeline, readability = _inputs(
                Path(temporary),
                ffmpeg,
            )
            manifest = render_subtitle_preview(
                project=project,
                base_video=base,
                subtitle_source=source,
                realized_timeline=timeline,
                readability_qa=readability,
                scope="all",
                proxy_unit="timeline",
                executable=ffmpeg,
            )
            actual_sha = "f" * 64
            with patch(
                "vlog_director.subtitle_visual_qa.inspect_ffmpeg_identity",
                return_value={"executable_sha256": actual_sha},
            ):
                report = qa_subtitles(
                    project=project,
                    preview_manifest=project / manifest["manifest_path"],
                    executable=ffmpeg,
                )
            self.assertIn(
                "subtitle_qa_ffmpeg_identity_mismatch",
                {item["code"] for item in report["blockers"]},
            )
            self.assertEqual(
                report["bindings"]["ffmpeg_executable_sha256"],
                actual_sha,
            )
            self.assertEqual(len(report["cue_evidence"]), 2)

    def test_source_change_invalidates_old_visual_evidence(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-stale-") as temporary:
            project, base, source, timeline, readability = _inputs(Path(temporary), ffmpeg)
            manifest = render_subtitle_preview(
                project=project, base_video=base, subtitle_source=source,
                realized_timeline=timeline, readability_qa=readability,
                scope="risk", proxy_unit="cue", executable=ffmpeg)
            manifest_path = project / manifest["manifest_path"]
            changed = json.loads(source.read_text(encoding="utf-8"))
            changed["cues"][0]["text"] = "changed after preview"
            _write(source, changed)
            report = qa_subtitles(project=project, preview_manifest=manifest_path,
                                  executable=ffmpeg)
            self.assertEqual(report["status"], "blocked")
            self.assertIn("subtitle_source_sha256_mismatch",
                          {item["code"] for item in report["blockers"]})
            self.assertEqual(report["human_review"]["status"], "pending")
            self.assertEqual(report["cue_evidence"], [])


if __name__ == "__main__":
    unittest.main()
