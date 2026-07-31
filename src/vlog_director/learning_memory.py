from __future__ import annotations

from pathlib import Path
from typing import Any

SCENIC_TAGS = {
    "scenery",
    "scenic",
    "scenic_reveal",
    "panorama",
    "nature",
    "mountain",
    "forest",
    "ocean",
    "lake",
    "snow",
    "skyline",
    "architecture",
    "local_texture",
    "scenic_with_people",
}
FUN_TAGS = {
    "fun",
    "funny",
    "humor",
    "playful_interaction",
    "verbal_incongruity",
    "physical_mishap",
    "surprise_reaction",
    "awkward_charm",
    "repetition_escalation",
    "cute_or_quirky",
    "observational_humor",
}

CONTENT_DIRECTIONS: dict[str, dict[str, Any]] = {
    "concise": {
        "content_direction": "fun_forward",
        "scenic_weight": 0.08,
        "fun_weight": 0.22,
        "contrast_penalty": 0.14,
    },
    "balanced": {
        "content_direction": "scenic_fun_balanced",
        "scenic_weight": 0.15,
        "fun_weight": 0.15,
        "contrast_penalty": 0.0,
    },
    "immersive": {
        "content_direction": "scenic_forward",
        "scenic_weight": 0.22,
        "fun_weight": 0.08,
        "contrast_penalty": 0.14,
    },
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _source_tokens(value: str) -> set[str]:
    path = Path(value)
    return {value.casefold(), path.name.casefold(), path.stem.casefold()}


def _overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _numeric_score(document: dict[str, Any], key: str) -> float:
    value = document.get(key)
    return _clamp(float(value)) if value is not None else 0.0


def _moment_content_score(moment: dict[str, Any], tags: set[str]) -> tuple[float, float]:
    scenic = _numeric_score(moment, "scenic_score")
    fun = _numeric_score(moment, "fun_score")
    if tags & SCENIC_TAGS and scenic == 0.0:
        importance = _numeric_score(moment, "importance_score")
        quality = _numeric_score(moment, "quality_score")
        confidence = _numeric_score(moment, "confidence")
        scenic = _clamp(importance * 0.4 + quality * 0.4 + confidence * 0.2)
    if tags & FUN_TAGS and fun == 0.0:
        fun = _clamp(
            _numeric_score(moment, "importance_score") * 0.45
            + _numeric_score(moment, "confidence") * 0.35
        )
    return scenic, fun


def content_signals(
    shot: dict[str, Any],
    event: dict[str, Any] | None,
    moments_document: dict[str, Any],
    *,
    source: str,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any]:
    """Return evidence-backed scenic and fun signals for one target shot."""
    scenic = _numeric_score(shot, "scenic_score")
    fun = _numeric_score(shot, "fun_score")
    explicit_fun = 0.0
    explicit_fun_evidence: list[str] = []

    def record_explicit_fun(score: float, evidence_value: str) -> None:
        nonlocal explicit_fun, explicit_fun_evidence
        if score > explicit_fun:
            explicit_fun = score
            explicit_fun_evidence = [evidence_value]
        elif score > 0 and score == explicit_fun:
            explicit_fun_evidence.append(evidence_value)

    evidence: list[str] = []
    if scenic:
        evidence.append("target_shot:scenic_score")
    if fun:
        evidence.append("target_shot:fun_score")
    if "fun_score" in shot and shot.get("fun_score") is not None:
        record_explicit_fun(
            fun,
            f"shot:{shot.get('shot_id', 'unknown')}:fun_score={fun:.4f}",
        )

    if event:
        event_scenic = _numeric_score(event, "scenic_score")
        event_fun = _numeric_score(event, "fun_score")
        if "fun_score" in event and event.get("fun_score") is not None:
            record_explicit_fun(
                event_fun,
                f"event:{event.get('event_id', 'unknown')}:fun_score={event_fun:.4f}",
            )
        if event_scenic > scenic:
            scenic = event_scenic
            evidence.append(f"target_event:{event.get('event_id', 'unknown')}:scenic")
        if event_fun > fun:
            fun = event_fun
            evidence.append(f"target_event:{event.get('event_id', 'unknown')}:fun")

    source_tokens = _source_tokens(source)
    for moment in moments_document.get("moments", []):
        moment_source = str(moment.get("source", ""))
        if not source_tokens & _source_tokens(moment_source):
            continue
        overlap = _overlap(
            start_sec,
            end_sec,
            float(moment.get("start_sec", 0.0)),
            float(moment.get("end_sec", 0.0)),
        )
        if overlap <= 0:
            continue
        tags = {str(value).casefold() for value in moment.get("types", [])}
        moment_scenic, moment_fun = _moment_content_score(moment, tags)
        overlap_ratio = overlap / max(0.001, end_sec - start_sec)
        overlap_weight = min(1.0, overlap_ratio * 1.5)
        moment_scenic *= overlap_weight
        moment_fun *= overlap_weight
        if (
            moment.get("keep_level") == "optional"
            and "fun_score" in moment
            and moment.get("fun_score") is not None
        ):
            explicit_moment_fun = _numeric_score(moment, "fun_score") * overlap_weight
            record_explicit_fun(
                explicit_moment_fun,
                f"moment:{moment.get('id', 'unknown')}:fun_score={explicit_moment_fun:.4f}",
            )
        if moment_scenic > scenic:
            scenic = moment_scenic
            evidence.append(f"moment:{moment.get('id', 'unknown')}:scenic")
        if moment_fun > fun:
            fun = moment_fun
            evidence.append(f"moment:{moment.get('id', 'unknown')}:fun")

    return {
        "scenic_score": round(_clamp(scenic), 4),
        "fun_score": round(_clamp(fun), 4),
        "explicit_fun_score": round(_clamp(explicit_fun), 4),
        "explicit_fun_evidence": list(dict.fromkeys(explicit_fun_evidence)),
        "evidence": list(dict.fromkeys(evidence)),
    }


def feedback_adjustment(
    feedback_document: dict[str, Any] | None,
    *,
    source: str,
    start_sec: float,
    end_sec: float,
) -> dict[str, Any]:
    """Apply explicit user decisions after reference-video priors."""
    if not feedback_document:
        return {
            "score_adjustment": 0.0,
            "mandatory": False,
            "excluded": False,
            "evidence": [],
        }
    source_tokens = _source_tokens(source)
    adjustment = 0.0
    mandatory = False
    excluded = False
    evidence: list[str] = []
    for item in feedback_document.get("shot_feedback", []):
        if not source_tokens & _source_tokens(str(item.get("source", ""))):
            continue
        overlap = _overlap(
            start_sec,
            end_sec,
            float(item.get("start_sec", 0.0)),
            float(item.get("end_sec", 0.0)),
        )
        if overlap <= 0:
            continue
        confidence = _clamp(float(item.get("confidence", 1.0)))
        decision = str(item.get("decision", "")).casefold()
        if decision in {"prefer", "restore", "extend"}:
            adjustment += 0.28 * confidence
        elif decision in {"avoid", "remove", "shorten"}:
            adjustment -= 0.45 * confidence
            if decision in {"avoid", "remove"}:
                excluded = True
        elif decision == "lock":
            adjustment += 0.35 * confidence
            mandatory = True
        else:
            continue
        evidence.append(f"user_feedback:{item.get('id', decision)}:{decision}")
    return {
        "score_adjustment": round(max(-0.75, min(0.75, adjustment)), 4),
        "mandatory": mandatory,
        "excluded": excluded,
        "evidence": evidence,
    }


def direction_policy(
    variant: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    policy = dict(CONTENT_DIRECTIONS[variant])
    weights = (
        profile.get("learning_memory", {})
        .get("content_model", {})
        .get("preference_weights", {})
    )
    policy["scenic_weight"] *= max(0.0, float(weights.get("scenic", 1.0)))
    policy["fun_weight"] *= max(0.0, float(weights.get("fun", 1.0)))
    return policy
