from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from .schema_validation import effect_plan_schema_errors
from .timeline import flatten_edit_plan, timeline_duration


HYPERFRAMES_VERSION = "0.7.90"
HYPERFRAMES_NPM_INTEGRITY = (
    "sha512-mx7v2W1VPcRnQgCV1dCHEQLb/2VIOmX/sAToat49KEaCb/55YfDhDgbTrqiosseu"
    "21r9NKNUJyIkxlxTYVssUQ=="
)
HYPERFRAMES_CAPABILITY = {
    "executor": "hyperframes",
    "package": "hyperframes",
    "version": HYPERFRAMES_VERSION,
    "npm_integrity": HYPERFRAMES_NPM_INTEGRITY,
    "minimum_node_major": 22,
    "output_format": "mov",
    "alpha": True,
    "recipes": [
        "impact_hit",
        "kinetic_explain",
        "place_reveal",
        "reaction_burst",
    ],
}

STYLE_PACKS = {
    "firecut-bold-v1": {
        "id": "firecut-bold-v1",
        "intensity": 0.88,
        "palette": {
            "primary": "#ff3d00",
            "secondary": "#ffd400",
            "contrast": "#00d9ff",
            "ink": "#101014",
            "paper": "#fff7e8",
        },
        "typography": {
            "family": "Arial Black, Microsoft YaHei, sans-serif",
            "title_weight": 900,
            "uppercase_latin": True,
        },
        "motion": {
            "character": "high_energy_editorial",
            "overshoot": 1.12,
            "entry_ratio": 0.24,
            "exit_ratio": 0.18,
        },
        "budget": {
            "max_primary_effects_per_event": 1,
            "max_effect_coverage_ratio": 0.35,
            "minimum_gap_sec": 0.25,
        },
    }
}


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_effect_payload_sha256(effect_plan: dict[str, Any]) -> str:
    """Hash every field that can change rendered effect pixels or placement."""
    payload = {
        "project_id": effect_plan.get("project_id"),
        "version": effect_plan.get("version"),
        "edit_plan_version": effect_plan.get("edit_plan_version"),
        "edit_plan_sha256": effect_plan.get("edit_plan_sha256"),
        "timeline_duration_sec": effect_plan.get("timeline_duration_sec"),
        "style_pack": effect_plan.get("style_pack"),
        "capability_registry": effect_plan.get("capability_registry"),
        "effects": effect_plan.get("effects"),
    }
    return _canonical_sha256(payload)


def _effect(
    *,
    segment_id: str,
    chapter_id: str,
    intent: str,
    start_sec: float,
    end_sec: float,
    evidence_ids: list[str],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "effect_id": f"effect-{segment_id}-{intent}",
        "event_id": f"event-{segment_id}",
        "chapter_id": chapter_id,
        "target_segment_id": segment_id,
        "intent": intent,
        "evidence_ids": evidence_ids,
        "placement": {
            "start_sec": round(start_sec, 4),
            "end_sec": round(end_sec, 4),
        },
        "recipe": {
            "executor": "hyperframes",
            "type": intent,
            "composition_format": "transparent_mov",
            "parameters": parameters,
        },
        "budget": {"role": "primary", "intensity": 0.88},
        "constraints": {
            "preserve_duration": True,
            "avoid_subtitle_safe_zone": True,
            "avoid_face_occlusion": True,
            "protected_zones": ["faces", "main_subject", "subtitles"],
        },
        "status": "review_required",
    }


