import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.enhancement import (
    RENDER_STAGES,
    build_enhancement_plan,
    validate_enhancement_plan,
)

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = Path(__file__).parents[1] / "schemas" / "enhancement-plan.schema.json"


def load_edit_plan() -> dict:
    return json.loads((FIXTURES / "edit_plan.valid.json").read_text(encoding="utf-8"))


class EnhancementTests(unittest.TestCase):
    def test_build_plan_covers_every_segment(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)

        self.assertEqual(plan["render_stages"], RENDER_STAGES)
        self.assertEqual(plan["timeline_duration_sec"], 22.0)
        self.assertEqual(len(plan["video_treatments"]), 2)
        validation = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(validation["status"], "passed")

    def test_build_plan_matches_formal_schema(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(plan))

        self.assertEqual(errors, [])

    def test_ready_music_track_is_validated_as_executable(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"]["status"] = "ready"
        plan["music"]["tracks"] = [
            {
                "id": "music-01",
                "source": "assets/music/bed.wav",
                "start_sec": 2.0,
                "end_sec": 8.0,
                "gain_db": -22.0,
                "fade_in_sec": 1.0,
                "fade_out_sec": 1.0,
            }
        ]
        self.assertEqual(validate_enhancement_plan(edit_plan, plan)["status"], "passed")

        plan["music"]["tracks"][0]["fade_out_sec"] = 8.0
        result = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("invalid_music_fades", {issue["code"] for issue in result["issues"]})

    def test_formal_schema_is_a_runtime_gate(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        del plan["schema_version"]

        result = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "enhancement_schema_invalid",
            {issue["code"] for issue in result["issues"]},
        )

        plan = build_enhancement_plan(edit_plan)
        plan["music"]["status"] = "ready"
        plan["music"]["tracks"] = [
            {
                "id": "missing-gain",
                "source": "assets/music/bed.wav",
                "start_sec": 1.0,
                "end_sec": 2.0,
            }
        ]
        result = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "enhancement_schema_invalid",
            {issue["code"] for issue in result["issues"]},
        )

    def test_ffmpeg_ducking_ranges_are_enforced_by_schema(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"]["ducking"]["attack_ms"] = 0

        result = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "enhancement_schema_invalid",
            {issue["code"] for issue in result["issues"]},
        )

    def test_legacy_advisory_music_plan_is_migrated(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"] = {
            "status": "reference_pending",
            "mode": "manual_capcut_reference",
            "non_blocking": True,
            "recommendations": [],
            "tracks": [],
        }

        result = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(result["status"], "passed")
        self.assertIn(
            "legacy_enhancement_plan_migrated",
            {issue["code"] for issue in result["issues"]},
        )

    def test_audio_removal_and_excessive_crop_block(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["video_treatments"][0]["audio"]["preserve_original"] = False
        plan["video_treatments"][0]["stabilization"]["max_crop_percent"] = 20

        result = validate_enhancement_plan(edit_plan, plan)
        codes = {issue["code"] for issue in result["issues"]}

        self.assertEqual(result["status"], "blocked")
        self.assertIn("original_audio_removed", codes)
        self.assertIn("stabilization_crop_too_large", codes)

    def test_subtitle_and_overlay_ranges_are_checked(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["cues"] = [
            {"start_sec": 21.0, "end_sec": 24.0, "text": "超出时间轴"}
        ]
        plan["illustration_motion"]["items"] = [
            {
                "id": "overlay-1",
                "type": "callout",
                "source": "assets/illustrations/callout.png",
                "start_sec": 2.0,
                "end_sec": 4.0,
                "anchor": "bottom_center",
                "animation": "pop"
            }
        ]

        result = validate_enhancement_plan(edit_plan, plan)
        codes = {issue["code"] for issue in result["issues"]}

        self.assertEqual(result["status"], "blocked")
        self.assertIn("subtitle_out_of_timeline", codes)
        self.assertIn("overlay_subtitle_conflict", codes)

    def test_review_required_subtitles_block_render(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "review_required"

        result = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "invalid_subtitle_status",
            {issue["code"] for issue in result["issues"]},
        )

    def test_ready_subtitles_require_verified_coverage_and_cues(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "ready"
        plan["subtitles"]["coverage"] = {"status": "verified"}
        plan["subtitles"]["cues"] = [
            {
                "start_sec": 1.0,
                "end_sec": 2.0,
                "text": "verified subtitle",
                "review_status": "verified",
            }
        ]

        self.assertEqual(validate_enhancement_plan(edit_plan, plan)["status"], "passed")

        plan["subtitles"]["cues"][0]["review_status"] = "pending"
        result = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("subtitle_cue_unverified", {issue["code"] for issue in result["issues"]})


    def test_render_stage_order_cannot_change(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        invalid = copy.deepcopy(plan)
        invalid["render_stages"].reverse()

        result = validate_enhancement_plan(edit_plan, invalid)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("invalid_render_order", {issue["code"] for issue in result["issues"]})


if __name__ == "__main__":
    unittest.main()
