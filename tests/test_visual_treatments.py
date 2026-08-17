from __future__ import annotations

import copy
import hashlib
import json
import math
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.enhancement import build_enhancement_plan
from vlog_director.visual_treatments import (
    VisualTreatmentPolicy,
    build_visual_treatment_plan,
    canonical_treatment_payload_sha256,
    validate_visual_treatment_analysis,
    validate_visual_treatment_plan,
)


ROOT = Path(__file__).parents[1]
FORMAL_ANALYSIS = ROOT / "schemas" / "visual-treatment-analysis.schema.json"
RUNTIME_ANALYSIS = (
    ROOT / "src" / "vlog_director" / "schemas" / "visual-treatment-analysis.schema.json"
)
FORMAL_PLAN = ROOT / "schemas" / "visual-treatment-plan.schema.json"
RUNTIME_PLAN = ROOT / "src" / "vlog_director" / "schemas" / "visual-treatment-plan.schema.json"


def _digest(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _edit_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "visual-demo",
        "version": 4,
        "chapters": [
            {
                "id": "ch01",
                "title": "雪山抵达",
                "segments": [
                    {
                        "id": "seg-dark",
                        "source": "raw/dark.mp4",
                        "in_sec": 0.0,
                        "out_sec": 2.0,
                        "story_role": "establishing",
                    },
                    {
                        "id": "seg-normal",
                        "source": "raw/normal.mp4",
                        "in_sec": 2.0,
                        "out_sec": 4.0,
                        "story_role": "story",
                    },
                ],
            }
        ],
    }


def _metrics(*, luma: float, contrast: float, saturation: float) -> dict:
    return {
        "luma_mean": luma,
        "luma_p05": max(0.0, luma - 0.12),
        "luma_p50": luma,
        "luma_p95": min(1.0, luma + 0.12),
        "clipped_black_ratio": 0.0,
        "clipped_white_ratio": 0.0,
        "contrast_std": contrast,
        "saturation_mean": saturation,
        "rgb_means": {"red": luma, "green": luma, "blue": luma},
        "sharpness": 0.09,
        "motion": 0.03,
        "temporal_noise": 0.02,
    }


def _analysis() -> dict:
    edit_plan = _edit_plan()
    return {
        "schema_version": "1.0",
        "analysis_version": "visual-segment-analysis-v1",
        "project_id": "visual-demo",
        "edit_plan_version": 4,
        "edit_plan_sha256": _digest(edit_plan),
        "realized_timeline_sha256": "2" * 64,
        "base_media": {
            "path": "output/directed.v4.mp4",
            "sha256": "3" * 64,
            "size_bytes": 1234,
        },
        "ffmpeg_identity": "ffmpeg test build",
        "segments": [
            {
                "segment_id": "seg-dark",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "sample_times_sec": [0.4, 1.0, 1.6],
                "metrics": _metrics(luma=0.27, contrast=0.10, saturation=0.08),
                "protected_regions_available": False,
                "warning_codes": ["protected_regions_unavailable"],
            },
            {
                "segment_id": "seg-normal",
                "start_sec": 2.0,
                "end_sec": 4.0,
                "sample_times_sec": [2.4, 3.0, 3.6],
                "metrics": _metrics(luma=0.50, contrast=0.22, saturation=0.30),
                "protected_regions_available": False,
                "warning_codes": ["protected_regions_unavailable"],
            },
        ],
    }


