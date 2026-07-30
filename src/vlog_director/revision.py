from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
from typing import Any


def _segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        segment
        for chapter in plan.get("chapters", [])
        for segment in chapter.get("segments", [])
    ]


def _signature(segment: dict[str, Any]) -> tuple[str, float, float]:
    return (
        str(segment["source"]),
        round(float(segment["in_sec"]), 3),
        round(float(segment["out_sec"]), 3),
    )


def _duration(plan: dict[str, Any]) -> float:
    return sum(
        float(segment["out_sec"]) - float(segment["in_sec"])
        for segment in _segments(plan)
    )


def compare_revisions(
    parent: dict[str, Any],
    candidate: dict[str, Any],
    *,
    minimum_change_ratio: float = 0.08,
) -> dict[str, Any]:
    parent_signatures = [_signature(segment) for segment in _segments(parent)]
    candidate_signatures = [_signature(segment) for segment in _segments(candidate)]
    matcher = SequenceMatcher(a=parent_signatures, b=candidate_signatures, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    denominator = max(len(parent_signatures), len(candidate_signatures), 1)
    change_ratio = 1.0 - matched / denominator
    parent_duration = _duration(parent)
    candidate_duration = _duration(candidate)

    issues: list[dict[str, str]] = []
    if candidate.get("parent_version") != parent.get("version"):
        issues.append(
            {
                "severity": "error",
                "code": "parent_version_mismatch",
                "message": "Candidate parent_version must reference the supplied parent plan.",
            }
        )
    if int(candidate.get("version", 0)) <= int(parent.get("version", 0)):
        issues.append(
            {
                "severity": "error",
                "code": "version_not_advanced",
                "message": "Candidate version must be greater than the parent version.",
            }
        )
    if parent_signatures == candidate_signatures:
        issues.append(
            {
                "severity": "error",
                "code": "timeline_unchanged",
                "message": "A director revision cannot reuse the parent timeline unchanged.",
            }
        )
    elif change_ratio < minimum_change_ratio:
        issues.append(
            {
                "severity": "error",
                "code": "timeline_change_too_small",
                "message": (
                    f"Timeline change ratio {change_ratio:.1%} is below the required "
                    f"{minimum_change_ratio:.1%}."
                ),
            }
        )

    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": "1.0",
        "status": "blocked" if blocking_count else "passed",
        "blocking_count": blocking_count,
        "minimum_change_ratio": minimum_change_ratio,
        "change_ratio": round(change_ratio, 4),
        "parent_version": parent.get("version"),
        "candidate_version": candidate.get("version"),
        "parent_segment_count": len(parent_signatures),
        "candidate_segment_count": len(candidate_signatures),
        "parent_duration_sec": round(parent_duration, 3),
        "candidate_duration_sec": round(candidate_duration, 3),
        "duration_delta_sec": round(candidate_duration - parent_duration, 3),
        "issues": issues,
    }


def _principle_ids(profile: dict[str, Any]) -> set[str]:
    principles = profile.get("principles", profile.get("semantic_principles", []))
    return {
        str(item["id"])
        for item in principles
        if isinstance(item, dict) and item.get("id")
    }


def compile_revision(
    parent: dict[str, Any],
    profile: dict[str, Any],
    directives: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    requested_principles = [str(value) for value in directives.get("applied_principles", [])]
    unknown_principles = sorted(set(requested_principles) - _principle_ids(profile))
    if not requested_principles:
        raise ValueError("directives must declare at least one applied_principle")
    if unknown_principles:
        raise ValueError(f"unknown director principles: {', '.join(unknown_principles)}")

    chapters = deepcopy(directives.get("chapters", []))
    if not chapters:
        raise ValueError("directives must contain a non-empty chapters list")
    for chapter in chapters:
        duration = sum(
            float(segment["out_sec"]) - float(segment["in_sec"])
            for segment in chapter.get("segments", [])
        )
        chapter["target_duration_sec"] = round(duration, 3)

    candidate = {
        "schema_version": parent["schema_version"],
        "project_id": parent["project_id"],
        "version": int(directives["version"]),
        "parent_version": parent["version"],
        "brief": deepcopy(parent["brief"]),
        "chapters": chapters,
        "music": deepcopy(directives.get("music", parent.get("music", []))),
        "qa": deepcopy(directives.get("qa", [])),
        "created_at": str(directives["created_at"]),
    }
    candidate["brief"]["target_duration_sec"] = round(_duration(candidate), 3)

    report = compare_revisions(
        parent,
        candidate,
        minimum_change_ratio=float(directives.get("minimum_change_ratio", 0.08)),
    )
    report["profile_id"] = profile.get("profile_id")
    report["applied_principles"] = requested_principles
    if report["status"] != "passed":
        raise ValueError(
            "; ".join(issue["message"] for issue in report["issues"])
        )
    return candidate, report
