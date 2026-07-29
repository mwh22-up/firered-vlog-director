from __future__ import annotations

from typing import Any


def flatten_edit_plan(edit_plan: dict[str, Any]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    output_cursor = 0.0

    for chapter_index, chapter in enumerate(edit_plan.get("chapters", []), start=1):
        chapter_id = chapter.get("id", f"ch{chapter_index:02d}")
        for segment_index, segment in enumerate(chapter.get("segments", []), start=1):
            source_in = float(segment["in_sec"])
            source_out = float(segment["out_sec"])
            duration = source_out - source_in
            if duration <= 0:
                raise ValueError(
                    f"segment {chapter_id}:{segment_index} must have positive duration"
                )

            segment_id = segment.get("id", f"{chapter_id}-s{segment_index:03d}")
            timeline.append(
                {
                    "segment_id": segment_id,
                    "chapter_id": chapter_id,
                    "source": segment["source"],
                    "source_in_sec": source_in,
                    "source_out_sec": source_out,
                    "output_start_sec": round(output_cursor, 4),
                    "output_end_sec": round(output_cursor + duration, 4),
                    "keep_original_audio": segment.get("keep_original_audio", True),
                }
            )
            output_cursor += duration

    return timeline


def timeline_duration(edit_plan: dict[str, Any]) -> float:
    timeline = flatten_edit_plan(edit_plan)
    return timeline[-1]["output_end_sec"] if timeline else 0.0
