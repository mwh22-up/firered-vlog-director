from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .learning_memory import content_signals, direction_policy, feedback_adjustment
from .protection import validate_protection
from .revision import compare_revisions
from .technique_policy import build_technique_policy


VARIANTS: dict[str, dict[str, float]] = {
    "concise": {"threshold": 0.66, "optional_threshold": 0.76, "budget_ratio": 0.82},
    "balanced": {"threshold": 0.57, "optional_threshold": 0.69, "budget_ratio": 1.0},
    "immersive": {"threshold": 0.49, "optional_threshold": 0.61, "budget_ratio": 1.12},
}


@dataclass(frozen=True)
class AnalysisBinding:
    source: str
    analysis: dict[str, Any]


def _source_tokens(value: str) -> set[str]:
    path = Path(value)
    return {value.casefold(), path.name.casefold(), path.stem.casefold()}


def _analysis_tokens(analysis: dict[str, Any]) -> set[str]:
    source = analysis.get("source", {})
    values = [
        source.get("source_id"),
        source.get("path"),
        source.get("file_name"),
        source.get("source"),
        source.get("target_source"),
        *source.get("aliases", []),
    ]
    tokens: set[str] = set()
    for value in values:
        if value:
            tokens.update(_source_tokens(str(value)))
    return tokens


