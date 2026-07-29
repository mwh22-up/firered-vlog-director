from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .shot_scoring import clamp


def refine_sequence_roles(shots: list[dict[str, Any]]) -> None:
    for index, shot in enumerate(shots):
        previous_roles = {
            item["role"]
            for item in shots[max(0, index - 2) : index]
        }
        has_dialogue_context = "dialogue" in previous_roles
        if (
            shot["role"] in {"ambient", "detail", "transition"}
            and (
                has_dialogue_context
                or shot["speech_ratio"] >= 0.15
            )
            and shot["audio"]["peak"] >= 0.58
            and shot["duration_sec"] <= 4.5
        ):
            shot["role"] = "reaction"
        if (
            shot["role"] == "reaction"
            and "action" in previous_roles
            and shot["speech_ratio"] >= 0.1
            and shot["novelty_score"] >= 0.25
        ):
            shot["role"] = "payoff"


def group_shots_into_events(
    shots: list[dict[str, Any]],
    *,
    min_duration_sec: float = 25,
    target_duration_sec: float = 60,
    max_duration_sec: float = 110,
) -> list[dict[str, Any]]:
    if not shots:
        return []
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    event_start = shots[0]["start_sec"]

    for index, shot in enumerate(shots):
        current.append(shot)
        elapsed = shot["end_sec"] - event_start
        boundary = boundary_score(shots, index)
        should_close = (
            elapsed >= max_duration_sec
            or elapsed >= target_duration_sec
            and boundary >= 0.35
            or elapsed >= min_duration_sec
            and boundary >= 0.72
        )
        if should_close and index < len(shots) - 1:
            groups.append(current)
            current = []
            event_start = shots[index + 1]["start_sec"]
    if current:
        groups.append(current)
    return [
        summarize_event(group, index)
        for index, group in enumerate(groups, start=1)
    ]


def boundary_score(shots: list[dict[str, Any]], index: int) -> float:
    shot = shots[index]
    previous = shots[index - 1] if index else None
    score = 0.0
    if shot["role"] in {"transition", "establishing"}:
        score += 0.35
    if shot["duration_sec"] >= 5:
        score += 0.2
    if shot["novelty_score"] >= 0.5:
        score += 0.2
    if shot["audio"]["kind"] == "silence":
        score += 0.18
    if previous and previous["speech_ratio"] >= 0.4 and shot["speech_ratio"] < 0.1:
        score += 0.15
    return min(1.0, score)


def summarize_event(
    shots: list[dict[str, Any]],
    event_index: int,
) -> dict[str, Any]:
    roles = Counter(shot["role"] for shot in shots)
    third = max(1, len(shots) // 3)
    first = shots[:third]
    last = shots[-third:]
    has_setup = any(
        shot["role"] in {"establishing", "dialogue"}
        for shot in first
    )
    has_action = any(
        shot["role"] in {"action", "payoff"}
        for shot in shots
    )
    has_reaction = any(
        shot["role"] in {"reaction", "payoff"}
        for shot in last
    )
    has_closure = any(
        shot["role"] in {"establishing", "ambient", "dialogue"}
        and shot["duration_sec"] >= 2.5
        for shot in last
    )
    completeness = mean(
        [float(has_setup), float(has_action), float(has_reaction), float(has_closure)]
    )
    event_type = classify_event(roles, shots)
    ranked = sorted(shots, key=lambda shot: shot["keep_score"], reverse=True)
    top_count = max(1, round(len(ranked) * 0.3))
    top_score = mean(shot["keep_score"] for shot in ranked[:top_count])
    priority = clamp(top_score * 0.65 + completeness * 0.35)
    return {
        "event_id": f"event-{event_index:03d}",
        "start_sec": shots[0]["start_sec"],
        "end_sec": shots[-1]["end_sec"],
        "duration_sec": round(shots[-1]["end_sec"] - shots[0]["start_sec"], 3),
        "event_type": event_type,
        "shot_count": len(shots),
        "role_counts": dict(sorted(roles.items())),
        "completeness_score": round(completeness, 4),
        "priority_score": round(priority, 4),
        "recommendation": (
            "protect"
            if priority >= 0.76
            else "retain"
            if priority >= 0.6
            else "optional"
        ),
        "key_shot_ids": [
            shot["shot_id"]
            for shot in ranked[:6]
            if shot["recommendation"] in {"protect", "retain"}
        ],
        "sequence_dependency": sequence_dependency(shots),
    }


def classify_event(
    roles: Counter[str],
    shots: list[dict[str, Any]],
) -> str:
    if roles["action"] + roles["payoff"] >= len(shots) * 0.32:
        return "activity"
    if roles["dialogue"] >= len(shots) * 0.4:
        return "conversation"
    if mean(shot["duration_sec"] for shot in shots) < 2:
        return "montage"
    if roles["detail"] >= len(shots) * 0.25:
        return "detail_sequence"
    return "observational"


def sequence_dependency(shots: list[dict[str, Any]]) -> dict[str, str | None]:
    return {
        "setup_shot_id": _find_role(shots, {"establishing", "dialogue"}),
        "payoff_shot_id": _find_role(
            reversed(shots),
            {"payoff", "action"},
        ),
        "reaction_shot_id": _find_role(
            reversed(shots),
            {"reaction", "dialogue"},
        ),
    }


def _find_role(
    shots: Any,
    roles: set[str],
) -> str | None:
    return next(
        (shot["shot_id"] for shot in shots if shot["role"] in roles),
        None,
    )
