from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.subtitle_approval import (
    build_subtitle_approval,
    create_ready_subtitle_source,
    validate_subtitle_approval,
)
from vlog_director.subtitle_readability import (
    audit_subtitle_readability,
    canonical_subtitle_payload_digest,
    canonical_subtitle_style_digest,
    canonical_verified_cue_set_digest,
)


ROOT = Path(__file__).resolve().parents[1]
FORMAL_HUMAN_SCHEMA = ROOT / "schemas" / "subtitle-human-review.schema.json"
RUNTIME_HUMAN_SCHEMA = (
    ROOT / "src" / "vlog_director" / "schemas" / "subtitle-human-review.schema.json"
)
FORMAL_APPROVAL_SCHEMA = ROOT / "schemas" / "subtitle-approval.schema.json"
RUNTIME_APPROVAL_SCHEMA = (
    ROOT / "src" / "vlog_director" / "schemas" / "subtitle-approval.schema.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


class _ApprovalFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "work" / "subtitles" / "reviewed.json"
        self.readability = root / "work" / "qa" / "readability.json"
        self.layout = root / "work" / "qa" / "layout.json"
        self.visual = root / "work" / "qa" / "visual.json"
        self.human = root / "work" / "qa" / "human-review.json"
        self.approval = root / "work" / "qa" / "subtitle-approval.json"
        self.ready = root / "work" / "subtitles" / "ready.json"
        self.timeline_sha256 = "b" * 64
        self.style = {
            "font_name": "Arial",
            "font_size": 64,
            "margin_v": 72,
            "outline": 4,
            "shadow": 1,
            "bold": True,
            "position": "bottom_center",
            "max_lines": 2,
            "safe_margin_percent": 8.0,
            "max_chars_per_line": 18,
            "background_opacity_percent": 42.0,
            "background_padding": 8,
        }
        self.source_document = {
            "schema_version": "1.0",
            "document_type": "subtitle_review_draft",
            "project_id": "approval-fixture",
            "subtitle_version": 5,
            "status": "review_required",
            "language": "zh-CN",
            "coverage": {"status": "verified"},
            "segment_coverage": [
                {
                    "segment_id": "segment-1",
                    "actual_start_sec": 0.0,
                    "actual_end_sec": 8.0,
                }
            ],
            "cues": [
                {
                    "cue_id": "cue-1",
                    "segment_id": "segment-1",
                    "chapter_id": "chapter-1",
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                    "text": "第一句",
                    "position": "bottom_center",
                    "review_status": "verified",
                    "risk_flags": [],
                },
                {
                    "cue_id": "cue-2",
                    "segment_id": "segment-1",
                    "chapter_id": "chapter-1",
                    "start_sec": 3.0,
                    "end_sec": 4.2,
                    "text": "second line",
                    "position": "top_center",
                    "review_status": "verified",
                    "risk_flags": [],
                },
            ],
        }
        _write(self.source, self.source_document)
        self.refresh_qa_and_human()

    @property
    def cue_ids(self) -> list[str]:
        return [str(cue["cue_id"]) for cue in self.source_document["cues"]]

    def refresh_qa_and_human(self) -> None:
        source_sha = _sha(self.source)
        readability = audit_subtitle_readability(
            self.source_document,
            mode="release",
            subtitle_source_sha256=source_sha,
            realized_timeline_sha256=self.timeline_sha256,
        )
        self.assert_passed_readability(readability)
        _write(self.readability, readability)

        layout_cues = []
        for cue in self.source_document["cues"]:
            effective_style = dict(self.style)
            effective_style["position"] = cue.get(
                "position", self.style["position"]
            )
            layout_cues.append(
                {
                    "cue_id": cue["cue_id"],
                    "text_sha256": hashlib.sha256(
                        str(cue["text"]).encode("utf-8")
                    ).hexdigest(),
                    "style_sha256": _canonical_sha(effective_style),
                    "position": effective_style["position"],
                    "real_layout_verified": True,
                    "inside_safe_area": True,
                    "clipped": False,
                    "warning_codes": [],
                    "blocker_codes": [],
                }
            )
        layout = {
            "schema_version": "1.0",
            "document_type": "subtitle_layout_qa",
            "probe_version": "libass-rgb24-bbox-v1",
            "status": "passed",
            "mode": "release",
            "probe_mode": "real_libass",
            "project_id": "approval-fixture",
            "bindings": {
                "subtitle_source_sha256": source_sha,
                "realized_timeline_sha256": self.timeline_sha256,
                "readability_qa_sha256": _sha(self.readability),
                "readability_policy_sha256": readability["policy_sha256"],
                "ass_sha256": "c" * 64,
                "readability_policy_version": readability["policy_version"],
            },
            "summary": {
                "cue_count": len(layout_cues),
                "real_layout_verified_count": len(layout_cues),
                "blocker_count": 0,
                "warning_count": 0,
            },
            "cues": layout_cues,
            "warning_codes": [],
            "blocker_codes": [],
        }
        layout["summary"]["cache_hit_count"] = 0
        layout.update(
            {
                "ffmpeg_identity": {
                    "executable_name": "ffmpeg.exe",
                    "executable_size_bytes": 1,
                    "executable_sha256": "1" * 64,
                    "version_line": "ffmpeg fixture",
                    "configuration_sha256": "2" * 64,
                    "filters_sha256": "3" * 64,
                    "subtitles_filter_available": True,
                    "libass_enabled": True,
                },
                "font_directory_identity": {
                    "present": True,
                    "sha256": "4" * 64,
                    "file_count": 1,
                    "files": [
                        {
                            "path": "fonts/fixture.ttf",
                            "size_bytes": 1,
                            "sha256": "5" * 64,
                        }
                    ],
                },
                "canvas": {"width": 1920, "height": 1080},
                "capabilities": {
                    "subtitles_filter_available": True,
                    "libass_enabled": True,
                    "real_frame_measurement": True,
                    "ocr_performed": False,
                },
                "limitations": ["Fixture contains layout evidence, not OCR evidence."],
            }
        )
        for index, cue_result in enumerate(layout_cues):
            cue_result.update(
                {
                    "ass_sha256": "c" * 64,
                    "cache_key": hashlib.sha256(
                        f"layout-cache-{index}".encode("utf-8")
                    ).hexdigest(),
                    "cache_hit": False,
                    "sample_time_sec": 1.5 + index,
                    "line_count": 1,
                    "line_count_source": "ass_dialogue_explicit_breaks",
                    "effective_font_size": 64,
                    "safe_area": {"x": 154, "y": 86, "width": 1612, "height": 908},
                    "measured_bbox": {
                        "x": 760,
                        "y": 880 if cue_result["position"] == "bottom_center" else 120,
                        "width": 400,
                        "height": 80,
                    },
                    "measured_pixel_count": 8000,
                    "measurement_method": "ffmpeg-libass-rgb24-control-difference-v1",
                    "font_resolution": {
                        "requested_font": "Arial",
                        "status": "resolved",
                        "resolved_faces": ["Arial"],
                        "fallback_detected": False,
                        "missing_glyph_observed": False,
                        "log_sha256": "6" * 64,
                    },
                }
            )
        _write(self.layout, layout)

        visual = {
            "schema_version": "1.0",
            "document_type": "subtitle_visual_qa",
            "qa_version": "subtitle-visual-evidence-v1",
            "status": "review_required",
            "machine_status": "passed",
            "project_id": "approval-fixture",
            "scope": "all",
            "bindings": {
                "preview_manifest_path": "work/proxy/manifest.json",
                "preview_manifest_sha256": "d" * 64,
                "subtitle_source_path": "work/subtitles/review.json",
                "subtitle_source_sha256": source_sha,
                "realized_timeline_path": "work/qa/timeline.json",
                "realized_timeline_sha256": self.timeline_sha256,
                "enhancement_plan_sha256": None,
                "readability_qa_sha256": _sha(self.readability),
                "readability_policy_sha256": readability["policy_sha256"],
                "layout_qa_sha256": _sha(self.layout),
                "ass_bundle_sha256": "1" * 64,
                "media_bundle_sha256": "2" * 64,
                "base_media_sha256": "e" * 64,
                "ffmpeg_executable_sha256": "f" * 64,
                "readability_policy_version": readability["policy_version"],
                "layout_probe_version": layout["probe_version"],
            },
            "cue_count": len(self.cue_ids),
            "actual_rendered_cue_count": len(self.cue_ids),
            "cue_ids": self.cue_ids,
            "rendered_cue_ids": self.cue_ids,
            "missing_cue_ids": [],
            "unrendered_due_to_scope_cue_ids": [],
            "blockers": [],
            "warnings": [],
            "human_review": {
                "status": "pending",
                "approval_path": None,
                "approval_sha256": None,
            },
            "release_ready": False,
            "limitations": [
                "已生成视觉帧和布局证据，文字准确性仍需人工听校。"
            ],
        }
        visual.update(
            {
                "readability_summary": {
                    "provided": True,
                    "status": readability["status"],
                    "high_risk_cue_count": 0,
                },
                "layout_probe_summary": {
                    "provided": True,
                    "status": layout["status"],
                    "probe_mode": layout["probe_mode"],
                    "cue_count": len(layout_cues),
                },
                "ass_parse_summary": {
                    "ass_count": 1,
                    "passed_count": 1,
                    "failed_count": 0,
                },
                "cue_evidence": [
                    {
                        "cue_id": cue_id,
                        "output_id": "preview-all",
                        "ass_sha256": "c" * 64,
                        "media_sha256": "7" * 64,
                        "frames": {
                            "middle": {
                                "path": f"work/qa/frames/{cue_id}-middle.png",
                                "sha256": hashlib.sha256(
                                    f"{cue_id}-middle".encode("utf-8")
                                ).hexdigest(),
                                "time_sec": 1.5 + index,
                            }
                        },
                    }
                    for index, cue_id in enumerate(self.cue_ids)
                ],
                "high_risk_review_queue": [],
                "contact_sheets": {
                    "two_line": [],
                    "dense_segment": [],
                    "position_change": [],
                    "cut_boundary": [],
                    "ultra_short": [],
                },
                "ffmpeg_log_path": "work/qa/subtitle-preview.ffmpeg.log",
                "report_path": "work/qa/visual.json",
            }
        )
        _write(self.visual, visual)

        human = {
            "schema_version": "1.0",
            "document_type": "subtitle_human_review",
            "status": "approved",
            "project_id": "approval-fixture",
            "subtitle_source_sha256": source_sha,
            "subtitle_payload_sha256": canonical_subtitle_payload_digest(
                self.source_document
            ),
            "subtitle_style_sha256": canonical_subtitle_style_digest(self.style),
            "verified_cue_set_sha256": canonical_verified_cue_set_digest(
                self.source_document["cues"]
            ),
            "readability_qa_sha256": _sha(self.readability),
            "layout_qa_sha256": _sha(self.layout),
            "visual_qa_sha256": _sha(self.visual),
            "cue_ids": self.cue_ids,
            "checks": {
                "audio_text_accuracy": "approved",
                "timing_and_cut_boundaries": "approved",
                "readability": "approved",
                "layout_and_safe_area": "approved",
                "visual_evidence_review": "approved",
            },
            "approved_by": "Human Reviewer",
            "approved_at": "2026-08-03T09:00:00+00:00",
            "notes": [],
        }
        _write(self.human, human)

    @staticmethod
    def assert_passed_readability(report: dict) -> None:
        if report["status"] != "passed" or not report["release_ready"]:
            raise AssertionError(report)

    def build(self) -> dict:
        return build_subtitle_approval(
            review_source_path=self.source,
            plan_style=self.style,
            readability_qa_path=self.readability,
            layout_qa_path=self.layout,
            visual_qa_path=self.visual,
            human_review_path=self.human,
            approved_by="Human Reviewer",
            output_path=self.approval,
            created_at="2026-08-03T10:00:00+00:00",
        )

    def validate(self, *, source: Path | None = None, style: dict | None = None) -> dict:
        return validate_subtitle_approval(
            subtitle_source_path=source or self.source,
            plan_style=style or self.style,
            readability_qa_path=self.readability,
            layout_qa_path=self.layout,
            visual_qa_path=self.visual,
            human_review_path=self.human,
            approval_path=self.approval,
        )


class SubtitleApprovalTests(unittest.TestCase):
    def test_builds_hash_bound_approval_and_validates_schemas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-approval-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))

            approval = fixture.build()

            self.assertEqual(approval["status"], "approved")
            self.assertEqual(approval["review_source_sha256"], _sha(fixture.source))
            self.assertEqual(approval["readability_qa_sha256"], _sha(fixture.readability))
            self.assertEqual(approval["layout_qa_sha256"], _sha(fixture.layout))
            self.assertEqual(approval["visual_qa_sha256"], _sha(fixture.visual))
            self.assertEqual(approval["human_review_sha256"], _sha(fixture.human))
            self.assertEqual(fixture.validate()["status"], "passed")
            self.assertFalse(fixture.approval.read_bytes().startswith(b"\xef\xbb\xbf"))

            formal_human = json.loads(FORMAL_HUMAN_SCHEMA.read_text(encoding="utf-8"))
            runtime_human = json.loads(RUNTIME_HUMAN_SCHEMA.read_text(encoding="utf-8"))
            formal_approval = json.loads(
                FORMAL_APPROVAL_SCHEMA.read_text(encoding="utf-8")
            )
            runtime_approval = json.loads(
                RUNTIME_APPROVAL_SCHEMA.read_text(encoding="utf-8")
            )
            self.assertEqual(formal_human, runtime_human)
            self.assertEqual(formal_approval, runtime_approval)
            Draft202012Validator.check_schema(formal_human)
            Draft202012Validator.check_schema(formal_approval)
            human = json.loads(fixture.human.read_text(encoding="utf-8"))
            self.assertEqual(
                list(Draft202012Validator(formal_human).iter_errors(human)), []
            )
            self.assertEqual(
                list(Draft202012Validator(formal_approval).iter_errors(approval)), []
            )

    def test_source_must_be_fully_verified_before_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-unverified-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))
            source = json.loads(fixture.source.read_text(encoding="utf-8"))
            source["cues"][0]["review_status"] = "review_required"
            source["coverage"]["status"] = "pending"
            _write(fixture.source, source)

            with self.assertRaisesRegex(ValueError, "verified"):
                fixture.build()

    def test_builder_consumes_but_never_fabricates_human_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-human-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))
            human = json.loads(fixture.human.read_text(encoding="utf-8"))
            human["status"] = "pending"
            human["checks"]["audio_text_accuracy"] = "pending"
            _write(fixture.human, human)

            with self.assertRaisesRegex(ValueError, "human review"):
                fixture.build()
            self.assertFalse(fixture.approval.exists())

    def test_human_review_cue_set_and_bindings_must_match_exactly(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-human-bind-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))
            human = json.loads(fixture.human.read_text(encoding="utf-8"))
            human["cue_ids"] = ["cue-1"]
            human["readability_qa_sha256"] = "0" * 64
            _write(fixture.human, human)

            with self.assertRaisesRegex(ValueError, "human review"):
                fixture.build()

    def test_release_qa_and_full_visual_scope_are_mandatory(self) -> None:
        mutations = (
            ("readability", lambda value: value.update({"status": "warnings", "release_ready": False})),
            ("layout", lambda value: value.update({"mode": "preview"})),
            ("visual", lambda value: value.update({"scope": "risk"})),
            ("visual", lambda value: value.update({"missing_cue_ids": ["cue-2"]})),
        )
        for target, mutate in mutations:
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="firered-subtitle-qa-gate-"
            ) as tmp:
                fixture = _ApprovalFixture(Path(tmp))
                path = getattr(fixture, target)
                document = json.loads(path.read_text(encoding="utf-8"))
                mutate(document)
                _write(path, document)
                with self.assertRaises(ValueError):
                    fixture.build()

    def test_content_timing_position_style_and_every_qa_hash_invalidate_approval(self) -> None:
        mutations = (
            "text",
            "timing",
            "position",
            "style",
            "readability",
            "layout",
            "visual",
            "human",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(
                prefix="firered-subtitle-stale-"
            ) as tmp:
                fixture = _ApprovalFixture(Path(tmp))
                fixture.build()
                style = fixture.style
                if mutation in {"text", "timing", "position"}:
                    source = json.loads(fixture.source.read_text(encoding="utf-8"))
                    if mutation == "text":
                        source["cues"][0]["text"] = "changed"
                    elif mutation == "timing":
                        source["cues"][0]["end_sec"] = 2.1
                    else:
                        source["cues"][0]["position"] = "top_center"
                    _write(fixture.source, source)
                elif mutation == "style":
                    style = {**fixture.style, "font_size": 65}
                else:
                    path = getattr(fixture, mutation)
                    document = json.loads(path.read_text(encoding="utf-8"))
                    document["tampered_for_test"] = True
                    _write(path, document)
                result = fixture.validate(style=style)
                self.assertEqual(result["status"], "blocked")

    def test_unknown_human_and_approval_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-unknown-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))
            human = json.loads(fixture.human.read_text(encoding="utf-8"))
            human["unknown"] = True
            _write(fixture.human, human)
            with self.assertRaisesRegex(ValueError, "human review"):
                fixture.build()

            fixture.refresh_qa_and_human()
            fixture.build()
            approval = json.loads(fixture.approval.read_text(encoding="utf-8"))
            approval["unknown"] = True
            _write(fixture.approval, approval)
            self.assertEqual(fixture.validate()["status"], "blocked")

    def test_unknown_layout_and_visual_fields_fail_closed(self) -> None:
        for target in ("layout", "visual"):
            with self.subTest(target=target), tempfile.TemporaryDirectory(
                prefix="firered-subtitle-unknown-qa-"
            ) as tmp:
                fixture = _ApprovalFixture(Path(tmp))
                path = getattr(fixture, target)
                document = json.loads(path.read_text(encoding="utf-8"))
                document["unknown_contract_field"] = True
                _write(path, document)

                with self.assertRaisesRegex(ValueError, rf"{target} QA schema invalid"):
                    fixture.build()
                self.assertFalse(fixture.approval.exists())

    def test_ready_source_is_created_only_from_valid_approval(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-ready-") as tmp:
            fixture = _ApprovalFixture(Path(tmp))
            approval = fixture.build()

            ready = create_ready_subtitle_source(
                review_source_path=fixture.source,
                approval_path=fixture.approval,
                output_path=fixture.ready,
            )

            self.assertEqual(ready["status"], "ready")
            self.assertEqual(ready["document_type"], "subtitle_ready_source")
            self.assertEqual(ready["cues"], fixture.source_document["cues"])
            self.assertEqual(ready["approval"]["approval_sha256"], _sha(fixture.approval))
            self.assertEqual(
                ready["approval"]["subtitle_payload_sha256"],
                approval["subtitle_payload_sha256"],
            )
            self.assertFalse(fixture.ready.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(
                fixture.validate(source=fixture.ready)["status"],
                "passed",
            )

            tampered = copy.deepcopy(approval)
            tampered["subtitle_payload_sha256"] = "0" * 64
            _write(fixture.approval, tampered)
            second_output = fixture.ready.with_name("must-not-exist.json")
            with self.assertRaises(ValueError):
                create_ready_subtitle_source(
                    review_source_path=fixture.source,
                    approval_path=fixture.approval,
                    output_path=second_output,
                )
            self.assertFalse(second_output.exists())


if __name__ == "__main__":
    unittest.main()
