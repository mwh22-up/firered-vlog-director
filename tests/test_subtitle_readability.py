from __future__ import annotations

import copy
import json
import math
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.subtitle_readability import (
    SubtitleReadabilityPolicy,
    audit_subtitle_readability,
    canonical_subtitle_payload_digest,
    canonical_subtitle_style_digest,
    canonical_verified_cue_set_digest,
    plan_safe_readability_repairs,
    select_high_risk_cue_ids,
    stable_cue_id,
    stable_cue_identity,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FORMAL_SCHEMA = REPOSITORY_ROOT / "schemas" / "subtitle-readability-qa.schema.json"
RUNTIME_SCHEMA = (
    REPOSITORY_ROOT
    / "src"
    / "vlog_director"
    / "schemas"
    / "subtitle-readability-qa.schema.json"
)


def _cue(
    cue_id: str,
    start: float,
    end: float,
    text: str,
    *,
    segment_id: str = "segment-1",
    review_status: str = "review_required",
) -> dict:
    return {
        "cue_id": cue_id,
        "segment_id": segment_id,
        "chapter_id": "chapter-1",
        "start_sec": start,
        "end_sec": end,
        "text": text,
        "review_status": review_status,
        "risk_flags": [],
    }


def _document(cues: list[dict], *, boundaries: list[dict] | None = None) -> dict:
    if boundaries is None:
        segment_ids = list(dict.fromkeys(str(cue["segment_id"]) for cue in cues))
        boundaries = [
            {
                "segment_id": segment_id,
                "actual_start_sec": 0.0,
                "actual_end_sec": 10.0,
            }
            for segment_id in segment_ids
        ]
    return {
        "project_id": "fixture-vlog",
        "subtitle_version": 4,
        "status": "review_required",
        "coverage": {"status": "pending"},
        "segment_coverage": boundaries,
        "cues": cues,
    }


def _audit(
    document: dict,
    *,
    policy: SubtitleReadabilityPolicy | None = None,
    mode: str = "preview",
) -> dict:
    return audit_subtitle_readability(
        document,
        policy=policy,
        mode=mode,
        subtitle_source_sha256="a" * 64,
        realized_timeline_sha256="b" * 64,
    )


class SubtitleReadabilityPolicyTests(unittest.TestCase):
    def test_policy_is_versioned_serializable_and_rejects_unknown_fields(self) -> None:
        policy = SubtitleReadabilityPolicy()

        payload = policy.to_dict()

        self.assertEqual(payload["policy_version"], "1.0")
        self.assertEqual(
            SubtitleReadabilityPolicy.from_dict(payload),
            policy,
        )
        with self.assertRaisesRegex(ValueError, "unknown policy fields"):
            SubtitleReadabilityPolicy.from_dict({**payload, "surprise": 1})

    def test_policy_numbers_fail_closed(self) -> None:
        invalid_cases = (
            {"min_duration_sec": True},
            {"min_duration_sec": math.nan},
            {"max_duration_sec": math.inf},
            {"min_gap_sec": -0.01},
            {"zh_max_chars_per_sec": 0},
            {"latin_max_words_per_sec": -1},
            {"max_lines": True},
            {"max_chars_per_line": 0},
            {"allow_auto_merge": 1},
            {"allow_safe_extension": 0},
        )
        for values in invalid_cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                SubtitleReadabilityPolicy(**values)

    def test_policy_rejects_conflicting_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_duration_sec"):
            SubtitleReadabilityPolicy(
                min_duration_sec=6.0,
                max_duration_sec=5.0,
            )
        with self.assertRaisesRegex(ValueError, "min_gap_sec"):
            SubtitleReadabilityPolicy(
                min_gap_sec=6.0,
                max_duration_sec=5.0,
            )


class SubtitleReadabilityAuditTests(unittest.TestCase):
    def test_short_cue_warns_in_preview_and_blocks_release(self) -> None:
        document = _document([_cue("brief", 1.0, 1.081, "好")])

        preview = _audit(document, mode="preview")
        release = _audit(document, mode="release")

        self.assertEqual(preview["status"], "warnings")
        self.assertFalse(preview["release_ready"])
        # blocker_count counts distinct blocker entries, not only affected cues.
        self.assertEqual(preview["blocker_count"], 2)
        self.assertIn(
            "duration_below_minimum",
            preview["cues"][0]["blocker_codes"],
        )
        self.assertEqual(release["status"], "blocked")
        self.assertFalse(release["release_ready"])
        self.assertEqual(select_high_risk_cue_ids(preview), ["brief"])

    def test_language_aware_metrics_ignore_punctuation_and_spaces(self) -> None:
        document = _document(
            [
                _cue("zh", 0.0, 1.0, "你，好！  "),
                _cue("latin", 2.0, 3.0, "hello, world!"),
                _cue("mixed", 4.0, 4.5, "你好, hello world!"),
            ]
        )

        report = _audit(document)
        cues = {cue["cue_id"]: cue for cue in report["cues"]}

        self.assertEqual(cues["zh"]["visible_char_count"], 2)
        self.assertEqual(cues["zh"]["zh_visible_char_count"], 2)
        self.assertEqual(cues["zh"]["zh_chars_per_sec"], 2.0)
        self.assertEqual(cues["latin"]["latin_word_count"], 2)
        self.assertEqual(cues["latin"]["latin_words_per_sec"], 2.0)
        self.assertEqual(cues["latin"]["latin_visible_char_count"], 10)
        self.assertEqual(cues["mixed"]["zh_chars_per_sec"], 4.0)
        self.assertEqual(cues["mixed"]["latin_words_per_sec"], 4.0)
        self.assertIn(
            "latin_reading_speed_exceeded",
            cues["mixed"]["blocker_codes"],
        )

    def test_overlap_gap_and_cut_proximity_are_measured_after_sorting(self) -> None:
        document = _document(
            [
                _cue("second", 0.95, 1.6, "第二句"),
                _cue("first", 0.1, 1.0, "第一句"),
            ],
            boundaries=[
                {
                    "segment_id": "segment-1",
                    "actual_start_sec": 0.0,
                    "actual_end_sec": 2.0,
                }
            ],
        )

        report = _audit(document)
        first, second = report["cues"]

        self.assertEqual([first["cue_id"], second["cue_id"]], ["first", "second"])
        self.assertAlmostEqual(first["next_gap_sec"], -0.05)
        self.assertAlmostEqual(second["previous_gap_sec"], -0.05)
        self.assertIn("subtitle_overlap", first["blocker_codes"])
        self.assertIn("subtitle_overlap", second["blocker_codes"])
        self.assertTrue(first["cut_proximity"]["within_tolerance"])
        self.assertEqual(first["cut_proximity"]["nearest_boundary"], "start")

    def test_input_order_does_not_change_ids_digests_or_audit(self) -> None:
        first = {
            "segment_id": "segment-1",
            "chapter_id": "chapter-1",
            "source_id": "GX000001",
            "source_start_sec": 10.0,
            "source_end_sec": 11.0,
            "start_sec": 0.0,
            "end_sec": 1.0,
            "text": "第一句",
            "review_status": "review_required",
            "asr_provenance": {
                "analysis_source_id": "GX000001",
                "word_refs": [
                    {
                        "asr_segment_id": "asr-1",
                        "word_index": 1,
                        "source_start_sec": 10.0,
                        "source_end_sec": 11.0,
                    }
                ],
            },
        }
        second = {
            **copy.deepcopy(first),
            "source_start_sec": 12.0,
            "source_end_sec": 13.0,
            "start_sec": 2.0,
            "end_sec": 3.0,
            "text": "第二句",
        }
        second["asr_provenance"]["word_refs"][0].update(
            {"source_start_sec": 12.0, "source_end_sec": 13.0}
        )
        ordered = _document([first, second])
        reversed_document = _document([second, first])

        ordered_report = _audit(ordered)
        reversed_report = _audit(reversed_document)

        self.assertEqual(stable_cue_id(first), stable_cue_id(copy.deepcopy(first)))
        self.assertEqual(
            stable_cue_identity(first),
            stable_cue_identity(copy.deepcopy(first)),
        )
        self.assertEqual(ordered_report["cue_ids"], reversed_report["cue_ids"])
        self.assertEqual(ordered_report["cues"], reversed_report["cues"])
        self.assertEqual(
            canonical_subtitle_payload_digest(ordered),
            canonical_subtitle_payload_digest(reversed_document),
        )

    def test_content_style_and_verified_set_digests_have_expected_scope(self) -> None:
        cues = [
            _cue("one", 0.0, 1.0, "one", review_status="verified"),
            _cue("two", 2.0, 3.0, "two", review_status="verified"),
        ]
        document = _document(cues)
        changed = copy.deepcopy(document)
        changed["cues"][0]["text"] = "changed"

        self.assertNotEqual(
            canonical_subtitle_payload_digest(document),
            canonical_subtitle_payload_digest(changed),
        )
        self.assertNotEqual(
            canonical_subtitle_style_digest({"font_size": 64}),
            canonical_subtitle_style_digest({"font_size": 65}),
        )
        self.assertEqual(
            canonical_verified_cue_set_digest(cues),
            canonical_verified_cue_set_digest(list(reversed(cues))),
        )

    def test_formal_and_runtime_schemas_match_and_validate_report(self) -> None:
        formal = json.loads(FORMAL_SCHEMA.read_text(encoding="utf-8"))
        runtime = json.loads(RUNTIME_SCHEMA.read_text(encoding="utf-8"))
        report = _audit(_document([_cue("cue-1", 0.0, 1.0, "正常字幕")]))

        self.assertEqual(formal, runtime)
        Draft202012Validator.check_schema(formal)
        self.assertEqual(list(Draft202012Validator(formal).iter_errors(report)), [])


class SubtitleReadabilityRepairTests(unittest.TestCase):
    def test_short_cue_prefers_deterministic_same_segment_merge(self) -> None:
        document = _document(
            [
                _cue("brief", 0.0, 0.4, "你好"),
                _cue("next", 0.45, 1.5, "世界"),
            ]
        )

        repairs = plan_safe_readability_repairs(document)

        self.assertEqual(len(repairs), 1)
        repair = repairs[0]
        self.assertEqual(repair["type"], "merge")
        self.assertEqual(repair["target_cue_ids"], ["brief", "next"])
        self.assertEqual(repair["proposed"]["text"], "你好世界")
        self.assertTrue(repair["review_required"])

    def test_repair_never_merges_or_extends_across_edit_cut(self) -> None:
        document = _document(
            [
                _cue("left", 0.0, 0.4, "左", segment_id="segment-1"),
                _cue("right", 0.4, 1.4, "右", segment_id="segment-2"),
            ],
            boundaries=[
                {
                    "segment_id": "segment-1",
                    "actual_start_sec": 0.0,
                    "actual_end_sec": 0.4,
                },
                {
                    "segment_id": "segment-2",
                    "actual_start_sec": 0.4,
                    "actual_end_sec": 1.4,
                },
            ],
        )

        repairs = plan_safe_readability_repairs(document)

        self.assertEqual(repairs, [])
        report = _audit(document, mode="release")
        left = next(cue for cue in report["cues"] if cue["cue_id"] == "left")
        self.assertIn("duration_below_minimum", left["blocker_codes"])
        self.assertIsNone(left["proposed_repair"])

    def test_safe_extension_stops_before_next_cue_and_boundary(self) -> None:
        policy = SubtitleReadabilityPolicy(
            allow_auto_merge=False,
            min_gap_sec=0.1,
        )
        document = _document(
            [
                _cue("brief", 0.0, 0.4, "短句"),
                _cue("next", 0.9, 1.8, "下一句"),
            ],
            boundaries=[
                {
                    "segment_id": "segment-1",
                    "actual_start_sec": 0.0,
                    "actual_end_sec": 2.0,
                }
            ],
        )

        repairs = plan_safe_readability_repairs(document, policy=policy)

        self.assertEqual(len(repairs), 1)
        repair = repairs[0]
        self.assertEqual(repair["type"], "extend")
        self.assertAlmostEqual(repair["proposed"]["end_sec"], 0.8)
        self.assertLessEqual(
            repair["proposed"]["end_sec"],
            document["cues"][1]["start_sec"] - policy.min_gap_sec,
        )

    def test_merge_that_exceeds_line_duration_or_speed_limits_is_not_proposed(self) -> None:
        policy = SubtitleReadabilityPolicy(
            min_duration_sec=0.8,
            max_duration_sec=1.0,
            max_chars_per_line=3,
            max_lines=1,
            allow_safe_extension=False,
        )
        document = _document(
            [
                _cue("brief", 0.0, 0.4, "一二三"),
                _cue("next", 0.45, 1.2, "四五六"),
            ]
        )

        self.assertEqual(
            plan_safe_readability_repairs(document, policy=policy),
            [],
        )


if __name__ == "__main__":
    unittest.main()
