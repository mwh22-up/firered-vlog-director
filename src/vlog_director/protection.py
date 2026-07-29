from __future__ import annotations

from collections import defaultdict
from typing import Any

from .intervals import interval_coverage

LOCKED_MIN_COVERAGE = 0.95
PROTECTED_MIN_COVERAGE = 0.80
PROTECTED_WARNING_COVERAGE = 0.95
GROUP_MEMBER_MIN_COVERAGE = 0.80


def _selected_ranges_by_source(edit_plan: dict[str, Any]) -> dict[str, list[tuple[float, float]]]:
    selected: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for chapter in edit_plan.get("chapters", []):
        for segment in chapter.get("segments", []):
            selected[segment["source"]].append(
                (float(segment["in_sec"]), float(segment["out_sec"]))
            )
    return selected


def _issue(
    severity: str,
    code: str,
    subject_id: str,
    coverage: float,
    message: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "subject_id": subject_id,
        "coverage": round(coverage, 4),
        "message": message,
    }


def validate_protection(
    moments_document: dict[str, Any],
    edit_plan: dict[str, Any],
) -> dict[str, Any]:
    selected = _selected_ranges_by_source(edit_plan)
    issues: list[dict[str, Any]] = []
    coverage_by_moment: dict[str, float] = {}

    for moment in moments_document.get("moments", []):
        coverage = interval_coverage(
            float(moment["start_sec"]),
            float(moment["end_sec"]),
            selected.get(moment["source"], []),
        )
        coverage_by_moment[moment["id"]] = round(coverage, 4)
        keep_level = moment["keep_level"]

        if keep_level == "locked" and coverage < LOCKED_MIN_COVERAGE:
            issues.append(
                _issue(
                    "error",
                    "locked_moment_missing",
                    moment["id"],
                    coverage,
                    "Locked moment must be covered by at least 95%.",
                )
            )
        elif keep_level == "protected" and coverage < PROTECTED_MIN_COVERAGE:
            issues.append(
                _issue(
                    "error",
                    "protected_moment_missing",
                    moment["id"],
                    coverage,
                    "Protected moment needs manual approval when coverage is below 80%.",
                )
            )
        elif keep_level == "protected" and coverage < PROTECTED_WARNING_COVERAGE:
            issues.append(
                _issue(
                    "warning",
                    "protected_moment_trimmed",
                    moment["id"],
                    coverage,
                    "Protected moment is present but may have lost context.",
                )
            )

    group_coverage: dict[str, dict[str, float]] = {}
    for group in moments_document.get("groups", []):
        member_coverage: dict[str, float] = {}
        for member in group.get("members", []):
            coverage = interval_coverage(
                float(member["start_sec"]),
                float(member["end_sec"]),
                selected.get(member["source"], []),
            )
            member_coverage[member["role"]] = round(coverage, 4)
            if group.get("must_keep_together") and coverage < GROUP_MEMBER_MIN_COVERAGE:
                issues.append(
                    _issue(
                        "error",
                        "moment_group_incomplete",
                        group["id"],
                        coverage,
                        f"Required group member '{member['role']}' is not sufficiently covered.",
                    )
                )
        group_coverage[group["id"]] = member_coverage

    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": "1.0",
        "plan_version": edit_plan.get("version"),
        "status": "blocked" if blocking_count else "passed",
        "blocking_count": blocking_count,
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "coverage_by_moment": coverage_by_moment,
        "coverage_by_group": group_coverage,
        "issues": issues,
    }
