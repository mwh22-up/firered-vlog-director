import copy
import json
import unittest
from pathlib import Path

from vlog_director.enhancement import (
    RENDER_STAGES,
    build_enhancement_plan,
    validate_enhancement_plan,
)

FIXTURES = Path(__file__).parent / "fixtures"


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

    def test_music_reference_is_optional_and_non_blocking(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"] = {
            "status": "reference_ready",
            "mode": "manual_capcut_reference",
            "non_blocking": True,
            "recommendations": [
                {
                    "recommendation_id": "music-01",
                    "start_sec": 2.0,
                    "end_sec": 8.0,
                    "capcut_search_keywords": ["??", "??"],
                }
            ],
            "tracks": [],
        }
        self.assertEqual(validate_enhancement_plan(edit_plan, plan)["status"], "passed")

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
            "subtitles_not_release_ready",
            {issue["code"] for issue in result["issues"]},
        )


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
