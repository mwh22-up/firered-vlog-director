from __future__ import annotations

from typing import Any, Iterable, Mapping


def _intersection(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[int, int, int, int] | None:
    x0 = max(int(left["x"]), int(right["x"]))
    y0 = max(int(left["y"]), int(right["y"]))
    x1 = min(int(left["x"]) + int(left["width"]), int(right["x"]) + int(right["width"]))
    y1 = min(int(left["y"]) + int(left["height"]), int(right["y"]) + int(right["height"]))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def audit_effect_collisions(
    *,
    effect_id: str,
    sample_time_sec: float,
    effect_bbox: Mapping[str, Any] | None,
    protected_regions: Iterable[Mapping[str, Any]],
    blocker_ratio: float = 0.05,
) -> list[dict[str, Any]]:
    """Measure effect-alpha overlap against time-bound protected regions."""
    if effect_bbox is None:
        return []
    findings: list[dict[str, Any]] = []
    for region in protected_regions:
        if not float(region["start_sec"]) <= sample_time_sec <= float(region["end_sec"]):
            continue
        overlap = _intersection(effect_bbox, region["bbox"])
        if overlap is None:
            continue
        x0, y0, x1, y1 = overlap
        intersection_area = (x1 - x0) * (y1 - y0)
        protected_area = int(region["bbox"]["width"]) * int(region["bbox"]["height"])
        effect_area = int(effect_bbox["width"]) * int(effect_bbox["height"])
        protected_ratio = intersection_area / max(1, protected_area)
        effect_ratio = intersection_area / max(1, effect_area)
        findings.append(
            {
                "effect_id": effect_id,
                "sample_time_sec": round(sample_time_sec, 6),
                "protected_id": str(region["region_id"]),
                "protected_type": str(region["region_type"]),
                "intersection_area_px": intersection_area,
                "protected_overlap_ratio": round(protected_ratio, 6),
                "effect_overlap_ratio": round(effect_ratio, 6),
                "severity": "error" if protected_ratio >= blocker_ratio else "warning",
            }
        )
    return findings
