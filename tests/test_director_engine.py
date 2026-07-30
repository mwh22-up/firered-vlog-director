import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.director_engine import build_candidate, direct_timeline, write_director_result


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