class VisualTreatmentTests(unittest.TestCase):
    def test_new_enhancement_plans_disable_music_by_default(self) -> None:
        plan = build_enhancement_plan(_edit_plan())
        self.assertEqual(plan["music"]["status"], "disabled")
        self.assertEqual(plan["music"]["tracks"], [])
        self.assertFalse(plan["music"]["ducking"]["enabled"])

    def test_analysis_and_plan_schemas_are_formal_runtime_identical(self) -> None:
        self.assertEqual(FORMAL_ANALYSIS.read_bytes(), RUNTIME_ANALYSIS.read_bytes())
        self.assertEqual(FORMAL_PLAN.read_bytes(), RUNTIME_PLAN.read_bytes())
        analysis_schema = json.loads(FORMAL_ANALYSIS.read_text(encoding="utf-8"))
        plan_schema = json.loads(FORMAL_PLAN.read_text(encoding="utf-8"))
        analysis = _analysis()
        plan = build_visual_treatment_plan(
            _edit_plan(),
            analysis,
            analysis_path="work/analysis/visual/analysis.v4.json",
            analysis_sha256=_digest(analysis),
        )
        self.assertEqual(list(Draft202012Validator(analysis_schema).iter_errors(analysis)), [])
        self.assertEqual(list(Draft202012Validator(plan_schema).iter_errors(plan)), [])

    def test_planner_is_deterministic_allowlisted_and_never_invents_reframe(self) -> None:
        analysis = _analysis()
        plan = build_visual_treatment_plan(
            _edit_plan(),
            analysis,
            analysis_path="work/analysis/visual/analysis.v4.json",
            analysis_sha256=_digest(analysis),
        )
        reversed_analysis = copy.deepcopy(analysis)
        reversed_analysis["segments"].reverse()
        reordered = build_visual_treatment_plan(
            _edit_plan(),
            reversed_analysis,
            analysis_path="work/analysis/visual/analysis.v4.json",
            analysis_sha256=_digest(reversed_analysis),
        )

        proposals = {row["segment_id"]: row for row in plan["proposals"]}
        self.assertGreater(proposals["seg-dark"]["changes"]["brightness"], 0)
        self.assertGreater(proposals["seg-dark"]["changes"]["contrast"], 1)
        self.assertGreater(proposals["seg-dark"]["changes"]["saturation"], 1)
        self.assertNotIn("reframe", proposals["seg-dark"]["changes"])
        self.assertNotIn("speed", proposals["seg-dark"]["changes"])
        self.assertTrue(all(row["status"] == "review_required" for row in plan["proposals"]))
        self.assertEqual(
            [row["proposal_id"] for row in plan["proposals"]],
            [row["proposal_id"] for row in reordered["proposals"]],
        )
        self.assertEqual(
            canonical_treatment_payload_sha256(plan),
            plan["treatment_payload_sha256"],
        )

    def test_non_finite_or_mismatched_analysis_fails_closed(self) -> None:
        analysis = _analysis()
        analysis["segments"][0]["metrics"]["luma_mean"] = math.nan
        invalid = validate_visual_treatment_analysis(_edit_plan(), analysis)
        self.assertEqual(invalid["status"], "blocked")
        self.assertIn("visual_analysis_schema_invalid", invalid["blocker_codes"])

        analysis = _analysis()
        analysis["base_media"]["sha256"] = "f" * 64
        plan = build_visual_treatment_plan(
            _edit_plan(),
            analysis,
            analysis_path="work/analysis/visual/analysis.v4.json",
            analysis_sha256=_digest(analysis),
        )
        changed = copy.deepcopy(_edit_plan())
        changed["chapters"][0]["segments"][0]["out_sec"] = 1.8
        validation = validate_visual_treatment_plan(changed, analysis, plan)
        self.assertEqual(validation["status"], "blocked")
        self.assertIn("visual_plan_edit_sha_mismatch", validation["blocker_codes"])

    def test_neutral_segments_produce_a_valid_no_change_plan(self) -> None:
        analysis = _analysis()
        analysis["segments"][0]["metrics"] = _metrics(
            luma=0.50,
            contrast=0.22,
            saturation=0.30,
        )
        plan = build_visual_treatment_plan(
            _edit_plan(),
            analysis,
            analysis_path="work/analysis/visual/analysis.v4.json",
            analysis_sha256=_digest(analysis),
        )
        self.assertEqual(plan["proposals"], [])

    def test_policy_rejects_bool_nan_infinity_and_conflicting_thresholds(self) -> None:
        for field, value in (
            ("luma_target", True),
            ("luma_target", math.nan),
            ("luma_target", math.inf),
            ("max_brightness_adjustment", -0.1),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    VisualTreatmentPolicy(**{field: value})
        with self.assertRaises(ValueError):
            VisualTreatmentPolicy(luma_dark_threshold=0.6, luma_bright_threshold=0.5)


if __name__ == "__main__":
    unittest.main()
