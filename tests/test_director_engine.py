import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.director_engine import (
    _build_opening_hook,
    build_candidate,
    direct_timeline,
    write_director_result,
)
from vlog_director.technique_policy import build_technique_policy


def segment(source: str, start: float, end: float, role: str = "story") -> dict:
    return {
        "source": source,
        "in_sec": start,
        "out_sec": end,
        "story_role": role,
        "reason": "parent story skeleton",
        "keep_original_audio": True,
        "beat_snap": False,
        "confidence": 0.8,
    }


def parent_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "demo",
        "version": 1,
        "parent_version": None,
        "brief": {
            "target_duration_sec": 10.0,
            "aspect_ratio": "16:9",
            "mode": "timeline",
            "keep_dialogue": True,
        },
        "chapters": [
            {
                "id": "ch01",
                "title": "Arrival",
                "target_duration_sec": 10.0,
                "segments": [segment("raw/A001.MP4", 0.0, 10.0)],
            }
        ],
        "music": [],
        "qa": [],
        "created_at": "2026-07-30T00:00:00+08:00",
    }


def target_analysis() -> dict:
    return {
        "source": {
            "source_id": "A001",
            "aliases": ["raw/A001.MP4", "A001.MP4"],
        },
        "transcription": {
            "status": "ready",
            "segments": [
                {"start_sec": 0.0, "end_sec": 2.0, "text": "we arrived"}
            ],
        },
        "shots": [
            {
                "shot_id": "shot-1",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "role": "dialogue",
                "speech_ratio": 0.9,
                "novelty_score": 0.8,
                "quality_score": 0.9,
                "keep_score": 0.92,
                "recommendation": "protect",
            },
            {
                "shot_id": "shot-2",
                "start_sec": 2.0,
                "end_sec": 6.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 0.01,
                "quality_score": 0.25,
                "keep_score": 0.2,
                "recommendation": "cut_first",
            },
            {
                "shot_id": "shot-3",
                "start_sec": 6.0,
                "end_sec": 10.0,
                "role": "action",
                "speech_ratio": 0.0,
                "novelty_score": 0.8,
                "quality_score": 0.9,
                "keep_score": 0.9,
                "recommendation": "protect",
            },
        ],
        "events": [
            {
                "event_id": "event-1",
                "start_sec": 0.0,
                "end_sec": 10.0,
                "event_type": "activity",
                "priority_score": 0.9,
                "completeness_score": 0.75,
                "recommendation": "protect",
                "key_shot_ids": ["shot-1", "shot-3"],
                "sequence_dependency": {
                    "setup_shot_id": "shot-1",
                    "payoff_shot_id": "shot-3",
                    "reaction_shot_id": None,
                },
            }
        ],
    }


PROFILE = {
    "profile_id": "reference-profile",
    "shot_selection_model": {
        "retain_archetypes": [
            {"role": "dialogue", "average_retained_ratio": 0.98},
            {"role": "action", "average_retained_ratio": 0.65},
        ],
        "selective_archetypes": [],
    },
}
MOMENTS = {"moments": [], "groups": []}


def technique_aggregate(*patterns: tuple[str, str]) -> dict:
    source_ids = ["reference-a", "reference-b"]
    stable_patterns = []
    for index, (technique_key, category) in enumerate(patterns, start=1):
        stable_patterns.append(
            {
                "technique_key": technique_key,
                "category": category,
                "source_support": 2,
                "source_ids": source_ids,
                "average_confidence": 0.95,
                "trigger_examples": ["target evidence is required"],
                "treatment_examples": ["apply only through the allowlisted executor"],
                "parameter_variants": [
                    {"source_id": source_id} for source_id in source_ids
                ],
                "guardrail_variants": [],
                "evidence_ranges": [
                    {
                        "source_id": source_id,
                        "start_sec": float(index),
                        "end_sec": float(index + 1),
                        "observation_id": f"obs-{index}-{source_index}",
                    }
                    for source_index, source_id in enumerate(source_ids, start=1)
                ],
            }
        )
    return {
        "schema_version": "1.0",
        "profile_id": "test-techniques-v1",
        "source_count": 2,
        "source_ids": source_ids,
        "minimum_source_support": 2,
        "stable_patterns": stable_patterns,
        "source_specific_patterns": [],
        "opening_recipes": [],
        "model_context_policy": {
            "default_maximum_characters": 180000,
            "hard_limit_characters": 200000,
            "comparison": "strictly_less_than",
        },
        "limitations": ["positive retained patterns only"],
    }


