import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.enhancement import (
    RENDER_STAGES,
    build_enhancement_plan,
    normalize_realized_timeline,
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

    def test_archived_nordic_v3_plan_remains_schema_compatible(self) -> None:
        repository = Path(__file__).parents[1]
        archived = json.loads(
            (
                repository
                / "research-artifacts"
                / "nordic-130-144"
                / "project"
                / "work"
                / "enhancement"
                / "enhancement_plan.v3.json"
            ).read_text(encoding="utf-8")
        )
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertEqual(list(Draft202012Validator(schema).iter_errors(archived)), [])

    def test_realized_render_report_boundaries_unlock_segment_treatments(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["video_treatments"][0]["visual"]["brightness"] = 0.08
        plan["music"]["status"] = "ready"
        plan["music"]["rights_manifest"] = "assets/music/rights.json"
        plan["music"]["audition_report"] = "work/qa/audition.json"
        plan["music"]["tracks"] = [
            {
                "id": "realized-tail",
                "source": "assets/music/tail.wav",
                "start_sec": 22.02,
                "end_sec": 22.1,
                "gain_db": -24.0,
                "fade_in_sec": 0.01,
                "fade_out_sec": 0.01,
            }
        ]
        report = {
            "project_id": edit_plan["project_id"],
            "version": edit_plan["version"],
            "actual_duration_sec": 22.12,
            "output_identity": {
                "size_bytes": 123,
                "sha256": "1" * 64,
            },
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/clip-01.mp4",
                    "actual_start_sec": 0.0,
                    "actual_end_sec": 10.04,
                },
                {
                    "chapter_id": "ch01",
                    "segment_index": 2,
                    "source": "raw/clip-02.mp4",
                    "actual_start_sec": 10.04,
                    "actual_end_sec": 22.12,
                },
            ],
            "cut_boundaries": [
                {
                    "actual_time_sec": 10.04,
                    "left_source": "raw/clip-01.mp4",
                    "right_source": "raw/clip-02.mp4",
                }
            ],
        }
        realized = normalize_realized_timeline(edit_plan, report)

        without_timeline = validate_enhancement_plan(edit_plan, plan)
        with_timeline = validate_enhancement_plan(
            edit_plan,
            plan,
            realized_timeline=realized,
        )

        self.assertEqual(without_timeline["status"], "blocked")
        self.assertIn(
            "realized_timeline_required",
            {issue["code"] for issue in without_timeline["issues"]},
        )
        self.assertEqual(with_timeline["status"], "passed")
        self.assertEqual(realized["segments"][0]["end_sec"], 10.04)
        self.assertEqual(realized["segments"][-1]["end_sec"], 22.12)

    def test_realized_timeline_requires_bound_base_media_identity(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["video_treatments"][0]["visual"]["brightness"] = 0.05
        realized = {
            "duration_sec": 22.1,
            "segments": [
                {"segment_id": "ch01-s001", "start_sec": 0.0, "end_sec": 10.05},
                {"segment_id": "ch01-s002", "start_sec": 10.05, "end_sec": 22.1},
            ],
        }

        missing_identity = validate_enhancement_plan(
            edit_plan,
            plan,
            realized_timeline=realized,
        )
        self.assertEqual(missing_identity["status"], "blocked")
        self.assertIn(
            "realized_timeline_base_identity_required",
            {issue["code"] for issue in missing_identity["issues"]},
        )

        realized["base_size_bytes"] = 123
        realized["base_sha256"] = "2" * 64
        self.assertEqual(
            validate_enhancement_plan(
                edit_plan,
                plan,
                realized_timeline=realized,
            )["status"],
            "passed",
        )

    def test_normalized_base_media_size_requires_positive_json_integer(self) -> None:
        edit_plan = load_edit_plan()
        report = {
            "actual_duration_sec": 22.1,
            "segments": [
                {"segment_id": "ch01-s001", "start_sec": 0.0, "end_sec": 10.05},
                {"segment_id": "ch01-s002", "start_sec": 10.05, "end_sec": 22.1},
            ],
            "output_identity": {"sha256": "2" * 64},
        }

        for invalid_size in (1.5, True, "123", 0, -1):
            with self.subTest(invalid_size=invalid_size):
                invalid = copy.deepcopy(report)
                invalid["output_identity"]["size_bytes"] = invalid_size
                with self.assertRaisesRegex(ValueError, "positive JSON integer"):
                    normalize_realized_timeline(edit_plan, invalid)

        report["output_identity"]["size_bytes"] = 123
        self.assertEqual(
            normalize_realized_timeline(edit_plan, report)["base_size_bytes"],
            123,
        )

    def test_non_finite_numbers_fail_closed_before_filter_generation(self) -> None:
        edit_plan = load_edit_plan()
        cases = (
            ("gamma", float("nan")),
            ("exposure_ev", float("inf")),
        )
        for field, value in cases:
            with self.subTest(field=field):
                plan = build_enhancement_plan(edit_plan)
                plan["video_treatments"][0]["visual"][field] = value

                result = validate_enhancement_plan(edit_plan, plan)

                self.assertEqual(result["status"], "blocked")
                self.assertIn(
                    "non_finite_number",
                    {issue["code"] for issue in result["issues"]},
                )

    def test_unimplemented_treatments_fail_closed(self) -> None:
        edit_plan = load_edit_plan()
        cases = (
            ("stabilization", "mode", "auto", "unsupported_stabilization_mode"),
            ("continuity", "transition", "crossfade", "unsupported_continuity_treatment"),
            ("visual", "speed", 1.25, "unsupported_segment_speed"),
        )
        for section, field, value, expected_code in cases:
            with self.subTest(section=section, field=field):
                plan = build_enhancement_plan(edit_plan)
                plan["video_treatments"][0][section][field] = value
                result = validate_enhancement_plan(edit_plan, plan)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(expected_code, {issue["code"] for issue in result["issues"]})

    def test_disabled_visual_treatments_reject_unused_parameters(self) -> None:
        edit_plan = load_edit_plan()
        cases = (
            (
                "denoise",
                {"mode": "off", "luma_spatial": 0.0},
                "inactive_denoise_parameters",
            ),
            (
                "sharpen",
                {"mode": "off", "amount": 0.0},
                "inactive_sharpen_parameters",
            ),
            (
                "reframe",
                {"mode": "off", "width_percent": 100.0},
                "inactive_reframe_parameters",
            ),
        )
        for treatment_name, value, expected_code in cases:
            with self.subTest(treatment_name=treatment_name):
                plan = build_enhancement_plan(edit_plan)
                plan["video_treatments"][0]["visual"][treatment_name] = value

                result = validate_enhancement_plan(edit_plan, plan)

                self.assertEqual(result["status"], "blocked")
                self.assertIn(
                    expected_code,
                    {issue["code"] for issue in result["issues"]},
                )

    def test_ready_music_track_is_validated_as_executable(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"]["status"] = "ready"
        plan["music"]["rights_manifest"] = "assets/music/rights.json"
        plan["music"]["audition_report"] = "work/qa/audition.json"
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

    def test_audition_music_tracks_are_renderable_but_other_states_block(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["music"].update(
            {
                "status": "audition",
                "rights_manifest": "assets/music/rights.json",
                "audition_report": "work/qa/audition.json",
                "tracks": [
                    {
                        "id": "music-01",
                        "source": "assets/music/bed.wav",
                        "start_sec": 2.0,
                        "end_sec": 8.0,
                        "gain_db": -22.0,
                    }
                ],
            }
        )

        self.assertEqual(validate_enhancement_plan(edit_plan, plan)["status"], "passed")

        for status in ("planned", "disabled"):
            with self.subTest(status=status):
                plan["music"]["status"] = status
                result = validate_enhancement_plan(edit_plan, plan)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(
                    "music_not_release_ready",
                    {issue["code"] for issue in result["issues"]},
                )

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
        plan["music"]["rights_manifest"] = "assets/music/rights.json"
        plan["music"]["audition_report"] = "work/qa/audition.json"
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
        self.assertIn("overlay_subtitle_safe_zone_violation", codes)

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

    def test_review_subtitles_allow_only_reviewable_cues(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"].update(
            {
                "status": "review",
                "source_sha256": "0" * 64,
                "coverage": {"status": "pending"},
                "cues": [
                    {
                        "start_sec": 1.0,
                        "end_sec": 2.0,
                        "text": "review subtitle",
                        "review_status": "review_required",
                    }
                ],
            }
        )

        self.assertEqual(validate_enhancement_plan(edit_plan, plan)["status"], "passed")

        plan["subtitles"]["cues"][0]["review_status"] = "pending"
        invalid = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(invalid["status"], "blocked")
        self.assertIn(
            "subtitle_review_cue_status_invalid",
            {issue["code"] for issue in invalid["issues"]},
        )

        plan["subtitles"]["cues"][0]["review_status"] = "verified"
        plan["subtitles"]["status"] = "planned"
        planned = validate_enhancement_plan(edit_plan, plan)
        self.assertEqual(planned["status"], "blocked")
        self.assertIn(
            "subtitles_not_release_ready",
            {issue["code"] for issue in planned["issues"]},
        )

    def test_overlay_subtitle_safe_zone_and_ids_fail_closed(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "ready"
        plan["subtitles"]["source_sha256"] = "0" * 64
        plan["subtitles"]["coverage"] = {"status": "verified"}
        plan["subtitles"]["cues"] = [
            {
                "start_sec": 1.0,
                "end_sec": 2.0,
                "text": "verified subtitle",
                "review_status": "verified",
            }
        ]
        plan["illustration_motion"]["status"] = "ready"
        plan["illustration_motion"]["subtitle_safe_zone"] = True
        overlay = {
            "id": "chapter-title",
            "type": "title_card",
            "source": "assets/illustrations/title.png",
            "start_sec": 1.0,
            "end_sec": 3.0,
            "anchor": "bottom_right",
            "animation": "fade",
            "animation_duration_sec": 0.3,
        }
        plan["illustration_motion"]["items"] = [overlay, copy.deepcopy(overlay)]

        result = validate_enhancement_plan(edit_plan, plan)
        codes = {issue["code"] for issue in result["issues"]}

        self.assertEqual(result["status"], "blocked")
        self.assertIn("overlay_subtitle_safe_zone_violation", codes)
        self.assertIn("duplicate_overlay_id", codes)

    def test_ready_subtitles_require_verified_coverage_and_cues(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "ready"
        plan["subtitles"]["source_sha256"] = "0" * 64
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

    def test_ready_subtitles_require_at_least_one_cue(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "ready"
        plan["subtitles"]["source_sha256"] = "0" * 64
        plan["subtitles"]["coverage"] = {"status": "verified"}

        result = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "ready_subtitles_empty",
            {issue["code"] for issue in result["issues"]},
        )

    def test_subtitle_overlap_is_order_independent_but_touching_is_valid(self) -> None:
        edit_plan = load_edit_plan()
        plan = build_enhancement_plan(edit_plan)
        plan["subtitles"]["status"] = "ready"
        plan["subtitles"]["source_sha256"] = "0" * 64
        plan["subtitles"]["coverage"] = {"status": "verified"}
        plan["subtitles"]["cues"] = [
            {
                "start_sec": 2.0,
                "end_sec": 3.0,
                "text": "second",
                "review_status": "verified",
            },
            {
                "start_sec": 1.0,
                "end_sec": 2.5,
                "text": "first",
                "review_status": "verified",
            },
        ]

        overlapping = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(overlapping["status"], "blocked")
        self.assertIn(
            "subtitle_cue_overlap",
            {issue["code"] for issue in overlapping["issues"]},
        )

        plan["subtitles"]["cues"][1]["end_sec"] = 2.0
        touching = validate_enhancement_plan(edit_plan, plan)

        self.assertEqual(touching["status"], "passed")


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