def bind_analyses(
    parent_plan: dict[str, Any],
    analyses: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    analysis_list = list(analyses)
    binding: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    sources = dict.fromkeys(
        str(segment["source"])
        for chapter in parent_plan.get("chapters", [])
        for segment in chapter.get("segments", [])
    )
    for source in sources:
        source_tokens = _source_tokens(source)
        matches = [analysis for analysis in analysis_list if source_tokens & _analysis_tokens(analysis)]
        if len(matches) == 1:
            binding[source] = matches[0]
        elif not matches:
            missing.append(source)
        else:
            raise ValueError(f"multiple target analyses match source: {source}")
    return binding, missing


def _role_priors(profile: dict[str, Any]) -> dict[str, float]:
    model = profile.get("shot_selection_model", {})
    rows = [
        *model.get("retain_archetypes", []),
        *model.get("selective_archetypes", []),
    ]
    priors = {
        str(row["role"]): float(row.get("average_retained_ratio", 0.5))
        for row in rows
    }
    return {
        "dialogue": 0.98,
        "reaction": 0.82,
        "action": 0.65,
        "payoff": 0.9,
        "detail": 0.08,
        "establishing": 0.19,
        "transition": 0.17,
        "ambient": 0.12,
    } | priors


def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _moment_ranges(
    moments_document: dict[str, Any],
    source: str,
    segment_start: float,
    segment_end: float,
    feedback_document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tokens = _source_tokens(source)
    ranges: list[dict[str, Any]] = []
    for moment in moments_document.get("moments", []):
        if not tokens & _source_tokens(str(moment["source"])):
            continue
        start = max(segment_start, float(moment["start_sec"]))
        end = min(segment_end, float(moment["end_sec"]))
        feedback = feedback_adjustment(
            feedback_document,
            source=source,
            start_sec=start,
            end_sec=end,
        )
        if feedback["excluded"]:
            continue
        if start < end and moment.get("keep_level") in {"locked", "protected"}:
            ranges.append(
                {
                    "start_sec": start,
                    "end_sec": end,
                    "mandatory": True,
                    "reason": f"protected:{moment['id']}",
                }
            )
    for group in moments_document.get("groups", []):
        if not group.get("must_keep_together"):
            continue
        for member in group.get("members", []):
            if not tokens & _source_tokens(str(member["source"])):
                continue
            start = max(segment_start, float(member["start_sec"]))
            end = min(segment_end, float(member["end_sec"]))
            feedback = feedback_adjustment(
                feedback_document,
                source=source,
                start_sec=start,
                end_sec=end,
            )
            if feedback["excluded"]:
                continue
            if start < end:
                ranges.append(
                    {
                        "start_sec": start,
                        "end_sec": end,
                        "mandatory": True,
                        "reason": f"group:{group['id']}:{member['role']}",
                    }
                )
    return ranges


def _shot_score(
    shot: dict[str, Any],
    priors: dict[str, float],
    content_policy: dict[str, Any],
    signals: dict[str, Any],
    feedback: dict[str, Any],
    *,
    fun_weight_multiplier: float = 1.0,
) -> float:
    role = str(shot.get("role", "ambient"))
    keep_score = float(shot.get("keep_score", 0.5))
    prior = priors.get(role, 0.4)
    novelty = float(shot.get("novelty_score", 0.5))
    speech = float(shot.get("speech_ratio", 0.0))
    quality = float(shot.get("quality_score", keep_score))
    event_bonus = float(shot.get("event_priority", 0.0)) * 0.08
    scenic_score = float(signals["scenic_score"])
    fun_score = float(signals["fun_score"])
    content_bonus = (
        scenic_score * float(content_policy["scenic_weight"])
        + fun_score * float(content_policy["fun_weight"])
        + float(signals.get("explicit_fun_score", 0.0))
        * float(content_policy["fun_weight"])
        * max(0.0, fun_weight_multiplier - 1.0)
    )
    contrast_penalty = 0.0
    if content_policy["content_direction"] == "scenic_forward":
        contrast_penalty = max(0.0, fun_score - scenic_score) * float(
            content_policy["contrast_penalty"]
        )
    elif content_policy["content_direction"] == "fun_forward":
        contrast_penalty = max(0.0, scenic_score - fun_score) * float(
            content_policy["contrast_penalty"]
        )
    score = (
        keep_score * 0.42
        + prior * 0.28
        + novelty * 0.1
        + quality * 0.12
        + speech * 0.08
        + event_bonus
        + content_bonus
        - contrast_penalty
        + float(feedback["score_adjustment"])
    )
    return round(max(0.0, min(1.0, score)), 4)


def _event_lookup(
    analysis: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    lookup: dict[str, dict[str, Any]] = {}
    dependencies: set[str] = set()
    for event in analysis.get("events", []):
        for shot_id in event.get("key_shot_ids", []):
            lookup[str(shot_id)] = event
        dependency = event.get("sequence_dependency", {})
        if event.get("recommendation") == "protect":
            dependencies.update(str(value) for value in dependency.values() if value)
        for shot_id in dependency.values():
            if shot_id:
                lookup[str(shot_id)] = event
    return lookup, dependencies


def _transcript_segments(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = analysis.get("transcription", {})
    return [
        segment
        for segment in transcript.get("segments", [])
        if "start_sec" in segment and "end_sec" in segment
    ]


def _align_dialogue_range(
    start: float,
    end: float,
    lower: float,
    upper: float,
    transcript_segments: list[dict[str, Any]],
) -> tuple[float, float]:
    overlapping = [
        segment
        for segment in transcript_segments
        if _overlap(start, end, float(segment["start_sec"]), float(segment["end_sec"])) > 0
    ]
    if not overlapping:
        return start, end
    return (
        max(lower, min(start, min(float(segment["start_sec"]) for segment in overlapping))),
        min(upper, max(end, max(float(segment["end_sec"]) for segment in overlapping))),
    )


def _should_keep_shot(
    *,
    score: float,
    recommendation: str,
    shot_id: str,
    dependency_ids: set[str],
    dialogue: bool,
    feedback: dict[str, Any],
    policy: dict[str, float],
) -> bool:
    if feedback.get("excluded"):
        return False
    if feedback.get("mandatory"):
        return True
    if recommendation == "protect" or shot_id in dependency_ids:
        return True
    if recommendation == "cut_first" and not dialogue:
        return False
    threshold = (
        policy["optional_threshold"]
        if recommendation == "optional"
        else policy["threshold"]
    )
    keep = (
        score >= threshold
        or dialogue and score >= policy["threshold"] - 0.12
    )
    return keep


def _technique_impact(
    rule: dict[str, Any],
    *,
    source: str,
    start_sec: float,
    end_sec: float,
    target_evidence: list[str],
    effect: str,
) -> dict[str, Any]:
    return {
        "technique_key": str(rule["technique_key"]),
        "category": str(rule["category"]),
        "executor": str(rule["executor"]),
        "source_support": int(rule["source_support"]),
        "average_confidence": float(rule["average_confidence"]),
        "target_evidence": list(target_evidence),
        "affected_ranges": [
            {
                "source": source,
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "effect": effect,
            }
        ],
    }


def _interval_is_covered(
    start_sec: float,
    end_sec: float,
    ranges: list[dict[str, Any]],
) -> bool:
    cursor = start_sec
    for item in sorted(ranges, key=lambda row: float(row["start_sec"])):
        item_start = float(item["start_sec"])
        item_end = float(item["end_sec"])
        if item_end <= cursor:
            continue
        if item_start > cursor + 1e-6:
            return False
        cursor = max(cursor, item_end)
        if cursor >= end_sec - 1e-6:
            return True
    return False


def _candidate_ranges(
    source: str,
    parent_segment: dict[str, Any],
    analysis: dict[str, Any],
    profile: dict[str, Any],
    moments_document: dict[str, Any],
    variant: str,
    technique_policy: dict[str, Any] | None = None,
    feedback_document: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start = float(parent_segment["in_sec"])
    end = float(parent_segment["out_sec"])
    priors = _role_priors(profile)
    policy = VARIANTS[variant]
    content_policy = direction_policy(variant, profile)
    event_lookup, dependency_ids = _event_lookup(analysis)
    rules = (technique_policy or {}).get("rules", {})
    humor_rule = rules.get("humor_awkward_process", {})
    transcript = _transcript_segments(analysis)
    ranges: list[dict[str, Any]] = _moment_ranges(
        moments_document,
        source,
        start,
        end,
        feedback_document,
    )
    preselected_ranges = list(ranges)
    considered = 0
    selected = 0
    dialogue_considered = 0
    dialogue_selected = 0
    scenic_selected = 0
    fun_selected = 0

    shots = sorted(analysis.get("shots", []), key=lambda shot: float(shot["start_sec"]))
    for shot in shots:
        shot_start = max(start, float(shot["start_sec"]))
        shot_end = min(end, float(shot["end_sec"]))
        if shot_end - shot_start < 0.25:
            continue
        considered += 1
        shot_id = str(shot.get("shot_id", f"shot-{considered}"))
        event = event_lookup.get(shot_id)
        enriched = dict(shot)
        enriched["event_priority"] = float(event.get("priority_score", 0.0)) if event else 0.0
        signals = content_signals(
            enriched,
            event,
            moments_document,
            source=source,
            start_sec=shot_start,
            end_sec=shot_end,
        )
        feedback = feedback_adjustment(
            feedback_document,
            source=source,
            start_sec=shot_start,
            end_sec=shot_end,
        )
        baseline_score = _shot_score(
            enriched,
            priors,
            content_policy,
            signals,
            feedback,
        )
        fun_score = float(signals["explicit_fun_score"])
        humor_evidence_matched = (
            humor_rule.get("active")
            and fun_score >= float(humor_rule.get("minimum_fun_score", 1.0))
        )
        technique_score = _shot_score(
            enriched,
            priors,
            content_policy,
            signals,
            feedback,
            fun_weight_multiplier=(
                float(humor_rule.get("weight_multiplier", 1.0))
                if humor_evidence_matched
                else 1.0
            ),
        )
        role = str(shot.get("role", "ambient"))
        recommendation = str(shot.get("recommendation", "optional"))
        dialogue = role == "dialogue" or float(shot.get("speech_ratio", 0.0)) >= 0.3
        if dialogue:
            dialogue_considered += 1
        baseline_keep = _should_keep_shot(
            score=baseline_score,
            recommendation=recommendation,
            shot_id=shot_id,
            dependency_ids=dependency_ids,
            dialogue=dialogue,
            feedback=feedback,
            policy=policy,
        )
        technique_keep = _should_keep_shot(
            score=technique_score,
            recommendation=recommendation,
            shot_id=shot_id,
            dependency_ids=dependency_ids,
            dialogue=dialogue,
            feedback=feedback,
            policy=policy,
        )
        technique_selected = bool(
            humor_evidence_matched
            and not baseline_keep
            and technique_keep
            and not _interval_is_covered(
                shot_start,
                shot_end,
                preselected_ranges,
            )
        )
        # Executable reference techniques may admit an evidence-backed
        # borderline shot, but they must not reorder shots that the target
        # policy already selected. This keeps applied traces aligned with an
        # observable threshold crossing in the final, budget-fitted EDL.
        keep = baseline_keep or technique_selected
        score = technique_score if technique_selected else baseline_score
        if not keep:
            continue
        if dialogue:
            dialogue_selected += 1
            shot_start, shot_end = _align_dialogue_range(
                shot_start,
                shot_end,
                start,
                end,
                transcript,
            )
        shot_technique_applications: list[dict[str, Any]] = []
        technique_reasons: list[str] = []
        if technique_selected:
            shot_technique_applications.append(
                _technique_impact(
                    humor_rule,
                    source=source,
                    start_sec=shot_start,
                    end_sec=shot_end,
                    target_evidence=list(signals["explicit_fun_evidence"]),
                    effect="selected_by_fun_weight",
                )
            )
            technique_reasons.append(
                f"technique:{humor_rule['technique_key']}:target_shot:{shot_id}"
            )
        selected += 1
        if float(signals["scenic_score"]) >= 0.55:
            scenic_selected += 1
        if float(signals["fun_score"]) >= 0.55:
            fun_selected += 1
        ranges.append(
            {
                "start_sec": shot_start,
                "end_sec": shot_end,
                "mandatory": (
                    recommendation == "protect"
                    or shot_id in dependency_ids
                    or bool(feedback["mandatory"])
                ),
                "score": score,
                "role": role,
                "speech_ratio": float(shot.get("speech_ratio", 0.0)),
                "scenic_score": float(signals["scenic_score"]),
                "fun_score": float(signals["fun_score"]),
                "reason": ":".join(
                    [
                        f"learned:{shot_id}:{role}:{score:.3f}",
                        str(content_policy["content_direction"]),
                        *technique_reasons,
                        *signals["evidence"],
                        *feedback["evidence"],
                    ]
                ),
                "technique_applications": shot_technique_applications,
            }
        )

    return _merge_ranges(ranges), {
        "considered_shots": considered,
        "selected_shots": selected,
        "dialogue_considered": dialogue_considered,
        "dialogue_selected": dialogue_selected,
        "scenic_selected": scenic_selected,
        "fun_selected": fun_selected,
    }


def _merge_ranges(ranges: list[dict[str, Any]], maximum_gap_sec: float = 0.12) -> list[dict[str, Any]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: (float(item["start_sec"]), float(item["end_sec"])))
    merged: list[dict[str, Any]] = []
    for item in ordered:
        start = float(item["start_sec"])
        end = float(item["end_sec"])
        if end - start < 0.2:
            continue
        if merged and start <= float(merged[-1]["end_sec"]) + maximum_gap_sec:
            prior = merged[-1]
            prior["end_sec"] = max(float(prior["end_sec"]), end)
            prior["mandatory"] = bool(prior.get("mandatory")) or bool(item.get("mandatory"))
            prior["score"] = max(float(prior.get("score", 0.0)), float(item.get("score", 0.0)))
            prior["speech_ratio"] = max(
                float(prior.get("speech_ratio", 0.0)), float(item.get("speech_ratio", 0.0))
            )
            role = str(item.get("role", "protected"))
            if role not in prior["roles"]:
                prior["roles"].append(role)
            prior["reasons"].append(str(item.get("reason", "selected")))
            prior["technique_applications"].extend(
                deepcopy(item.get("technique_applications", []))
            )
            continue
        merged.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "mandatory": bool(item.get("mandatory", False)),
                "score": float(item.get("score", 1.0 if item.get("mandatory") else 0.5)),
                "speech_ratio": float(item.get("speech_ratio", 0.0)),
                "roles": [str(item.get("role", "protected"))],
                "reasons": [str(item.get("reason", "selected"))],
                "technique_applications": deepcopy(
                    item.get("technique_applications", [])
                ),
            }
        )
    for item in merged:
        item["start_sec"] = round(float(item["start_sec"]), 3)
        item["end_sec"] = round(float(item["end_sec"]), 3)
    return merged


def _segment_from_range(parent_segment: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    roles = [role for role in item.get("roles", []) if role != "protected"]
    return {
        "source": parent_segment["source"],
        "in_sec": round(float(item["start_sec"]), 3),
        "out_sec": round(float(item["end_sec"]), 3),
        "story_role": roles[0] if roles else parent_segment.get("story_role", "story"),
        "reason": "; ".join(item.get("reasons", []))[:500],
        "keep_original_audio": bool(parent_segment.get("keep_original_audio", True)),
        "beat_snap": False,
        "confidence": round(max(0.5, min(1.0, float(item.get("score", 0.7)))), 3),
    }


def _analysis_duration(analysis: dict[str, Any]) -> float:
    media_duration = analysis.get("media", {}).get("duration_sec")
    if media_duration is not None:
        return float(media_duration)
    shots = analysis.get("shots", [])
    return max((float(shot["end_sec"]) for shot in shots), default=0.0)


def _chapter_sources(chapter: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sources: dict[str, dict[str, Any]] = {}
    for segment in chapter.get("segments", []):
        sources.setdefault(str(segment["source"]), segment)
    return list(sources.items())


def _applied_rule_trace(profile: dict[str, Any]) -> list[dict[str, str]]:
    available = {
        str(item.get("id")): str(item.get("rule", ""))
        for key in ("shared_rules", "semantic_principles")
        for item in profile.get(key, [])
        if item.get("id")
    }
    implementation = {
        "retain-action": "action role prior changes shot score",
        "retain-dialogue": "dialogue prior and relaxed threshold preserve speech",
        "retain-reaction": "reaction role prior changes shot score",
        "preserve-event-chain": "protected event dependencies are mandatory",
        "dialogue-is-story-structure": "cuts expand to transcript phrase boundaries",
        "action-and-reaction-over-decoration": "detail/ambient/transition require stronger evidence",
        "seasonal-place-texture": "novelty and quality reward distinct place texture",
        "contrast-pacing-by-function": "variant thresholds create concise/balanced/immersive pacing",
    }
    return [
        {"id": rule_id, "rule": available.get(rule_id, ""), "implementation": detail}
        for rule_id, detail in implementation.items()
        if rule_id in available
    ]


def _merge_technique_applications(
    applications: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    range_keys: dict[str, set[tuple[str, float, float, str]]] = {}
    for application in applications:
        key = str(application["technique_key"])
        if key not in grouped:
            grouped[key] = {
                "technique_key": key,
                "category": str(application["category"]),
                "executor": str(application["executor"]),
                "source_support": int(application["source_support"]),
                "average_confidence": float(application["average_confidence"]),
                "target_evidence": [],
                "affected_ranges": [],
            }
            range_keys[key] = set()
        target = grouped[key]
        for evidence in application.get("target_evidence", []):
            evidence_text = str(evidence)
            if evidence_text not in target["target_evidence"]:
                target["target_evidence"].append(evidence_text)
        for affected in application.get("affected_ranges", []):
            range_key = (
                str(affected["source"]),
                float(affected["start_sec"]),
                float(affected["end_sec"]),
                str(affected["effect"]),
            )
            if range_key in range_keys[key]:
                continue
            range_keys[key].add(range_key)
            target["affected_ranges"].append(deepcopy(affected))
    result = []
    for key in sorted(grouped):
        row = grouped[key]
        row["affected_target_count"] = len(row["affected_ranges"])
        result.append(row)
    return result


def _range_duration(item: dict[str, Any]) -> float:
    return float(item["end_sec"]) - float(item["start_sec"])


def _fit_ranges_to_budget(
    ranges: list[dict[str, Any]],
    budget_sec: float,
) -> list[dict[str, Any]]:
    mandatory = [item for item in ranges if item.get("mandatory")]
    optional = [item for item in ranges if not item.get("mandatory")]
    selected = list(mandatory)
    used = sum(_range_duration(item) for item in selected)
    for item in sorted(
        optional,
        key=lambda row: (
            float(row.get("score", 0.0)) + min(0.15, float(row.get("speech_ratio", 0.0)) * 0.15),
            _range_duration(row),
        ),
        reverse=True,
    ):
        duration = _range_duration(item)
        if used + duration <= budget_sec + 0.05:
            selected.append(item)
            used += duration
    return sorted(selected, key=lambda row: float(row["start_sec"]))


def _build_opening_hook(
    chapters: list[dict[str, Any]],
    analyses_by_source: dict[str, dict[str, Any]],
    *,
    target_sec: float = 10.0,
    feedback_document: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    choices: list[tuple[int, float, str, dict[str, Any]]] = []
    for chapter_index, chapter in enumerate(chapters):
        for source, _ in _chapter_sources(chapter):
            for shot in analyses_by_source[source].get("shots", []):
                duration = float(shot["end_sec"]) - float(shot["start_sec"])
                role = str(shot.get("role", "ambient"))
                if duration < 0.8 or role not in {"action", "reaction", "payoff", "establishing"}:
                    continue
                if float(shot.get("speech_ratio", 0.0)) > 0.2:
                    continue
                feedback = feedback_adjustment(
                    feedback_document,
                    source=source,
                    start_sec=float(shot["start_sec"]),
                    end_sec=float(shot["end_sec"]),
                )
                if feedback["excluded"]:
                    continue
                score = (
                    float(shot.get("keep_score", 0.5)) * 0.5
                    + float(shot.get("quality_score", 0.5)) * 0.25
                    + float(shot.get("novelty_score", 0.5)) * 0.25
                )
                if score >= 0.62:
                    choices.append((chapter_index, score, source, shot))
    selected: list[dict[str, Any]] = []
    used_chapters: set[int] = set()
    used_sources: set[str] = set()
    elapsed = 0.0
    for chapter_index, score, source, shot in sorted(choices, key=lambda row: row[1], reverse=True):
        if chapter_index in used_chapters or source in used_sources:
            continue
        start = float(shot["start_sec"])
        duration = min(
            1.4,
            float(shot["end_sec"]) - start,
            target_sec - elapsed,
        )
        if duration < 0.75:
            continue
        selected.append(
            {
                "source": source,
                "in_sec": round(start, 3),
                "out_sec": round(start + duration, 3),
                "story_role": "opening_preview",
                "reason": f"opening-sensory-preview:{shot.get('shot_id')}:{score:.3f}",
                "keep_original_audio": True,
                "beat_snap": False,
                "confidence": round(score, 3),
            }
        )
        used_chapters.add(chapter_index)
        used_sources.add(source)
        elapsed += duration
        if elapsed >= target_sec - 0.05:
            break
    if elapsed < 4.0:
        return None
    return {
        "id": "ch00",
        "title": "开场预告",
        "target_duration_sec": round(elapsed, 3),
        "segments": selected,
    }


def _opening_shot_score(shot: dict[str, Any]) -> float:
    return (
        float(shot.get("keep_score", 0.5)) * 0.5
        + float(shot.get("quality_score", 0.5)) * 0.25
        + float(shot.get("novelty_score", 0.5)) * 0.25
    )


def _build_phased_opening_hook(
    chapters: list[dict[str, Any]],
    analyses_by_source: dict[str, dict[str, Any]],
    rule: dict[str, Any],
    *,
    feedback_document: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not rule.get("active"):
        return None, []
    phase_specs = (
        ("future_payoff", {"payoff", "establishing"}, 1.4),
        ("human_context", {"reaction"}, 2.4),
        ("action_progression", {"action", "transition"}, 1.0),
    )
    source_order = [
        source
        for chapter in chapters
        for source, _ in _chapter_sources(chapter)
    ]
    candidates: dict[str, list[tuple[float, str, dict[str, Any]]]] = {
        phase: [] for phase, _, _ in phase_specs
    }
    for source in dict.fromkeys(source_order):
        for shot in analyses_by_source[source].get("shots", []):
            duration = float(shot["end_sec"]) - float(shot["start_sec"])
            speech_ratio = float(shot.get("speech_ratio", 0.0))
            score = _opening_shot_score(shot)
            if (
                duration < float(rule["minimum_shot_sec"])
                or speech_ratio > float(rule["maximum_speech_ratio"])
                or score < float(rule["minimum_shot_score"])
            ):
                continue
            feedback = feedback_adjustment(
                feedback_document,
                source=source,
                start_sec=float(shot["start_sec"]),
                end_sec=float(shot["end_sec"]),
            )
            if feedback["excluded"]:
                continue
            role = str(shot.get("role", "ambient"))
            for phase, roles, _ in phase_specs:
                if role in roles:
                    candidates[phase].append((score, source, shot))

    selected: list[dict[str, Any]] = []
    applications: list[dict[str, Any]] = []
    used_shots: set[tuple[str, str]] = set()
    for phase, _, maximum_duration in phase_specs:
        available = sorted(candidates[phase], key=lambda row: row[0], reverse=True)
        chosen = next(
            (
                row
                for row in available
                if (row[1], str(row[2].get("shot_id"))) not in used_shots
            ),
            None,
        )
        if chosen is None:
            return None, []
        score, source, shot = chosen
        shot_id = str(shot.get("shot_id", "unknown"))
        used_shots.add((source, shot_id))
        start = float(shot["start_sec"])
        duration = min(maximum_duration, float(shot["end_sec"]) - start)
        end = start + duration
        selected.append(
            {
                "source": source,
                "in_sec": round(start, 3),
                "out_sec": round(end, 3),
                "story_role": "opening_preview",
                "reason": (
                    f"technique:{rule['technique_key']}:phase:{phase}:"
                    f"target_shot:{shot_id}"
                ),
                "keep_original_audio": True,
                "beat_snap": False,
                "confidence": round(score, 3),
            }
        )
        applications.append(
            _technique_impact(
                rule,
                source=source,
                start_sec=start,
                end_sec=end,
                target_evidence=[
                    f"shot:{shot_id}:role={shot.get('role')}",
                    f"shot:{shot_id}:speech_ratio={float(shot.get('speech_ratio', 0.0)):.4f}",
                    f"opening_phase:{phase}",
                ],
                effect=f"opening_phase:{phase}",
            )
        )
    elapsed = sum(
        float(row["out_sec"]) - float(row["in_sec"])
        for row in selected
    )
    return (
        {
            "id": "ch00",
            "title": "Opening preview",
            "target_duration_sec": round(elapsed, 3),
            "segments": selected,
        },
        applications,
    )


def _travel_compression_preview_proposals(
    chapters: list[dict[str, Any]],
    analyses_by_source: dict[str, dict[str, Any]],
    rule: dict[str, Any],
    *,
    feedback_document: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not rule.get("active"):
        return []
    proposals: list[dict[str, Any]] = []
    source_order = [
        source
        for chapter in chapters
        for source, _ in _chapter_sources(chapter)
    ]
    for source in dict.fromkeys(source_order):
        for shot in analyses_by_source[source].get("shots", []):
            start = float(shot["start_sec"])
            end = float(shot["end_sec"])
            duration = end - start
            speech_ratio = float(shot.get("speech_ratio", 0.0))
            motion = float(shot.get("visual", {}).get("motion", 0.0))
            role = str(shot.get("role", "ambient"))
            if (
                duration < float(rule["minimum_shot_sec"])
                or speech_ratio > float(rule["maximum_speech_ratio"])
                or motion < float(rule["minimum_motion"])
                or role not in set(rule["allowed_roles"])
            ):
                continue
            feedback = feedback_adjustment(
                feedback_document,
                source=source,
                start_sec=start,
                end_sec=end,
            )
            if feedback["excluded"]:
                continue
            shot_id = str(shot.get("shot_id", "unknown"))
            proposals.append(
                {
                    "technique_key": str(rule["technique_key"]),
                    "category": str(rule["category"]),
                    "executor": str(rule["executor"]),
                    "execution_mode": "preview_only",
                    "status": "human_rate_selection_required",
                    "source_support": int(rule["source_support"]),
                    "average_confidence": float(rule["average_confidence"]),
                    "target_evidence": [
                        f"shot:{shot_id}:role={role}",
                        f"shot:{shot_id}:duration_sec={duration:.3f}",
                        f"shot:{shot_id}:speech_ratio={speech_ratio:.4f}",
                        f"shot:{shot_id}:visual.motion={motion:.5f}",
                    ],
                    "affected_ranges": [
                        {
                            "source": source,
                            "start_sec": round(start, 3),
                            "end_sec": round(end, 3),
                            "effect": "travel_compression_preview_without_rate",
                        }
                    ],
                    "parameters": {
                        "playback_rate": None,
                        "rate_source": "human_preview_selection",
                    },
                }
            )
    return proposals[:5]


def build_candidate(
    parent_plan: dict[str, Any],
    analyses_by_source: dict[str, dict[str, Any]],
    profile: dict[str, Any],
    moments_document: dict[str, Any],
    *,
    version: int,
    variant: str,
    created_at: str,
    target_duration_sec: float | None = None,
    technique_policy: dict[str, Any] | None = None,
    feedback_document: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown director variant: {variant}")
    chapters: list[dict[str, Any]] = []
    source_reports: dict[str, dict[str, int]] = {}
    candidate_technique_applications: list[dict[str, Any]] = []
    assigned_sources: set[str] = set()
    parent_target = float(parent_plan.get("brief", {}).get("target_duration_sec", 0.0))
    requested_target = float(target_duration_sec or parent_target or 1.0)
    budget_scale = requested_target / max(parent_target, 1.0) * VARIANTS[variant]["budget_ratio"]
    for chapter in parent_plan.get("chapters", []):
        output_segments: list[dict[str, Any]] = []
        chapter_ranges: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for source, template in _chapter_sources(chapter):
            if source in assigned_sources:
                continue
            assigned_sources.add(source)
            analysis = analyses_by_source[source]
            source_duration = _analysis_duration(analysis)
            if source_duration <= 0:
                raise ValueError(f"target analysis has no usable duration: {source}")
            full_source_template = dict(template)
            full_source_template["in_sec"] = 0.0
            full_source_template["out_sec"] = source_duration
            ranges, report = _candidate_ranges(
                source,
                full_source_template,
                analysis,
                profile,
                moments_document,
                variant,
                technique_policy,
                feedback_document,
            )
            aggregate = source_reports.setdefault(
                source,
                {
                    "considered_shots": 0,
                    "selected_shots": 0,
                    "dialogue_considered": 0,
                    "dialogue_selected": 0,
                    "scenic_selected": 0,
                    "fun_selected": 0,
                },
            )
            for key, value in report.items():
                aggregate[key] += int(value)
            chapter_ranges.extend((template, item) for item in ranges)
        chapter_budget = float(chapter.get("target_duration_sec", 0.0)) * budget_scale
        flattened_ranges = [item for _, item in chapter_ranges]
        fitted = _fit_ranges_to_budget(flattened_ranges, chapter_budget)
        candidate_technique_applications.extend(
            application
            for item in fitted
            for application in item.get("technique_applications", [])
        )
        fitted_ids = {id(item) for item in fitted}
        output_segments.extend(
            _segment_from_range(template, item)
            for template, item in chapter_ranges
            if id(item) in fitted_ids
        )
        duration = sum(float(item["out_sec"]) - float(item["in_sec"]) for item in output_segments)
        chapters.append(
            {
                "id": chapter["id"],
                "title": chapter["title"],
                "target_duration_sec": round(duration, 3),
                "segments": output_segments,
            }
        )
    rules = (technique_policy or {}).get("rules", {})
    hook, hook_applications = _build_phased_opening_hook(
        parent_plan.get("chapters", []),
        analyses_by_source,
        rules.get("opening_phased_hook", {}),
        feedback_document=feedback_document,
    )
    if hook is None:
        hook = _build_opening_hook(
            parent_plan.get("chapters", []),
            analyses_by_source,
            feedback_document=feedback_document,
        )
    if hook:
        chapters.insert(0, hook)
    candidate_technique_applications.extend(hook_applications)
    preview_proposals = _travel_compression_preview_proposals(
        parent_plan.get("chapters", []),
        analyses_by_source,
        rules.get("travel_compression_preview", {}),
        feedback_document=feedback_document,
    )
    total_duration = sum(float(chapter["target_duration_sec"]) for chapter in chapters)
    plan = {
        "schema_version": parent_plan["schema_version"],
        "project_id": parent_plan["project_id"],
        "version": version,
        "parent_version": parent_plan["version"],
        "brief": deepcopy(parent_plan["brief"]),
        "chapters": chapters,
        "music": deepcopy(parent_plan.get("music", [])),
        "qa": [],
        "created_at": created_at,
    }
    plan["brief"]["target_duration_sec"] = round(total_duration, 3)
    return plan, {
        "variant": variant,
        "content_direction": direction_policy(variant, profile)["content_direction"],
        "selection_scope": "full_target_sources",
        "sources": source_reports,
        "applied_rules": _applied_rule_trace(profile),
        "technique_application": {
            "profile_id": (technique_policy or {}).get("profile_id"),
            "eligible_pattern_keys": [
                row["technique_key"]
                for row in (technique_policy or {}).get("eligible_patterns", [])
            ],
            "applied_patterns": _merge_technique_applications(
                candidate_technique_applications
            ),
            "preview_required_patterns": preview_proposals,
            "guidance_pattern_keys": [
                row["technique_key"]
                for row in (technique_policy or {}).get("guidance_patterns", [])
            ],
        },
    }


def build_cut_review_manifest(plan: dict[str, Any], window_sec: float = 0.4) -> dict[str, Any]:
    boundaries: list[dict[str, Any]] = []
    cursor = 0.0
    prior: dict[str, Any] | None = None
    for chapter in plan.get("chapters", []):
        for segment in chapter.get("segments", []):
            duration = float(segment["out_sec"]) - float(segment["in_sec"])
            if prior is not None:
                boundaries.append(
                    {
                        "boundary_id": f"cut-{len(boundaries) + 1:04d}",
                        "time_sec": round(cursor, 3),
                        "review_start_sec": round(max(0.0, cursor - window_sec), 3),
                        "review_end_sec": round(cursor + window_sec, 3),
                        "left": {"source": prior["source"], "source_out_sec": prior["out_sec"]},
                        "right": {"source": segment["source"], "source_in_sec": segment["in_sec"]},
                        "checks": ["visual_jump", "audio_pop", "speech_truncation", "subtitle_visibility"],
                        "status": "pending_render_review",
                    }
                )
            cursor += duration
            prior = segment
    return {
        "schema_version": "1.0",
        "plan_version": plan.get("version"),
        "timeline_duration_sec": round(cursor, 3),
        "boundary_count": len(boundaries),
        "boundaries": boundaries,
    }

def _dialogue_retention(source_reports: dict[str, dict[str, int]]) -> float:
    considered = sum(report["dialogue_considered"] for report in source_reports.values())
    selected = sum(report["dialogue_selected"] for report in source_reports.values())
    return selected / considered if considered else 1.0


def _content_alignment(generation_report: dict[str, Any]) -> float:
    selected = sum(
        report["selected_shots"] for report in generation_report["sources"].values()
    )
    if not selected:
        return 0.0
    scenic = sum(
        report.get("scenic_selected", 0) for report in generation_report["sources"].values()
    ) / selected
    fun = sum(
        report.get("fun_selected", 0) for report in generation_report["sources"].values()
    ) / selected
    direction = generation_report.get("content_direction")
    if direction == "scenic_forward":
        return min(1.0, scenic)
    if direction == "fun_forward":
        return min(1.0, fun)
    return min(1.0, (scenic + fun) / 2)


def evaluate_candidate(
    parent_plan: dict[str, Any],
    candidate: dict[str, Any],
    moments_document: dict[str, Any],
    generation_report: dict[str, Any],
    *,
    target_duration_sec: float | None,
    minimum_change_ratio: float,
) -> dict[str, Any]:
    protection = validate_protection(moments_document, candidate)
    revision = compare_revisions(
        parent_plan,
        candidate,
        minimum_change_ratio=minimum_change_ratio,
    )
    duration = float(candidate["brief"]["target_duration_sec"])
    target = target_duration_sec or duration
    duration_fit = max(0.0, 1.0 - abs(duration - target) / max(target, 1.0))
    dialogue_retention = _dialogue_retention(generation_report["sources"])
    change_quality = min(1.0, float(revision["change_ratio"]) / max(minimum_change_ratio * 2, 0.01))
    content_alignment = _content_alignment(generation_report)
    score = (
        (1.0 if protection["status"] == "passed" else 0.0) * 0.38
        + dialogue_retention * 0.22
        + duration_fit * 0.18
        + change_quality * 0.12
        + content_alignment * 0.1
    )
    blocked = protection["status"] != "passed" or revision["status"] != "passed"
    return {
        "variant": generation_report["variant"],
        "status": "blocked" if blocked else "passed",
        "score": round(score, 4),
        "duration_sec": round(duration, 3),
        "duration_fit": round(duration_fit, 4),
        "dialogue_retention": round(dialogue_retention, 4),
        "content_direction": generation_report.get("content_direction"),
        "content_alignment": round(content_alignment, 4),
        "protection": protection,
        "revision": revision,
        "source_selection": generation_report["sources"],
        "technique_application": deepcopy(
            generation_report.get("technique_application", {})
        ),
    }


def build_semantic_view(
    parent_plan: dict[str, Any],
    analyses_by_source: dict[str, dict[str, Any]],
) -> str:
    lines = [
        f"# Target footage semantic view: {parent_plan['project_id']}",
        "",
        "This compact view is generated from target footage, not reference videos.",
    ]
    seen: set[str] = set()
    for chapter in parent_plan.get("chapters", []):
        lines.extend(["", f"## {chapter['id']} {chapter['title']}"])
        for segment in chapter.get("segments", []):
            source = str(segment["source"])
            if source in seen:
                continue
            seen.add(source)
            analysis = analyses_by_source[source]
            shots = analysis.get("shots", [])
            events = analysis.get("events", [])
            transcript = analysis.get("transcription", {})
            lines.append(
                f"- {source}: {len(shots)} shots, {len(events)} events, "
                f"transcript={transcript.get('status', 'missing')}"
            )
            for event in events:
                lines.append(
                    "  - "
                    f"[{float(event['start_sec']):.2f}-{float(event['end_sec']):.2f}] "
                    f"{event.get('event_type', 'event')} priority={float(event.get('priority_score', 0)):.2f} "
                    f"complete={float(event.get('completeness_score', 0)):.2f}"
                )
            for phrase in transcript.get("segments", []):
                text = str(phrase.get("text", "")).strip()
                if text:
                    lines.append(
                        f"  - [{float(phrase['start_sec']):.2f}-{float(phrase['end_sec']):.2f}] {text}"
                    )
    return "\n".join(lines) + "\n"


def direct_timeline(
    parent_plan: dict[str, Any],
    target_analyses: Iterable[dict[str, Any]],
    profile: dict[str, Any],
    moments_document: dict[str, Any],
    *,
    version: int,
    created_at: str,
    target_duration_sec: float | None = None,
    minimum_change_ratio: float = 0.08,
    variants: Iterable[str] = ("concise", "balanced", "immersive"),
    technique_profile: dict[str, Any] | None = None,
    feedback_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    technique_policy = build_technique_policy(technique_profile)
    analyses_by_source, missing = bind_analyses(parent_plan, target_analyses)
    if missing:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "reason": "target_analysis_missing",
            "missing_sources": missing,
            "message": "Reference-video learning cannot replace analysis of the target raw footage.",
            "technique_profile_id": technique_policy.get("profile_id"),
            "candidates": [],
        }
    transcript_missing = [
        source
        for source, analysis in analyses_by_source.items()
        if parent_plan.get("brief", {}).get("keep_dialogue")
        and (
            analysis.get("transcription", {}).get("status") != "ready"
            or analysis.get("transcription", {}).get("portable_redaction")
        )
    ]
    if transcript_missing:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "reason": "target_transcript_missing",
            "missing_sources": transcript_missing,
            "message": "Dialogue-preserving direction requires full target transcripts.",
            "technique_profile_id": technique_policy.get("profile_id"),
            "candidates": [],
        }

    candidates = []
    for variant in variants:
        plan, generation = build_candidate(
            parent_plan,
            analyses_by_source,
            profile,
            moments_document,
            version=version,
            variant=variant,
            created_at=created_at,
            target_duration_sec=target_duration_sec,
            technique_policy=technique_policy,
            feedback_document=feedback_document,
        )
        evaluation = evaluate_candidate(
            parent_plan,
            plan,
            moments_document,
            generation,
            target_duration_sec=target_duration_sec,
            minimum_change_ratio=minimum_change_ratio,
        )
        candidates.append({"variant": variant, "plan": plan, "evaluation": evaluation})

    passed = [candidate for candidate in candidates if candidate["evaluation"]["status"] == "passed"]
    winner = max(passed, key=lambda candidate: candidate["evaluation"]["score"]) if passed else None
    winner_application = (
        winner["evaluation"].get("technique_application", {})
        if winner
        else {}
    )
    return {
        "schema_version": "1.0",
        "status": "review_required" if winner else "blocked",
        "profile_id": profile.get("profile_id"),
        "technique_profile_id": technique_policy.get("profile_id"),
        "technique_application": {
            "profile_id": technique_policy.get("profile_id"),
            "source_count": technique_policy.get("source_count", 0),
            "minimum_source_support": technique_policy.get("minimum_source_support"),
            "eligible_patterns": deepcopy(
                technique_policy.get("eligible_patterns", [])
            ),
            "applied_patterns": deepcopy(
                winner_application.get("applied_patterns", [])
            ),
            "preview_required_patterns": deepcopy(
                winner_application.get("preview_required_patterns", [])
            ),
            "guidance_patterns": deepcopy(
                technique_policy.get("guidance_patterns", [])
            ),
            "candidate_applications": {
                candidate["variant"]: deepcopy(
                    candidate["evaluation"].get("technique_application", {})
                )
                for candidate in candidates
            },
        },
        "target_analysis_count": len(analyses_by_source),
        "minimum_change_ratio": minimum_change_ratio,
        "learning_precedence": [
            "explicit_user_feedback",
            "target_footage_evidence",
            "cross_reference_patterns",
            "source_specific_patterns",
        ],
        "candidate_directions": {
            candidate["variant"]: candidate["evaluation"].get("content_direction")
            for candidate in candidates
        },
        "recommended_variant": winner["variant"] if winner else None,
        "recommended_plan": winner["plan"] if winner else None,
        "candidates": candidates,
        "semantic_view": build_semantic_view(parent_plan, analyses_by_source),
    }


def write_director_result(result: dict[str, Any], output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    report = deepcopy(result)
    semantic_view = str(report.pop("semantic_view", ""))
    recommended_plan = report.pop("recommended_plan", None)
    candidates = report.pop("candidates", [])
    for candidate in candidates:
        variant = candidate["variant"]
        (output_directory / f"candidate.{variant}.json").write_text(
            json.dumps(candidate["plan"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        candidate["plan"] = f"candidate.{variant}.json"
    if recommended_plan:
        (output_directory / "edit_plan.recommended.json").write_text(
            json.dumps(recommended_plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output_directory / "cut_review_manifest.json").write_text(
            json.dumps(build_cut_review_manifest(recommended_plan), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["recommended_plan"] = "edit_plan.recommended.json"
        report["cut_review_manifest"] = "cut_review_manifest.json"
        report["approval_required"] = True
    report["candidates"] = candidates
    (output_directory / "director_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if semantic_view:
        (output_directory / "target_semantic_view.md").write_text(semantic_view, encoding="utf-8")
