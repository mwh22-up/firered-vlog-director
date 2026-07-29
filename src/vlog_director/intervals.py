from __future__ import annotations

from collections.abc import Iterable

Interval = tuple[float, float]


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    normalized = sorted(
        (float(start), float(end))
        for start, end in intervals
        if float(end) > float(start)
    )
    if not normalized:
        return []

    merged: list[Interval] = [normalized[0]]
    for start, end in normalized[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def interval_coverage(
    required_start: float,
    required_end: float,
    selected_ranges: Iterable[Interval],
) -> float:
    required_duration = required_end - required_start
    if required_duration <= 0:
        raise ValueError("required interval must have positive duration")

    clipped = (
        (max(required_start, start), min(required_end, end))
        for start, end in selected_ranges
    )
    covered_duration = sum(end - start for start, end in merge_intervals(clipped))
    return min(1.0, covered_duration / required_duration)