def optional_fun_moments(fun_score: float) -> dict:
    return {
        "moments": [
            {
                "id": "moment_awkward_process",
                "source": "raw/A001.MP4",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "types": ["humor", "awkward_charm"],
                "importance_score": 1.0,
                "fun_score": fun_score,
                "quality_score": 0.7,
                "confidence": 1.0,
                "keep_level": "optional",
                "reason": "explicit target-footage review signal",
                "evidence": [
                    {"type": "visual", "value": "reviewed awkward interaction"}
                ],
            }
        ],
        "groups": [],
    }


class DirectorEngineTests(unittest.TestCase):
    def test_missing_target_analysis_blocks_instead_of_copying_parent(self) -> None:
        result = direct_timeline(
            parent_plan(),
            [],
            PROFILE,
            MOMENTS,
            version=2,
            created_at="2026-07-30T01:00:00+08:00",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "target_analysis_missing")
        self.assertEqual(result["missing_sources"], ["raw/A001.MP4"])

    def test_target_analysis_produces_changed_scored_candidates(self) -> None:
        result = direct_timeline(
            parent_plan(),
            [target_analysis()],
            PROFILE,
            MOMENTS,
            version=2,
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=6.0,
        )
        self.assertEqual(result["status"], "review_required")
        self.assertIn(result["recommended_variant"], {"concise", "balanced", "immersive"})
        selected = result["recommended_plan"]
        self.assertEqual(selected["parent_version"], 1)
        self.assertEqual(selected["version"], 2)
        self.assertEqual(selected["brief"]["target_duration_sec"], 6.0)
        ranges = [
            (item["in_sec"], item["out_sec"])
            for item in selected["chapters"][0]["segments"]
        ]
        self.assertEqual(ranges, [(0.0, 2.0), (6.0, 10.0)])
        self.assertTrue(all(c["evaluation"]["revision"]["change_ratio"] > 0 for c in result["candidates"]))

    def test_reference_profile_priors_change_shot_selection(self) -> None:
        analysis = target_analysis()
        analysis["shots"].append(
            {
                "shot_id": "shot-detail",
                "start_sec": 2.0,
                "end_sec": 4.0,
                "role": "detail",
                "speech_ratio": 0.0,
                "novelty_score": 0.5,
                "quality_score": 0.5,
                "keep_score": 0.5,
                "recommendation": "retain",
            }
        )
        analyses = {"raw/A001.MP4": analysis}
        low_prior = {
            "profile_id": "low-detail",
            "shot_selection_model": {
                "retain_archetypes": [],
                "selective_archetypes": [
                    {"role": "detail", "average_retained_ratio": 0.05}
                ],
            },
        }
        high_prior = {
            "profile_id": "high-detail",
            "shot_selection_model": {
                "retain_archetypes": [
                    {"role": "detail", "average_retained_ratio": 0.95}
                ],
                "selective_archetypes": [],
            },
        }
        low_plan, _ = build_candidate(
            parent_plan(), analyses, low_prior, MOMENTS,
            version=2, variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
        )
        high_plan, _ = build_candidate(
            parent_plan(), analyses, high_prior, MOMENTS,
            version=2, variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
        )
        low_ranges = {
            (item["in_sec"], item["out_sec"])
            for item in low_plan["chapters"][0]["segments"]
        }
        high_ranges = {
            (item["in_sec"], item["out_sec"])
            for item in high_plan["chapters"][0]["segments"]
        }
        self.assertFalse(any(start <= 3.0 < end for start, end in low_ranges))
        self.assertTrue(any(start <= 3.0 < end for start, end in high_ranges))


    def test_content_directions_choose_different_target_shots(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        plan["brief"]["target_duration_sec"] = 6.0
        plan["chapters"][0]["target_duration_sec"] = 6.0
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "scenic",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.65,
                    "recommendation": "retain",
                    "scenic_score": 0.95,
                    "fun_score": 0.0,
                },
                {
                    "shot_id": "fun",
                    "start_sec": 2.0,
                    "end_sec": 4.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.65,
                    "recommendation": "retain",
                    "scenic_score": 0.0,
                    "fun_score": 0.95,
                },
                {
                    "shot_id": "weak",
                    "start_sec": 4.0,
                    "end_sec": 6.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.05,
                    "quality_score": 0.2,
                    "keep_score": 0.2,
                    "recommendation": "cut_first",
                },
            ],
            "events": [],
        }
        analyses = {"raw/A001.MP4": analysis}
        fun_plan, fun_report = build_candidate(
            plan,
            analyses,
            PROFILE,
            MOMENTS,
            version=2,
            variant="concise",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=4.0,
        )
        scenic_plan, scenic_report = build_candidate(
            plan,
            analyses,
            PROFILE,
            MOMENTS,
            version=2,
            variant="immersive",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=4.0,
        )
        fun_ranges = [
            (item["in_sec"], item["out_sec"])
            for item in fun_plan["chapters"][0]["segments"]
        ]
        scenic_ranges = [
            (item["in_sec"], item["out_sec"])
            for item in scenic_plan["chapters"][0]["segments"]
        ]
        self.assertEqual(fun_ranges, [(2.0, 4.0)])
        self.assertEqual(scenic_ranges, [(0.0, 2.0)])
        self.assertEqual(fun_report["content_direction"], "fun_forward")
        self.assertEqual(scenic_report["content_direction"], "scenic_forward")

    def test_explicit_user_feedback_overrides_reference_direction(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = target_analysis()
        analysis["transcription"] = {"status": "disabled", "segments": []}
        analysis["events"] = []
        analysis["shots"] = [
            {
                "shot_id": "scenic",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 0.8,
                "quality_score": 0.7,
                "keep_score": 0.65,
                "recommendation": "retain",
                "scenic_score": 0.95,
                "fun_score": 0.0,
            },
            {
                "shot_id": "fun",
                "start_sec": 2.0,
                "end_sec": 4.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 0.8,
                "quality_score": 0.7,
                "keep_score": 0.65,
                "recommendation": "retain",
                "scenic_score": 0.0,
                "fun_score": 0.95,
            },
        ]
        feedback = {
            "shot_feedback": [
                {
                    "id": "keep-scenic",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": "lock",
                    "confidence": 1.0,
                },
                {
                    "id": "remove-fun",
                    "source": "raw/A001.MP4",
                    "start_sec": 2.0,
                    "end_sec": 4.0,
                    "decision": "remove",
                    "confidence": 1.0,
                },
            ]
        }
        candidate, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            MOMENTS,
            version=2,
            variant="concise",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            feedback_document=feedback,
        )
        ranges = [
            (item["in_sec"], item["out_sec"])
            for item in candidate["chapters"][0]["segments"]
        ]
        self.assertEqual(ranges, [(0.0, 2.0)])
        self.assertIn("user_feedback:keep-scenic:lock", candidate["chapters"][0]["segments"][0]["reason"])

    def test_technique_profile_without_target_evidence_does_not_change_edl(self) -> None:
        aggregate = technique_aggregate(
            ("humor-preserve-real-awkward-process", "humor"),
            ("narrative-failure-adaptation-payoff", "narrative"),
            ("graphic-inline-reference-card-over-live-scene", "graphic"),
        )
        baseline = direct_timeline(
            parent_plan(),
            [target_analysis()],
            PROFILE,
            MOMENTS,
            version=2,
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=6.0,
        )
        learned = direct_timeline(
            parent_plan(),
            [target_analysis()],
            PROFILE,
            MOMENTS,
            version=2,
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=6.0,
            technique_profile=aggregate,
        )

        self.assertEqual(
            [candidate["plan"] for candidate in learned["candidates"]],
            [candidate["plan"] for candidate in baseline["candidates"]],
        )
        self.assertEqual(
            learned["technique_application"]["applied_patterns"],
            [],
        )
        self.assertEqual(
            {
                row["technique_key"]
                for row in learned["technique_application"]["eligible_patterns"]
            },
            {
                "humor-preserve-real-awkward-process",
            },
        )
        self.assertEqual(
            [
                row["technique_key"]
                for row in learned["technique_application"]["guidance_patterns"]
            ],
            [
                "graphic-inline-reference-card-over-live-scene",
                "narrative-failure-adaptation-payoff",
            ],
        )

    def test_fun_evidence_can_select_a_borderline_shot_with_trace(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "awkward-process",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.58,
                    "recommendation": "retain",
                }
            ],
            "events": [],
        }
        policy = build_technique_policy(
            technique_aggregate(
                ("humor-preserve-real-awkward-process", "humor"),
            )
        )
        baseline, baseline_report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            optional_fun_moments(0.8),
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
        )
        learned, learned_report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            optional_fun_moments(0.8),
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            technique_policy=policy,
        )

        self.assertEqual(baseline["chapters"][0]["segments"], [])
        self.assertEqual(
            [
                (row["in_sec"], row["out_sec"])
                for row in learned["chapters"][0]["segments"]
            ],
            [(0.0, 2.0)],
        )
        self.assertEqual(
            baseline_report["technique_application"]["applied_patterns"],
            [],
        )
        applied = learned_report["technique_application"]["applied_patterns"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(
            applied[0]["technique_key"],
            "humor-preserve-real-awkward-process",
        )
        self.assertEqual(applied[0]["affected_target_count"], 1)
        self.assertIn(
            "moment:moment_awkward_process:fun_score=0.8000",
            applied[0]["target_evidence"],
        )

    def test_user_remove_overrides_fun_technique(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "awkward-process",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.58,
                    "recommendation": "retain",
                }
            ],
            "events": [],
        }
        feedback = {
            "shot_feedback": [
                {
                    "id": "remove-awkward-process",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": "remove",
                    "confidence": 1.0,
                }
            ]
        }
        learned, report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            optional_fun_moments(0.8),
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            technique_policy=build_technique_policy(
                technique_aggregate(
                    ("humor-preserve-real-awkward-process", "humor"),
                )
            ),
            feedback_document=feedback,
        )

        self.assertEqual(learned["chapters"][0]["segments"], [])
        self.assertEqual(report["technique_application"]["applied_patterns"], [])

    def test_derived_fun_signal_does_not_trigger_technique(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "derived-humor-only",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.58,
                    "recommendation": "retain",
                }
            ],
            "events": [],
        }
        learned, report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            optional_fun_moments(0.0),
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            technique_policy=build_technique_policy(
                technique_aggregate(
                    ("humor-preserve-real-awkward-process", "humor"),
                )
            ),
        )

        self.assertEqual(learned["chapters"][0]["segments"], [])
        self.assertEqual(report["technique_application"]["applied_patterns"], [])

    def test_fun_technique_does_not_reorder_already_selected_shots(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        plan["brief"]["target_duration_sec"] = 2.0
        plan["chapters"][0]["target_duration_sec"] = 2.0
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "fun-process",
                    "start_sec": 0.0,
                    "end_sec": 1.9,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.8,
                    "keep_score": 0.7,
                    "recommendation": "retain",
                },
                {
                    "shot_id": "slightly-stronger",
                    "start_sec": 2.1,
                    "end_sec": 4.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.8,
                    "keep_score": 0.99,
                    "recommendation": "retain",
                },
            ],
            "events": [],
        }
        moments = optional_fun_moments(0.8)
        moments["moments"][0]["end_sec"] = 1.9
        baseline, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            moments,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
        )
        learned, report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            moments,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            technique_policy=build_technique_policy(
                technique_aggregate(
                    ("humor-preserve-real-awkward-process", "humor"),
                )
            ),
        )

        self.assertEqual(learned["chapters"], baseline["chapters"])
        self.assertEqual(report["technique_application"]["applied_patterns"], [])

    def test_fun_technique_does_not_report_existing_protected_coverage(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = {
            "source": target_analysis()["source"],
            "transcription": {"status": "disabled", "segments": []},
            "shots": [
                {
                    "shot_id": "already-protected",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "role": "ambient",
                    "speech_ratio": 0.0,
                    "novelty_score": 0.8,
                    "quality_score": 0.7,
                    "keep_score": 0.58,
                    "recommendation": "retain",
                }
            ],
            "events": [],
        }
        moments = optional_fun_moments(0.8)
        moments["moments"].append(
            {
                "id": "existing-protection",
                "source": "raw/A001.MP4",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "keep_level": "protected",
            }
        )
        baseline, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            moments,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
        )
        learned, report = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            moments,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            technique_policy=build_technique_policy(
                technique_aggregate(
                    ("humor-preserve-real-awkward-process", "humor"),
                )
            ),
        )

        self.assertEqual(learned["chapters"], baseline["chapters"])
        self.assertEqual(report["technique_application"]["applied_patterns"], [])

    def test_user_lock_overrides_cut_first_without_technique(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = target_analysis()
        analysis["transcription"] = {"status": "disabled", "segments": []}
        analysis["events"] = []
        analysis["shots"] = [
            {
                "shot_id": "locked-cut-first",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 0.0,
                "quality_score": 0.1,
                "keep_score": 0.1,
                "recommendation": "cut_first",
            }
        ]
        feedback = {
            "shot_feedback": [
                {
                    "id": "lock-cut-first",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": "lock",
                    "confidence": 1.0,
                }
            ]
        }

        candidate, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            MOMENTS,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            feedback_document=feedback,
        )

        self.assertEqual(
            [
                (row["in_sec"], row["out_sec"])
                for row in candidate["chapters"][0]["segments"]
            ],
            [(0.0, 2.0)],
        )

    def test_user_remove_wins_conflicting_lock(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = target_analysis()
        analysis["transcription"] = {"status": "disabled", "segments": []}
        analysis["events"] = []
        analysis["shots"] = [
            {
                "shot_id": "conflicting-feedback",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 1.0,
                "quality_score": 1.0,
                "keep_score": 1.0,
                "recommendation": "protect",
            }
        ]
        feedback = {
            "shot_feedback": [
                {
                    "id": decision,
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": decision,
                    "confidence": 1.0,
                }
                for decision in ("lock", "remove")
            ]
        }

        candidate, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            MOMENTS,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            feedback_document=feedback,
        )

        self.assertEqual(candidate["chapters"][0]["segments"], [])

    def test_user_remove_overrides_protected_moment_and_event_dependency(self) -> None:
        plan = parent_plan()
        plan["brief"]["keep_dialogue"] = False
        analysis = target_analysis()
        analysis["transcription"] = {"status": "disabled", "segments": []}
        analysis["shots"] = [
            {
                "shot_id": "protected-shot",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "role": "ambient",
                "speech_ratio": 0.0,
                "novelty_score": 1.0,
                "quality_score": 1.0,
                "keep_score": 1.0,
                "recommendation": "protect",
            }
        ]
        analysis["events"] = [
            {
                "event_id": "protected-event",
                "event_type": "activity",
                "recommendation": "protect",
                "key_shot_ids": ["protected-shot"],
                "sequence_dependency": {"setup_shot_id": "protected-shot"},
            }
        ]
        moments = {
            "moments": [
                {
                    "id": "protected-moment",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "keep_level": "protected",
                }
            ],
            "groups": [],
        }
        feedback = {
            "shot_feedback": [
                {
                    "id": "remove-protected",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": "remove",
                    "confidence": 1.0,
                }
            ]
        }

        candidate, _ = build_candidate(
            plan,
            {"raw/A001.MP4": analysis},
            PROFILE,
            moments,
            version=2,
            variant="balanced",
            created_at="2026-07-30T01:00:00+08:00",
            target_duration_sec=2.0,
            feedback_document=feedback,
        )

        self.assertEqual(candidate["chapters"][0]["segments"], [])

    def test_opening_hook_skips_user_removed_shots(self) -> None:
        chapters = []
        analyses = {}
        for index in range(3):
            source = f"raw/A{index + 1:03d}.MP4"
            chapters.append(
                {
                    "id": f"ch{index + 1:02d}",
                    "title": f"Chapter {index + 1}",
                    "segments": [segment(source, 0.0, 2.0)],
                }
            )
            analyses[source] = {
                "shots": [
                    {
                        "shot_id": f"opening-{index + 1}",
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "role": "action",
                        "speech_ratio": 0.0,
                        "keep_score": 0.95,
                        "quality_score": 0.95,
                        "novelty_score": 0.95,
                    }
                ]
            }

        self.assertIsNotNone(_build_opening_hook(chapters, analyses))
        feedback = {
            "shot_feedback": [
                {
                    "id": "remove-opening",
                    "source": "raw/A001.MP4",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "decision": "remove",
                    "confidence": 1.0,
                }
            ]
        }
        self.assertIsNone(
            _build_opening_hook(
                chapters,
                analyses,
                feedback_document=feedback,
            )
        )

    def test_outputs_are_written_as_reviewable_edl_artifacts(self) -> None:
        result = direct_timeline(
            parent_plan(),
            [target_analysis()],
            PROFILE,
            MOMENTS,
            version=2,
            created_at="2026-07-30T01:00:00+08:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_director_result(result, output)
            self.assertTrue((output / "director_report.json").is_file())
            self.assertTrue((output / "target_semantic_view.md").is_file())
            selected = json.loads((output / "edit_plan.recommended.json").read_text(encoding="utf-8"))
            self.assertEqual(selected["version"], 2)
            self.assertTrue((output / "candidate.concise.json").is_file())
            self.assertTrue((output / "cut_review_manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
