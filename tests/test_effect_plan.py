from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from vlog_director.effect_plan import (
    HYPERFRAMES_CAPABILITY,
    build_effect_plan,
    canonical_effect_payload_sha256,
    validate_effect_plan,
)


ROOT = Path(__file__).parents[1]
FORMAL_SCHEMA = ROOT / "schemas" / "effect-plan.schema.json"
RUNTIME_SCHEMA = ROOT / "src" / "vlog_director" / "schemas" / "effect-plan.schema.json"


def _edit_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "bold-demo",
        "version": 3,
        "chapters": [
            {
                "id": "ch01",
                "title": "抵达火星",
                "segments": [
                    {
                        "source": "raw/a.mp4",
                        "in_sec": 2.0,
                        "out_sec": 5.0,
                        "story_role": "establishing",
                        "confidence": 0.9,
                    },
                    {
                        "source": "raw/b.mp4",
                        "in_sec": 8.0,
                        "out_sec": 10.0,
                        "story_role": "reaction",
                        "confidence": 0.92,
                        "reason": "group:event-7:reaction",
                    },
                    {
                        "source": "raw/c.mp4",
                        "in_sec": 11.0,
                        "out_sec": 13.5,
                        "story_role": "action",
                        "confidence": 0.87,
                        "effect_hint": {
                            "intent": "kinetic_explain",
                            "text": "氧气只剩 10%",
                        },
                    },
                ],
            }
        ],
    }