def _apply_style_budget(
    effects: list[dict[str, Any]],
    *,
    timeline_duration_sec: float,
    style_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep bold hits sparse enough that the effect layer never becomes the edit."""
    budget = style_pack["budget"]
    minimum_gap = float(budget["minimum_gap_sec"])
    ordered = sorted(effects, key=lambda row: float(row["placement"]["start_sec"]))
    kept: list[dict[str, Any]] = []
    minimum_effect_duration = 0.2
    for effect in ordered:
        if kept:
            previous = kept[-1]
            previous_start = float(previous["placement"]["start_sec"])
            previous_end = float(previous["placement"]["end_sec"])
            current_start = float(effect["placement"]["start_sec"])
            current_end = float(effect["placement"]["end_sec"])
            if current_start - previous_end < minimum_gap:
                shortened_end = current_start - minimum_gap
                if shortened_end - previous_start >= minimum_effect_duration:
                    previous["placement"]["end_sec"] = round(shortened_end, 4)
                else:
                    shifted_start = previous_end + minimum_gap
                    if current_end - shifted_start < minimum_effect_duration:
                        continue
                    effect["placement"]["start_sec"] = round(shifted_start, 4)
        kept.append(effect)

    maximum_coverage = timeline_duration_sec * float(budget["max_effect_coverage_ratio"])
    current_coverage = sum(
        float(row["placement"]["end_sec"]) - float(row["placement"]["start_sec"])
        for row in kept
    )
    if current_coverage > maximum_coverage and current_coverage > 0:
        scale = maximum_coverage / current_coverage
        for row in kept:
            start = float(row["placement"]["start_sec"])
            duration = float(row["placement"]["end_sec"]) - start
            row["placement"]["end_sec"] = round(start + duration * scale, 4)
    return kept


def build_effect_plan(
    edit_plan: dict[str, Any],
    *,
    edit_plan_sha256: str,
    style_pack_id: str = "firecut-bold-v1",
) -> dict[str, Any]:
    if style_pack_id not in STYLE_PACKS:
        raise ValueError(f"unsupported effect style pack: {style_pack_id}")
    timeline = flatten_edit_plan(edit_plan)
    timeline_rows = {row["segment_id"]: row for row in timeline}
    effects: list[dict[str, Any]] = []

    for chapter_index, chapter in enumerate(edit_plan.get("chapters", []), start=1):
        chapter_id = str(chapter.get("id", f"ch{chapter_index:02d}"))
        chapter_title = str(chapter.get("title", "")).strip()
        for segment_index, segment in enumerate(chapter.get("segments", []), start=1):
            segment_id = str(segment.get("id", f"{chapter_id}-s{segment_index:03d}"))
            row = timeline_rows[segment_id]
            segment_start = float(row["output_start_sec"])
            segment_end = float(row["output_end_sec"])
            duration = segment_end - segment_start
            role = str(segment.get("story_role", "story"))
            hint = segment.get("effect_hint")

            if isinstance(hint, dict) and hint.get("intent") == "kinetic_explain":
                text = str(hint.get("text", "")).strip()
                if text:
                    effect_duration = min(duration, 2.2)
                    effects.append(
                        _effect(
                            segment_id=segment_id,
                            chapter_id=chapter_id,
                            intent="kinetic_explain",
                            start_sec=segment_start,
                            end_sec=segment_start + effect_duration,
                            evidence_ids=[f"segment:{segment_id}:effect_hint"],
                            parameters={"text": text, "layout": "oversized_split"},
                        )
                    )
                    continue

            if role in {"reaction", "payoff"} and duration >= 0.75:
                effect_duration = min(duration, 1.2)
                offset = min(0.12, max(0.0, duration - effect_duration))
                effects.append(
                    _effect(
                        segment_id=segment_id,
                        chapter_id=chapter_id,
                        intent="reaction_burst",
                        start_sec=segment_start + offset,
                        end_sec=segment_start + offset + effect_duration,
                        evidence_ids=[f"segment:{segment_id}:story_role:{role}"],
                        parameters={"glyph": "!", "burst_count": 14},
                    )
                )
                continue

            if role == "opening_preview" and duration >= 0.65:
                effects.append(
                    _effect(
                        segment_id=segment_id,
                        chapter_id=chapter_id,
                        intent="impact_hit",
                        start_sec=segment_start,
                        end_sec=segment_start + min(duration, 0.9),
                        evidence_ids=[f"segment:{segment_id}:story_role:opening_preview"],
                        parameters={"pulse_count": 2, "accent": "radial_flash"},
                    )
                )
                continue

            if segment_index == 1 and chapter_title and duration >= 1.0:
                effects.append(
                    _effect(
                        segment_id=segment_id,
                        chapter_id=chapter_id,
                        intent="place_reveal",
                        start_sec=segment_start,
                        end_sec=segment_start + min(duration, 1.8),
                        evidence_ids=[f"chapter:{chapter_id}:title"],
                        parameters={"text": chapter_title, "layout": "bold_poster"},
                    )
                )

    total_duration = timeline_duration(edit_plan)
    effects = _apply_style_budget(
        effects,
        timeline_duration_sec=total_duration,
        style_pack=STYLE_PACKS[style_pack_id],
    )
    return {
        "schema_version": "1.0",
        "contract_version": "effect-plan-v1",
        "project_id": edit_plan["project_id"],
        "version": 1,
        "edit_plan_version": edit_plan["version"],
        "edit_plan_sha256": edit_plan_sha256,
        "timeline_duration_sec": round(total_duration, 4),
        "style_pack": deepcopy(STYLE_PACKS[style_pack_id]),
        "capability_registry": deepcopy(HYPERFRAMES_CAPABILITY),
        "effects": effects,
    }


def _issue(code: str, subject_id: str, message: str) -> dict[str, str]:
    return {
        "severity": "error",
        "code": code,
        "subject_id": subject_id,
        "message": message,
    }


def validate_effect_plan(
    edit_plan: dict[str, Any],
    effect_plan: dict[str, Any],
    *,
    edit_plan_sha256: str,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    schema_errors = effect_plan_schema_errors(effect_plan)
    for error in schema_errors:
        issues.append(
            _issue("effect_schema_invalid", str(error.json_path), error.message)
        )
    if any(error.validator in {"required", "type"} for error in schema_errors):
        return {"status": "blocked", "blocking_count": len(issues), "issues": issues}

    if effect_plan.get("project_id") != edit_plan.get("project_id"):
        issues.append(_issue("effect_project_mismatch", "effect_plan", "Project IDs differ."))
    if effect_plan.get("edit_plan_version") != edit_plan.get("version"):
        issues.append(
            _issue(
                "effect_edit_plan_version_mismatch",
                "effect_plan",
                "Effect plan targets a different edit plan version.",
            )
        )
    if effect_plan.get("edit_plan_sha256") != edit_plan_sha256:
        issues.append(
            _issue(
                "effect_edit_plan_sha256_mismatch",
                "effect_plan",
                "Effect plan is not bound to the current edit plan content.",
            )
        )
    expected_duration = timeline_duration(edit_plan)
    raw_duration = effect_plan.get("timeline_duration_sec", -1)
    if (
        isinstance(raw_duration, bool)
        or not isinstance(raw_duration, (int, float))
        or not math.isfinite(float(raw_duration))
        or abs(float(raw_duration) - expected_duration) > 0.001
    ):
        issues.append(
            _issue(
                "effect_timeline_duration_mismatch",
                "effect_plan",
                "Effect plan duration must match the approved edit timeline.",
            )
        )
    if effect_plan.get("capability_registry") != HYPERFRAMES_CAPABILITY:
        issues.append(
            _issue(
                "effect_capability_registry_changed",
                "capability_registry",
                "HyperFrames capability registry must match the pinned runtime contract.",
            )
        )
    style_pack = effect_plan.get("style_pack", {})
    expected_style = STYLE_PACKS.get(str(style_pack.get("id")))
    if expected_style is None or style_pack != expected_style:
        issues.append(
            _issue(
                "effect_style_pack_changed",
                "style_pack",
                "Effect style pack must match a versioned built-in style contract.",
            )
        )

    segments = {row["segment_id"]: row for row in flatten_edit_plan(edit_plan)}
    effect_ids: list[str] = []
    primary_counts: dict[str, int] = {}
    for effect in effect_plan.get("effects", []):
        if not isinstance(effect, dict):
            continue
        effect_id = str(effect.get("effect_id", ""))
        effect_ids.append(effect_id)
        segment_id = str(effect.get("target_segment_id", ""))
        segment = segments.get(segment_id)
        if segment is None:
            issues.append(
                _issue(
                    "effect_unknown_target_segment",
                    effect_id,
                    "Effect targets a segment outside the approved edit plan.",
                )
            )
            continue
        placement = effect.get("placement", {})
        try:
            start = float(placement["start_sec"])
            end = float(placement["end_sec"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < float(segment["output_start_sec"]) - 0.0001
            or end > float(segment["output_end_sec"]) + 0.0001
            or end <= start
        ):
            issues.append(
                _issue(
                    "effect_outside_target_segment",
                    effect_id,
                    "Effect placement must remain inside its approved target segment.",
                )
            )
        if effect.get("constraints", {}).get("preserve_duration") is not True:
            issues.append(
                _issue(
                    "effect_duration_mutation_forbidden",
                    effect_id,
                    "Effect recipes cannot change timeline duration.",
                )
            )
        if not effect.get("evidence_ids"):
            issues.append(
                _issue(
                    "effect_evidence_required",
                    effect_id,
                    "Every effect requires target evidence.",
                )
            )
        if effect.get("intent") != effect.get("recipe", {}).get("type"):
            issues.append(
                _issue(
                    "effect_recipe_intent_mismatch",
                    effect_id,
                    "Effect intent and HyperFrames recipe type must match.",
                )
            )
        if effect.get("budget", {}).get("role") == "primary":
            event_id = str(effect.get("event_id", ""))
            primary_counts[event_id] = primary_counts.get(event_id, 0) + 1

    if len(effect_ids) != len(set(effect_ids)):
        issues.append(
            _issue(
                "duplicate_effect_id",
                "effects",
                "Effect IDs must be unique.",
            )
        )
    max_primary = int(
        effect_plan.get("style_pack", {})
        .get("budget", {})
        .get("max_primary_effects_per_event", 1)
    )
    for event_id, count in primary_counts.items():
        if count > max_primary:
            issues.append(
                _issue(
                    "effect_primary_budget_exceeded",
                    event_id,
                    "An event exceeds its primary effect budget.",
                )
            )

    expected_budget = STYLE_PACKS["firecut-bold-v1"]["budget"]
    valid_placements = [
        effect
        for effect in effect_plan.get("effects", [])
        if isinstance(effect, dict)
        and isinstance(effect.get("placement"), dict)
        and isinstance(effect["placement"].get("start_sec"), (int, float))
        and not isinstance(effect["placement"].get("start_sec"), bool)
        and isinstance(effect["placement"].get("end_sec"), (int, float))
        and not isinstance(effect["placement"].get("end_sec"), bool)
        and math.isfinite(float(effect["placement"]["start_sec"]))
        and math.isfinite(float(effect["placement"]["end_sec"]))
    ]
    coverage = sum(
        max(0.0, float(effect["placement"]["end_sec"]) - float(effect["placement"]["start_sec"]))
        for effect in valid_placements
    )
    maximum_coverage = expected_duration * float(expected_budget["max_effect_coverage_ratio"])
    if coverage > maximum_coverage + 0.001:
        issues.append(
            _issue(
                "effect_coverage_budget_exceeded",
                "effects",
                "Total effect coverage exceeds the versioned style budget.",
            )
        )
    ordered_effects = sorted(
        valid_placements,
        key=lambda effect: float(effect["placement"]["start_sec"]),
    )
    minimum_gap = float(expected_budget["minimum_gap_sec"])
    for left, right in zip(ordered_effects, ordered_effects[1:]):
        actual_gap = float(right["placement"]["start_sec"]) - float(left["placement"]["end_sec"])
        if actual_gap < minimum_gap - 0.001:
            issues.append(
                _issue(
                    "effect_minimum_gap_violated",
                    str(right.get("effect_id", "effects")),
                    "Primary effects must preserve the versioned minimum breathing room.",
                )
            )

    return {
        "schema_version": "1.0",
        "status": "blocked" if issues else "passed",
        "blocking_count": len(issues),
        "effect_count": len(effect_plan.get("effects", [])),
        "effect_payload_sha256": canonical_effect_payload_sha256(effect_plan),
        "issues": issues,
    }