def _digest(document: dict) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EffectPlanTests(unittest.TestCase):
    def test_builder_creates_bold_evidence_bound_hyperframes_cues(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))

        self.assertEqual(plan["style_pack"]["id"], "firecut-bold-v1")
        self.assertGreaterEqual(plan["style_pack"]["intensity"], 0.8)
        self.assertEqual(plan["capability_registry"], HYPERFRAMES_CAPABILITY)
        self.assertEqual(
            {cue["intent"] for cue in plan["effects"]},
            {"place_reveal", "reaction_burst", "kinetic_explain"},
        )
        self.assertTrue(all(cue["status"] == "review_required" for cue in plan["effects"]))
        self.assertTrue(all(cue["recipe"]["executor"] == "hyperframes" for cue in plan["effects"]))
        self.assertTrue(all(cue["evidence_ids"] for cue in plan["effects"]))
        self.assertEqual(
            validate_effect_plan(
                edit_plan,
                plan,
                edit_plan_sha256=_digest(edit_plan),
            )["status"],
            "passed",
        )

    def test_formal_and_runtime_schemas_are_identical_and_validate_plan(self) -> None:
        self.assertEqual(FORMAL_SCHEMA.read_bytes(), RUNTIME_SCHEMA.read_bytes())
        schema = json.loads(FORMAL_SCHEMA.read_text(encoding="utf-8"))
        plan = build_effect_plan(_edit_plan(), edit_plan_sha256=_digest(_edit_plan()))
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(plan)), [])

    def test_edit_plan_change_invalidates_effect_plan(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        changed = copy.deepcopy(edit_plan)
        changed["chapters"][0]["segments"][1]["out_sec"] = 9.8

        result = validate_effect_plan(
            changed,
            plan,
            edit_plan_sha256=_digest(changed),
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIn(
            "effect_edit_plan_sha256_mismatch",
            {issue["code"] for issue in result["issues"]},
        )

    def test_editorial_cards_require_verified_source_and_rights_evidence(self) -> None:
        edit_plan = _edit_plan()
        edit_plan["chapters"][0]["segments"][1]["effect_hint"] = {
            "intent": "route_map",
            "text": "苏黎世 → 因特拉肯",
            "source_reference": "brief:verified-route-1",
            "fact_check_status": "verified",
            "rights_status": "owned",
        }
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        route = next(row for row in plan["effects"] if row["intent"] == "route_map")
        self.assertEqual(route["recipe"]["parameters"]["layout"], "editorial_card")
        self.assertEqual(route["editorial_evidence"]["fact_check_status"], "verified")
        self.assertIn("critical_text_logo", route["constraints"]["protected_zones"])
        self.assertEqual(
            validate_effect_plan(
                edit_plan,
                plan,
                edit_plan_sha256=_digest(edit_plan),
            )["status"],
            "passed",
        )

        plan["effects"][0]["editorial_evidence"] = {
            **route["editorial_evidence"],
            "fact_check_status": "review_required",
        }
        validation = validate_effect_plan(
            edit_plan,
            plan,
            edit_plan_sha256=_digest(edit_plan),
        )
        self.assertEqual(validation["status"], "blocked")

    def test_unverified_editorial_hint_is_not_compiled(self) -> None:
        edit_plan = _edit_plan()
        edit_plan["chapters"][0]["segments"][2]["effect_hint"] = {
            "intent": "source_card",
            "text": "未经核验的历史资料",
            "source_reference": "unknown",
            "fact_check_status": "review_required",
            "rights_status": "review_required",
        }
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        self.assertNotIn("source_card", {row["intent"] for row in plan["effects"]})

    def test_effect_cannot_change_duration_or_escape_target_segment(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        plan["effects"][0]["constraints"]["preserve_duration"] = False
        plan["effects"][0]["placement"]["end_sec"] = 999

        result = validate_effect_plan(
            edit_plan,
            plan,
            edit_plan_sha256=_digest(edit_plan),
        )

        codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("effect_duration_mutation_forbidden", codes)
        self.assertIn("effect_outside_target_segment", codes)

    def test_primary_budget_is_enforced_per_event(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        duplicate = copy.deepcopy(plan["effects"][0])
        duplicate["effect_id"] = "effect-duplicate"
        plan["effects"].append(duplicate)

        result = validate_effect_plan(
            edit_plan,
            plan,
            edit_plan_sha256=_digest(edit_plan),
        )

        self.assertIn(
            "effect_primary_budget_exceeded",
            {issue["code"] for issue in result["issues"]},
        )

    def test_builder_and_validator_enforce_coverage_and_gap_budgets(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        budget = plan["style_pack"]["budget"]
        coverage = sum(
            cue["placement"]["end_sec"] - cue["placement"]["start_sec"]
            for cue in plan["effects"]
        )
        self.assertLessEqual(
            coverage,
            plan["timeline_duration_sec"] * budget["max_effect_coverage_ratio"] + 0.001,
        )
        ordered = sorted(plan["effects"], key=lambda cue: cue["placement"]["start_sec"])
        self.assertTrue(
            all(
                right["placement"]["start_sec"] - left["placement"]["end_sec"]
                >= budget["minimum_gap_sec"] - 0.001
                for left, right in zip(ordered, ordered[1:])
            )
        )

        changed = copy.deepcopy(plan)
        changed["effects"][0]["placement"]["end_sec"] = 3.0
        changed["effects"][1]["placement"]["start_sec"] = 3.0
        changed["effects"][1]["placement"]["end_sec"] = 5.0
        changed["effects"][2]["placement"]["start_sec"] = 5.0
        changed["effects"][2]["placement"]["end_sec"] = 7.5
        codes = {
            issue["code"]
            for issue in validate_effect_plan(
                edit_plan,
                changed,
                edit_plan_sha256=_digest(edit_plan),
            )["issues"]
        }
        self.assertIn("effect_coverage_budget_exceeded", codes)
        self.assertIn("effect_minimum_gap_violated", codes)

    def test_payload_digest_changes_for_timing_style_text_or_recipe(self) -> None:
        edit_plan = _edit_plan()
        plan = build_effect_plan(edit_plan, edit_plan_sha256=_digest(edit_plan))
        original = canonical_effect_payload_sha256(plan)

        for mutate in (
            lambda value: value["effects"][0]["placement"].__setitem__("start_sec", 0.1),
            lambda value: value["style_pack"].__setitem__("intensity", 0.81),
            lambda value: value["effects"][-1]["recipe"]["parameters"].__setitem__("text", "改变"),
            lambda value: value["effects"][0]["recipe"].__setitem__("type", "impact_hit"),
        ):
            changed = copy.deepcopy(plan)
            mutate(changed)
            self.assertNotEqual(canonical_effect_payload_sha256(changed), original)


if __name__ == "__main__":
    unittest.main()
