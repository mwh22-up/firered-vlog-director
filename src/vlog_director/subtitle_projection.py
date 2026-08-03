from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping
from .subtitle_readability import (
    SubtitleReadabilityPolicy,
    plan_safe_readability_repairs,
    stable_cue_id,
)



TERMINAL_PUNCTUATION = "。！？!?；;"


@dataclass(frozen=True)
class SubtitleMergePolicy:
    max_gap_sec: float = 0.65
    max_duration_sec: float = 5.5
    min_duration_sec: float = 0.8
    merge_shorter_than_sec: float = 1.4
    merge_shorter_than_chars: int = 6
    max_chars_per_line: int = 15
    max_lines: int = 2
    cut_risk_window_sec: float = 0.3
    low_confidence_threshold: float = 0.5
    very_low_confidence_threshold: float = 0.2
    high_no_speech_threshold: float = 0.5
    low_avg_logprob_threshold: float = -1.0

    def __post_init__(self) -> None:
        if self.max_gap_sec < 0:
            raise ValueError("max_gap_sec must be non-negative")
        if self.max_duration_sec <= 0:
            raise ValueError("max_duration_sec must be positive")
        if not 0 < self.min_duration_sec <= self.max_duration_sec:
            raise ValueError("min_duration_sec must fit inside max_duration_sec")
        if self.merge_shorter_than_sec <= 0:
            raise ValueError("merge_shorter_than_sec must be positive")
        if self.merge_shorter_than_chars <= 0:
            raise ValueError("merge_shorter_than_chars must be positive")
        if self.max_chars_per_line <= 0:
            raise ValueError("max_chars_per_line must be positive")
        if self.max_lines not in {1, 2}:
            raise ValueError("max_lines must be one or two")
        if self.cut_risk_window_sec < 0:
            raise ValueError("cut_risk_window_sec must be non-negative")
        for name in (
            "low_confidence_threshold",
            "very_low_confidence_threshold",
            "high_no_speech_threshold",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.very_low_confidence_threshold > self.low_confidence_threshold:
            raise ValueError(
                "very_low_confidence_threshold cannot exceed low_confidence_threshold"
            )


@dataclass(frozen=True)
class SubtitleCrosscheckPolicy:
    boundary_tolerance_sec: float = 0.15
    context_window_sec: float = 1.5
    timing_midpoint_tolerance_sec: float = 0.75
    strong_match_threshold: float = 0.75
    partial_match_threshold: float = 0.45
    low_confidence_threshold: float = 0.2

    def __post_init__(self) -> None:
        if self.boundary_tolerance_sec < 0:
            raise ValueError("boundary_tolerance_sec must be non-negative")
        if self.context_window_sec < 0:
            raise ValueError("context_window_sec must be non-negative")
        if self.timing_midpoint_tolerance_sec < 0:
            raise ValueError("timing_midpoint_tolerance_sec must be non-negative")
        for name in (
            "strong_match_threshold",
            "partial_match_threshold",
            "low_confidence_threshold",
        ):
            value = float(getattr(self, name))
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between zero and one")
        if self.partial_match_threshold > self.strong_match_threshold:
            raise ValueError(
                "partial_match_threshold cannot exceed strong_match_threshold"
            )


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _round_time(value: float) -> float:
    return round(value, 3)


def _source_id(source: str) -> str:
    normalized = source.replace("\\", "/")
    return PurePosixPath(normalized).stem


def _normalize_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(
        r"(?<=[\u3400-\u4dbf\u4e00-\u9fff]) (?=[\u3400-\u4dbf\u4e00-\u9fff])",
        "",
        normalized,
    )
    normalized = re.sub(r"\s+([，。！？、；：,.!?;:])", r"\1", normalized)
    return normalized


def _join_word_text(words: list[dict[str, Any]]) -> str:
    return _normalize_text("".join(str(word["raw_text"]) for word in words))


def _visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _format_two_lines(
    words: list[dict[str, Any]],
    policy: SubtitleMergePolicy,
) -> tuple[str, bool]:
    plain_text = _join_word_text(words)
    if policy.max_lines == 1 or _visible_length(plain_text) <= policy.max_chars_per_line:
        return plain_text, _visible_length(plain_text) > policy.max_chars_per_line

    candidates: list[tuple[int, int, int, str, str]] = []
    for split_index in range(1, len(words)):
        left = _join_word_text(words[:split_index])
        right = _join_word_text(words[split_index:])
        left_length = _visible_length(left)
        right_length = _visible_length(right)
        if (
            left
            and right
            and left_length <= policy.max_chars_per_line
            and right_length <= policy.max_chars_per_line
        ):
            previous_word = words[split_index - 1]
            next_word = words[split_index]
            pause_sec = max(
                0.0,
                float(next_word["source_start_sec"])
                - float(previous_word["source_end_sec"]),
            )
            preferred_break = (
                previous_word["semantic_break_after"]
                or previous_word["asr_segment_id"] != next_word["asr_segment_id"]
                or pause_sec >= 0.25
            )
            candidates.append(
                (
                    0 if preferred_break else 1,
                    max(left_length, right_length),
                    abs(left_length - right_length),
                    left,
                    right,
                )
            )
    if candidates:
        _, _, _, left, right = min(
            candidates, key=lambda item: (item[0], item[1], item[2])
        )
        return f"{left}\n{right}", False

    limit = policy.max_chars_per_line
    return f"{plain_text[:limit]}\n{plain_text[limit:]}", True


def _analysis_map(
    analyses: Iterable[dict[str, Any]] | Mapping[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    documents = analyses.values() if isinstance(analyses, Mapping) else analyses
    result: dict[str, dict[str, Any]] = {}
    for document in documents:
        source = document.get("source", {})
        source_id = str(source.get("source_id", "")).strip()
        if not source_id:
            raise ValueError("target analysis is missing source.source_id")
        key = source_id.casefold()
        if key in result:
            raise ValueError(f"duplicate target analysis source_id: {source_id}")
        transcription = document.get("transcription", {})
        if transcription.get("status") != "ready":
            raise ValueError(f"target analysis transcription is not ready: {source_id}")
        result[key] = document
    return result


def _realized_segments(
    edit_plan: dict[str, Any],
    render_report: dict[str, Any],
) -> list[dict[str, Any]]:
    raw_measurements = render_report.get("segment_measurements")
    if raw_measurements is None:
        portable_segments = render_report.get("segments")
        if not isinstance(portable_segments, list):
            raise ValueError("realized timeline has no segment measurements")
        expected: list[tuple[str, int, dict[str, Any]]] = []
        for chapter_index, chapter in enumerate(
            edit_plan.get("chapters", []), start=1
        ):
            chapter_id = str(chapter.get("id", f"ch{chapter_index:02d}"))
            for segment_index, segment in enumerate(
                chapter.get("segments", []), start=1
            ):
                expected.append((chapter_id, segment_index, segment))
        if len(portable_segments) != len(expected):
            raise ValueError(
                "realized timeline segment count does not match the edit plan"
            )
        raw_measurements = []
        for realized, (chapter_id, segment_index, segment) in zip(
            portable_segments, expected
        ):
            if not isinstance(realized, dict):
                raise ValueError("realized timeline segments must be objects")
            expected_id = str(
                segment.get("id", f"{chapter_id}-s{segment_index:03d}")
            )
            if str(realized.get("segment_id", "")) != expected_id:
                raise ValueError(
                    "realized timeline segment IDs do not match the edit plan"
                )
            raw_measurements.append(
                {
                    "chapter_id": chapter_id,
                    "segment_index": segment_index,
                    "source": str(segment["source"]),
                    "planned_duration_sec": float(segment["out_sec"])
                    - float(segment["in_sec"]),
                    "actual_start_sec": realized.get("start_sec"),
                    "actual_end_sec": realized.get("end_sec"),
                }
            )
    if not isinstance(raw_measurements, list) or not all(
        isinstance(item, dict) for item in raw_measurements
    ):
        raise ValueError("render report segment_measurements must be an array of objects")
    measurements = {
        (str(item.get("chapter_id")), int(item.get("segment_index", 0))): item
        for item in raw_measurements
    }
    segments: list[dict[str, Any]] = []
    previous_actual_end = 0.0
    if len(measurements) != len(raw_measurements):
        raise ValueError("render report segment measurements must be unique")
    for chapter_index, chapter in enumerate(edit_plan.get("chapters", []), start=1):
        chapter_id = str(chapter.get("id", f"ch{chapter_index:02d}"))
        for segment_index, segment in enumerate(chapter.get("segments", []), start=1):
            measurement = measurements.get((chapter_id, segment_index))
            if measurement is None:
                raise ValueError(
                    f"render report is missing measurement for {chapter_id}:{segment_index}"
                )
            source = str(segment["source"])
            measured_source = str(measurement.get("source", ""))
            if _source_id(source).casefold() != _source_id(measured_source).casefold():
                raise ValueError(
                    f"render measurement source mismatch for {chapter_id}:{segment_index}"
                )
            source_in = _finite_number(segment["in_sec"], "in_sec")
            source_out = _finite_number(segment["out_sec"], "out_sec")
            if source_out <= source_in:
                raise ValueError(f"invalid edit interval for {chapter_id}:{segment_index}")
            actual_start = _finite_number(
                measurement.get("actual_start_sec"), "actual_start_sec"
            )
            actual_end = _finite_number(
                measurement.get("actual_end_sec"), "actual_end_sec"
            )
            if actual_start < 0 or actual_end <= actual_start:
                raise ValueError(
                    f"invalid realized interval for {chapter_id}:{segment_index}"
                )
            if actual_start + 0.02 < previous_actual_end:
                raise ValueError("render measurements are not monotonic")
            planned_duration = source_out - source_in
            measured_planned = _finite_number(
                measurement.get("planned_duration_sec", planned_duration),
                "planned_duration_sec",
            )
            if abs(measured_planned - planned_duration) > 0.02:
                raise ValueError(
                    f"planned duration mismatch for {chapter_id}:{segment_index}"
                )
            realized_duration = actual_end - actual_start
            segment_id = str(
                segment.get("id", f"{chapter_id}-s{segment_index:03d}")
            )
            segments.append(
                {
                    "segment_id": segment_id,
                    "chapter_id": chapter_id,
                    "segment_index": segment_index,
                    "source": source,
                    "source_id": _source_id(source),
                    "source_in_sec": source_in,
                    "source_out_sec": source_out,
                    "actual_start_sec": actual_start,
                    "actual_end_sec": actual_end,
                    "scale_factor": realized_duration / planned_duration,
                }
            )
            previous_actual_end = actual_end

    if len(measurements) != len(segments):
        raise ValueError("render report contains measurements outside the edit plan")
    return segments


def _project_segment_words(
    segment: dict[str, Any],
    analysis: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    transcription = analysis["transcription"]
    source_in = float(segment["source_in_sec"])
    source_out = float(segment["source_out_sec"])
    actual_start = float(segment["actual_start_sec"])
    actual_end = float(segment["actual_end_sec"])
    scale_factor = float(segment["scale_factor"])
    projected: list[dict[str, Any]] = []
    candidate_count = 0

    asr_segments = sorted(
        transcription.get("segments", []),
        key=lambda item: (
            _finite_number(item.get("start_sec"), "asr.start_sec"),
            _finite_number(item.get("end_sec"), "asr.end_sec"),
        ),
    )
    for asr_segment in asr_segments:
        asr_start = _finite_number(asr_segment.get("start_sec"), "asr.start_sec")
        asr_end = _finite_number(asr_segment.get("end_sec"), "asr.end_sec")
        if asr_end <= source_in or asr_start >= source_out:
            continue
        selected_words: list[dict[str, Any]] = []
        for word_index, word in enumerate(asr_segment.get("words", []), start=1):
            word_start = _finite_number(word.get("start_sec"), "word.start_sec")
            word_end = _finite_number(word.get("end_sec"), "word.end_sec")
            if word_end < word_start:
                raise ValueError(
                    f"word timing runs backwards in {segment['source_id']}:"
                    f"{asr_segment.get('id')}:{word_index}"
                )
            zero_duration_timing = word_end == word_start
            overlaps = (
                source_in <= word_start < source_out
                if zero_duration_timing
                else word_end > source_in and word_start < source_out
            )
            if not overlaps:
                continue
            clipped_start = max(word_start, source_in)
            clipped_end = min(word_end, source_out)
            if clipped_end < clipped_start:
                continue
            raw_text = str(word.get("text", ""))
            if not _normalize_text(raw_text):
                continue
            output_start = actual_start + (clipped_start - source_in) * scale_factor
            output_end = actual_start + (clipped_end - source_in) * scale_factor
            output_start = min(actual_end, max(actual_start, output_start))
            output_end = min(actual_end, max(output_start, output_end))
            probability_value = word.get("probability")
            probability = (
                _finite_number(probability_value, "word.probability")
                if probability_value is not None
                else None
            )
            selected_words.append(
                {
                    "raw_text": raw_text,
                    "source_start_sec": clipped_start,
                    "source_end_sec": clipped_end,
                    "output_start_sec": output_start,
                    "output_end_sec": output_end,
                    "probability": probability,
                    "asr_segment_id": str(asr_segment.get("id", "")),
                    "asr_word_index": word_index,
                    "asr_segment_start_sec": asr_start,
                    "asr_segment_end_sec": asr_end,
                    "avg_logprob": asr_segment.get("avg_logprob"),
                    "no_speech_probability": asr_segment.get(
                        "no_speech_probability"
                    ),
                    "clipped_at_source_in": word_start < source_in,
                    "clipped_at_source_out": word_end > source_out,
                    "asr_segment_clipped": asr_start < source_in or asr_end > source_out,
                    "zero_duration_timing": zero_duration_timing,
                    "semantic_break_after": False,
                }
            )
        if not selected_words:
            continue
        candidate_count += 1
        if str(asr_segment.get("text", "")).rstrip().endswith(
            tuple(TERMINAL_PUNCTUATION)
        ):
            selected_words[-1]["semantic_break_after"] = True
        projected.extend(selected_words)

    projected.sort(
        key=lambda item: (item["source_start_sec"], item["source_end_sec"])
    )
    return projected, candidate_count


def _group_fits(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    policy: SubtitleMergePolicy,
) -> bool:
    combined = left + right
    gap = right[0]["source_start_sec"] - left[-1]["source_end_sec"]
    duration = combined[-1]["output_end_sec"] - combined[0]["output_start_sec"]
    return (
        gap <= policy.max_gap_sec
        and duration <= policy.max_duration_sec
        and _visible_length(_join_word_text(combined))
        <= policy.max_chars_per_line * policy.max_lines
        and not left[-1]["semantic_break_after"]
    )


def _split_asr_units(
    words: list[dict[str, Any]],
    policy: SubtitleMergePolicy,
) -> list[list[dict[str, Any]]]:
    units: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if current:
            same_asr_segment = (
                current[-1]["asr_segment_id"] == word["asr_segment_id"]
            )
            if not same_asr_segment or not _group_fits(current, [word], policy):
                units.append(current)
                current = []
        current.append(word)
        if word["semantic_break_after"]:
            units.append(current)
            current = []
    if current:
        units.append(current)
    return units


def _merge_asr_units(
    units: list[list[dict[str, Any]]],
    policy: SubtitleMergePolicy,
) -> list[list[dict[str, Any]]]:
    merged: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for unit in units:
        if not current:
            current = list(unit)
            continue
        current_duration = current[-1]["output_end_sec"] - current[0]["output_start_sec"]
        unit_duration = unit[-1]["output_end_sec"] - unit[0]["output_start_sec"]
        current_chars = _visible_length(_join_word_text(current))
        unit_chars = _visible_length(_join_word_text(unit))
        short_side = (
            current_duration < policy.merge_shorter_than_sec
            or unit_duration < policy.merge_shorter_than_sec
            or current_chars < policy.merge_shorter_than_chars
            or unit_chars < policy.merge_shorter_than_chars
        )
        if short_side and _group_fits(current, unit, policy):
            current.extend(unit)
        else:
            merged.append(current)
            current = list(unit)
    if current:
        merged.append(current)

    index = 0
    while index < len(merged):
        group = merged[index]
        duration = group[-1]["output_end_sec"] - group[0]["output_start_sec"]
        if duration >= policy.min_duration_sec:
            index += 1
            continue
        if index + 1 < len(merged) and _group_fits(group, merged[index + 1], policy):
            merged[index] = group + merged[index + 1]
            del merged[index + 1]
            continue
        if index > 0 and _group_fits(merged[index - 1], group, policy):
            merged[index - 1].extend(group)
            del merged[index]
            index -= 1
            continue
        index += 1
    return merged


def _cue_from_words(
    words: list[dict[str, Any]],
    segment: dict[str, Any],
    analysis: dict[str, Any],
    policy: SubtitleMergePolicy,
) -> dict[str, Any]:
    transcription = analysis["transcription"]
    formatted_text, line_overflow = _format_two_lines(words, policy)
    source_start = min(float(word["source_start_sec"]) for word in words)
    source_end = max(float(word["source_end_sec"]) for word in words)
    output_start = min(float(word["output_start_sec"]) for word in words)
    output_end = max(float(word["output_end_sec"]) for word in words)
    if output_end <= output_start:
        output_end = min(float(segment["actual_end_sec"]), output_start + 0.1)
    probabilities = [
        float(word["probability"])
        for word in words
        if word["probability"] is not None
    ]
    no_speech_probabilities = [
        _finite_number(word["no_speech_probability"], "no_speech_probability")
        for word in words
        if word["no_speech_probability"] is not None
    ]
    avg_logprobs = [
        _finite_number(word["avg_logprob"], "avg_logprob")
        for word in words
        if word["avg_logprob"] is not None
    ]
    risk_flags: list[str] = []
    if probabilities and min(probabilities) < policy.low_confidence_threshold:
        risk_flags.append("low_confidence_word")
    if probabilities and min(probabilities) < policy.very_low_confidence_threshold:
        risk_flags.append("very_low_confidence_word")
    if output_end - output_start < policy.min_duration_sec:
        risk_flags.append("short_duration")
    if output_end - output_start > policy.max_duration_sec:
        risk_flags.append("long_duration")
    if source_start - float(segment["source_in_sec"]) <= policy.cut_risk_window_sec:
        risk_flags.append("near_cut_in")
    if float(segment["source_out_sec"]) - source_end <= policy.cut_risk_window_sec:
        risk_flags.append("near_cut_out")
    if any(
        word["clipped_at_source_in"]
        or word["clipped_at_source_out"]
        or word["asr_segment_clipped"]
        for word in words
    ):
        risk_flags.append("source_boundary_clipped")
    if any(word["zero_duration_timing"] for word in words):
        risk_flags.append("zero_duration_word_timing")
    if line_overflow:
        risk_flags.append("line_limit_exceeded")
    if (
        no_speech_probabilities
        and max(no_speech_probabilities) >= policy.high_no_speech_threshold
    ):
        risk_flags.append("high_no_speech_probability")
    if avg_logprobs and min(avg_logprobs) <= policy.low_avg_logprob_threshold:
        risk_flags.append("low_asr_logprob")

    segment_ids = list(dict.fromkeys(word["asr_segment_id"] for word in words))
    word_refs = [
        {
            "asr_segment_id": word["asr_segment_id"],
            "word_index": word["asr_word_index"],
            "source_start_sec": _round_time(word["source_start_sec"]),
            "source_end_sec": _round_time(word["source_end_sec"]),
            "probability": (
                round(float(word["probability"]), 4)
                if word["probability"] is not None
                else None
            ),
        }
        for word in words
    ]
    return {
        "start_sec": _round_time(output_start),
        "end_sec": _round_time(output_end),
        "text": formatted_text,
        "review_status": "review_required",
        "segment_id": segment["segment_id"],
        "chapter_id": segment["chapter_id"],
        "source": segment["source"],
        "source_id": segment["source_id"],
        "source_start_sec": _round_time(source_start),
        "source_end_sec": _round_time(source_end),
        "risk_flags": risk_flags,
        "asr_provenance": {
            "provider": transcription.get("provider"),
            "model": transcription.get("model"),
            "language": transcription.get("language"),
            "analysis_source_id": analysis["source"]["source_id"],
            "asr_segment_ids": segment_ids,
            "word_refs": word_refs,
            "minimum_word_probability": (
                round(min(probabilities), 4) if probabilities else None
            ),
        },
    }


def project_asr_to_realized_timeline(
    edit_plan: dict[str, Any],
    render_report: dict[str, Any],
    analyses: Iterable[dict[str, Any]] | Mapping[str, dict[str, Any]],
    *,
    subtitle_version: int,
    policy: SubtitleMergePolicy | None = None,
    readability_policy: SubtitleReadabilityPolicy | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if subtitle_version < 1:
        raise ValueError("subtitle_version must be positive")
    merge_policy = policy or SubtitleMergePolicy()
    active_readability_policy = readability_policy or SubtitleReadabilityPolicy()
    analysis_by_source = _analysis_map(analyses)
    realized_segments = _realized_segments(edit_plan, render_report)
    cues: list[dict[str, Any]] = []
    segment_coverage: list[dict[str, Any]] = []
    raw_asr_candidate_count = 0
    selected_word_count = 0

    for segment in realized_segments:
        analysis = analysis_by_source.get(str(segment["source_id"]).casefold())
        if analysis is None:
            raise ValueError(
                f"target analysis is missing for edit source: {segment['source_id']}"
            )
        words, candidate_count = _project_segment_words(segment, analysis)
        raw_asr_candidate_count += candidate_count
        selected_word_count += len(words)
        units = _split_asr_units(words, merge_policy)
        groups = _merge_asr_units(units, merge_policy)
        segment_cues = [
            _cue_from_words(group, segment, analysis, merge_policy) for group in groups
        ]
        cues.extend(segment_cues)
        segment_coverage.append(
            {
                "segment_id": segment["segment_id"],
                "chapter_id": segment["chapter_id"],
                "source": segment["source"],
                "source_id": segment["source_id"],
                "source_start_sec": _round_time(segment["source_in_sec"]),
                "source_end_sec": _round_time(segment["source_out_sec"]),
                "actual_start_sec": _round_time(segment["actual_start_sec"]),
                "actual_end_sec": _round_time(segment["actual_end_sec"]),
                "time_scale_factor": round(float(segment["scale_factor"]), 8),
                "raw_asr_segment_count": candidate_count,
                "selected_word_count": len(words),
                "draft_cue_count": len(segment_cues),
                "risk_cue_count": sum(bool(cue["risk_flags"]) for cue in segment_cues),
                "review_status": "review_required",
            }
        )

    for cue_index, cue in enumerate(cues):
        cues[cue_index] = {
            "cue_id": stable_cue_id(cue, prefix=f"subtitle-v{subtitle_version}"),
            **cue,
        }

    if cues:
        for left, right in zip(cues, cues[1:]):
            if left["end_sec"] > right["start_sec"]:
                raise ValueError(
                    f"projected subtitle cues overlap: {left['cue_id']} and {right['cue_id']}"
                )
            if (
                left["segment_id"] != right["segment_id"]
                and left["end_sec"] > right["start_sec"]
            ):
                raise ValueError("subtitle cue crosses an edit cut")

    actual_duration = _finite_number(
        render_report.get(
            "actual_duration_sec",
            realized_segments[-1]["actual_end_sec"] if realized_segments else 0,
        ),
        "render_report.actual_duration_sec",
    )
    planned_duration = sum(
        float(item["source_out_sec"]) - float(item["source_in_sec"])
        for item in realized_segments
    )
    draft = {
        "schema_version": "1.0",
        "document_type": "subtitle_review_draft",
        "project_id": edit_plan.get("project_id"),
        "subtitle_version": subtitle_version,
        "edit_plan_version": edit_plan.get("version"),
        "render_report_version": render_report.get("version"),
        "status": "review_required",
        "language": "zh-CN",
        "timeline": {
            "basis": "render_report_actual_segment_measurements",
            "mapping": "linear_scale_within_realized_segment",
            "planned_duration_sec": _round_time(planned_duration),
            "actual_duration_sec": _round_time(actual_duration),
        },
        "coverage": {
            "status": "pending",
            "selected_segment_count": len(realized_segments),
            "segments_with_asr_words": sum(
                item["selected_word_count"] > 0 for item in segment_coverage
            ),
            "segments_without_asr_words": sum(
                item["selected_word_count"] == 0 for item in segment_coverage
            ),
            "raw_asr_candidate_count": raw_asr_candidate_count,
            "selected_word_count": selected_word_count,
            "draft_cue_count": len(cues),
        },
        "merge_policy": asdict(merge_policy),
        "segment_coverage": segment_coverage,
        "cues": cues,
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }

    repair_proposals = plan_safe_readability_repairs(
        draft,
        policy=active_readability_policy,
    )
    draft["readability"] = {
        "policy_version": active_readability_policy.policy_version,
        "policy": active_readability_policy.to_dict(),
        "repair_proposal_count": len(repair_proposals),
        "repair_proposals": repair_proposals,
        "status": "review_required",
        "limitations": [
            "machine_repairs_are_proposals_and_never_mark_cues_verified"
        ],
    }
    return draft


_ARABIC_DIGIT_PATTERN = re.compile(r"\d+")
_COMPARISON_STRIP_PATTERN = re.compile(r"[\s，。！？、；：,.!?;:'\"“”‘’（）()\[\]【】…—-]+")


def _integer_under_ten_thousand_to_chinese(value: int) -> str:
    if value == 0:
        return "零"
    digits = "零一二三四五六七八九"
    units = ("", "十", "百", "千")
    pieces: list[str] = []
    zero_pending = False
    unit_index = 0
    remaining = value
    while remaining:
        digit = remaining % 10
        if digit == 0:
            if pieces:
                zero_pending = True
        else:
            if zero_pending:
                pieces.append("零")
                zero_pending = False
            pieces.append(units[unit_index])
            pieces.append(digits[digit])
        unit_index += 1
        remaining //= 10
    result = "".join(reversed(pieces)).rstrip("零")
    if result.startswith("一十"):
        result = result[1:]
    return result


def _comparison_text(text: str) -> str:
    def replace_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        value = int(raw)
        if value < 10_000:
            return _integer_under_ten_thousand_to_chinese(value)
        return raw

    normalized = _normalize_text(text).casefold()
    normalized = _ARABIC_DIGIT_PATTERN.sub(replace_number, normalized)
    return _COMPARISON_STRIP_PATTERN.sub("", normalized)


def _crosscheck_words(cross_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    transcription = cross_analysis.get("transcription", {})
    if transcription.get("status") != "ready":
        raise ValueError("cross ASR transcription is not ready")
    words: list[dict[str, Any]] = []
    segments = transcription.get("segments", [])
    for segment_index, segment in enumerate(segments, start=1):
        segment_id = str(segment.get("id", f"cross-asr-{segment_index:04d}"))
        for word_index, word in enumerate(segment.get("words", []), start=1):
            start_sec = _finite_number(word.get("start_sec"), "cross_word.start_sec")
            end_sec = _finite_number(word.get("end_sec"), "cross_word.end_sec")
            if end_sec < start_sec:
                raise ValueError(
                    f"cross ASR word timing runs backwards: {segment_id}:{word_index}"
                )
            text = _normalize_text(str(word.get("text", "")))
            if not text:
                continue
            probability_value = word.get("probability")
            probability = (
                _finite_number(probability_value, "cross_word.probability")
                if probability_value is not None
                else None
            )
            words.append(
                {
                    "segment_id": segment_id,
                    "word_index": word_index,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "text": text,
                    "probability": probability,
                }
            )
    if not words and transcription.get("words"):
        for word_index, word in enumerate(transcription["words"], start=1):
            start_sec = _finite_number(word.get("start_sec"), "cross_word.start_sec")
            end_sec = _finite_number(word.get("end_sec"), "cross_word.end_sec")
            if end_sec < start_sec:
                raise ValueError(
                    f"cross ASR word timing runs backwards: cross-asr:{word_index}"
                )
            text = _normalize_text(str(word.get("text", "")))
            if not text:
                continue
            probability_value = word.get("probability")
            words.append(
                {
                    "segment_id": "cross-asr",
                    "word_index": word_index,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "text": text,
                    "probability": (
                        _finite_number(probability_value, "cross_word.probability")
                        if probability_value is not None
                        else None
                    ),
                }
            )
    words.sort(key=lambda item: (item["start_sec"], item["end_sec"]))
    return words


def _word_cue_overlap(word: dict[str, Any], cue: dict[str, Any]) -> float:
    word_start = float(word["start_sec"])
    word_end = float(word["end_sec"])
    cue_start = float(cue["start_sec"])
    cue_end = float(cue["end_sec"])
    if word_end == word_start:
        return 1e-9 if cue_start <= word_start <= cue_end else 0.0
    return max(0.0, min(word_end, cue_end) - max(word_start, cue_start))


def _word_cue_distance(word: dict[str, Any], cue: dict[str, Any]) -> float:
    if float(word["end_sec"]) < float(cue["start_sec"]):
        return float(cue["start_sec"]) - float(word["end_sec"])
    if float(word["start_sec"]) > float(cue["end_sec"]):
        return float(word["start_sec"]) - float(cue["end_sec"])
    return 0.0


def _assign_crosscheck_words(
    cues: list[dict[str, Any]],
    words: list[dict[str, Any]],
    policy: SubtitleCrosscheckPolicy,
) -> dict[str, list[dict[str, Any]]]:
    assignments = {str(cue["cue_id"]): [] for cue in cues}
    for word in words:
        overlapping = [
            (cue, _word_cue_overlap(word, cue))
            for cue in cues
            if _word_cue_overlap(word, cue) > 0
        ]
        selected: dict[str, Any] | None = None
        if overlapping:
            selected = max(
                overlapping,
                key=lambda item: (
                    item[1],
                    -abs(
                        (float(item[0]["start_sec"]) + float(item[0]["end_sec"]))
                        / 2
                        - (float(word["start_sec"]) + float(word["end_sec"])) / 2
                    ),
                ),
            )[0]
        else:
            nearby = [
                (cue, _word_cue_distance(word, cue))
                for cue in cues
                if _word_cue_distance(word, cue) <= policy.boundary_tolerance_sec
            ]
            if nearby:
                selected = min(nearby, key=lambda item: item[1])[0]
        if selected is not None:
            assignments[str(selected["cue_id"])].append(word)
    return assignments


def attach_cross_asr_evidence(
    draft: dict[str, Any],
    cross_analysis: dict[str, Any],
    *,
    policy: SubtitleCrosscheckPolicy | None = None,
    crosschecked_at: str | None = None,
) -> dict[str, Any]:
    if draft.get("status") != "review_required":
        raise ValueError("cross ASR evidence can only be attached to a review draft")
    crosscheck_policy = policy or SubtitleCrosscheckPolicy()
    result = deepcopy(draft)
    cues = result.get("cues", [])
    cue_ids = [str(cue.get("cue_id", "")) for cue in cues]
    if any(not cue_id for cue_id in cue_ids) or len(cue_ids) != len(set(cue_ids)):
        raise ValueError("subtitle draft must contain unique non-empty cue IDs")
    if any(cue.get("review_status") != "review_required" for cue in cues):
        raise ValueError("all crosschecked cues must remain review_required")
    for left, right in zip(cues, cues[1:]):
        if float(left["start_sec"]) > float(right["start_sec"]):
            raise ValueError("subtitle cues must be ordered by start time")

    words = _crosscheck_words(cross_analysis)
    assignments = _assign_crosscheck_words(cues, words, crosscheck_policy)
    status_counts: dict[str, int] = {}
    cross_flag_counts: dict[str, int] = {}
    for cue in cues:
        retained_risk_flags = [
            flag
            for flag in cue.get("risk_flags", [])
            if not flag.startswith("cross_asr_")
        ]
        cue_words = assignments[str(cue["cue_id"])]
        evidence_text = _normalize_text("".join(word["text"] for word in cue_words))
        primary_text = _comparison_text(str(cue.get("text", "")))
        comparison_evidence = _comparison_text(evidence_text)
        if not comparison_evidence:
            status = "no_evidence"
            similarity = None
        else:
            similarity = SequenceMatcher(
                None,
                primary_text,
                comparison_evidence,
                autojunk=False,
            ).ratio()
            if similarity >= crosscheck_policy.strong_match_threshold:
                status = "strong_match"
            elif similarity >= crosscheck_policy.partial_match_threshold:
                status = "partial_match"
            else:
                status = "disagreement"
        status_counts[status] = status_counts.get(status, 0) + 1
        probabilities = [
            float(word["probability"])
            for word in cue_words
            if word["probability"] is not None
        ]
        cross_flags: list[str] = []
        if status == "no_evidence":
            cross_flags.append("cross_asr_no_evidence")
        elif status == "disagreement":
            cross_flags.append("cross_asr_disagreement")
        elif status == "partial_match":
            cross_flags.append("cross_asr_partial_match")
        if probabilities and min(probabilities) < crosscheck_policy.low_confidence_threshold:
            cross_flags.append("cross_asr_low_confidence_word")
        midpoint_offset = None
        if cue_words:
            cue_midpoint = (float(cue["start_sec"]) + float(cue["end_sec"])) / 2
            evidence_midpoint = (
                min(float(word["start_sec"]) for word in cue_words)
                + max(float(word["end_sec"]) for word in cue_words)
            ) / 2
            midpoint_offset = cue_midpoint - evidence_midpoint
            if (
                abs(midpoint_offset)
                > crosscheck_policy.timing_midpoint_tolerance_sec
            ):
                cross_flags.append("cross_asr_timing_disagreement")
        nearby_context_words = (
            [
                word
                for word in words
                if _word_cue_distance(word, cue) <= crosscheck_policy.context_window_sec
            ]
            if status != "strong_match"
            else []
        )
        for flag in cross_flags:
            cross_flag_counts[flag] = cross_flag_counts.get(flag, 0) + 1
        cue["cross_asr_evidence"] = {
            "status": status,
            "text": evidence_text,
            "similarity": round(similarity, 4) if similarity is not None else None,
            "matched_word_count": len(cue_words),
            "start_sec": (
                _round_time(min(float(word["start_sec"]) for word in cue_words))
                if cue_words
                else None
            ),
            "end_sec": (
                _round_time(max(float(word["end_sec"]) for word in cue_words))
                if cue_words
                else None
            ),
            "asr_segment_ids": list(
                dict.fromkeys(str(word["segment_id"]) for word in cue_words)
            ),
            "minimum_word_probability": (
                round(min(probabilities), 4) if probabilities else None
            ),
            "midpoint_offset_sec": (
                round(midpoint_offset, 3) if midpoint_offset is not None else None
            ),
            "nearby_context_text": _normalize_text(
                "".join(word["text"] for word in nearby_context_words)
            ),
            "risk_flags": cross_flags,
        }
        cue["risk_flags"] = list(
            dict.fromkeys([*retained_risk_flags, *cross_flags])
        )

    transcription = cross_analysis.get("transcription", {})
    source = cross_analysis.get("source", {})
    result["machine_crosscheck"] = {
        "status": "completed_review_still_required",
        "provider": transcription.get("provider"),
        "model": transcription.get("model"),
        "language": transcription.get("language"),
        "source_id": source.get("source_id"),
        "method": "exclusive_word_timeline_assignment_and_normalized_text_similarity",
        "policy": asdict(crosscheck_policy),
        "summary": {
            "cue_count": len(cues),
            "assigned_word_count": sum(
                len(assignments[str(cue["cue_id"])]) for cue in cues
            ),
            "unassigned_word_count": len(words)
            - sum(len(items) for items in assignments.values()),
            "status_counts": dict(sorted(status_counts.items())),
            "risk_flag_counts": dict(sorted(cross_flag_counts.items())),
            "disagreement_cue_count": status_counts.get("disagreement", 0),
            "no_evidence_cue_count": status_counts.get("no_evidence", 0),
        },
        "limitations": [
            "cross_asr_is_a_machine_second_opinion_not_human_audio_review",
            "agreement_does_not_mark_a_cue_verified",
            "disagreement_requires_listening_before_final_text_selection",
        ],
        "crosschecked_at": crosschecked_at or datetime.now(UTC).isoformat(),
    }
    return result


def apply_evidence_based_text_corrections(
    draft: dict[str, Any],
    corrections: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    if draft.get("status") != "review_required":
        raise ValueError("text corrections can only be applied to a review draft")
    result = deepcopy(draft)
    cue_by_id = {str(cue.get("cue_id")): cue for cue in result.get("cues", [])}
    max_lines = int(result.get("merge_policy", {}).get("max_lines", 2))
    max_chars_per_line = int(
        result.get("merge_policy", {}).get("max_chars_per_line", 15)
    )
    applied: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for correction in corrections:
        cue_id = str(correction.get("cue_id", ""))
        if cue_id in seen_ids:
            raise ValueError(f"duplicate correction cue_id: {cue_id}")
        seen_ids.add(cue_id)
        cue = cue_by_id.get(cue_id)
        if cue is None:
            raise ValueError(f"correction references unknown cue: {cue_id}")
        if cue.get("review_status") != "review_required":
            raise ValueError(f"correction cue is not review_required: {cue_id}")
        expected_text = str(correction.get("expected_text", ""))
        if expected_text and expected_text != str(cue.get("text", "")):
            raise ValueError(f"correction expected_text mismatch: {cue_id}")
        replacement_lines = [
            _normalize_text(line)
            for line in str(correction.get("replacement_text", "")).splitlines()
            if _normalize_text(line)
        ]
        replacement_text = "\n".join(replacement_lines)
        if not replacement_text:
            raise ValueError(f"correction replacement_text is empty: {cue_id}")
        if len(replacement_lines) > max_lines or any(
            _visible_length(line) > max_chars_per_line for line in replacement_lines
        ):
            raise ValueError(f"correction exceeds subtitle line limits: {cue_id}")
        reason = str(correction.get("reason", "")).strip()
        evidence = [str(item).strip() for item in correction.get("evidence", [])]
        evidence = [item for item in evidence if item]
        if not reason or len(evidence) < 2:
            raise ValueError(
                f"correction requires a reason and at least two evidence statements: {cue_id}"
            )
        original_text = str(cue.get("text", ""))
        if replacement_text == original_text:
            raise ValueError(f"correction does not change text: {cue_id}")
        record = {
            "cue_id": cue_id,
            "original_text": original_text,
            "replacement_text": replacement_text,
            "reason": reason,
            "evidence": evidence,
            "review_status": "review_required",
        }
        cue["text"] = replacement_text
        cue["machine_text_correction"] = record
        cue["risk_flags"] = list(
            dict.fromkeys(
                [*cue.get("risk_flags", []), "machine_text_corrected_review_required"]
            )
        )
        applied.append(record)

    result["machine_text_corrections"] = {
        "status": "applied_review_still_required",
        "count": len(applied),
        "items": applied,
        "limitations": [
            "corrections_are_machine_assisted_and_require_full_audio_review",
            "no_cue_is_marked_verified_by_this_step",
        ],
    }
    return result


def build_subtitle_crosscheck_report(
    draft: dict[str, Any],
    *,
    draft_path: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    crosscheck = draft.get("machine_crosscheck")
    if not crosscheck or not str(crosscheck.get("status", "")).startswith(
        "completed"
    ):
        raise ValueError("subtitle draft has no completed machine crosscheck")
    flagged_cues = []
    for cue in draft.get("cues", []):
        evidence = cue.get("cross_asr_evidence", {})
        cross_flags = list(evidence.get("risk_flags", []))
        correction = cue.get("machine_text_correction")
        if evidence.get("status") == "strong_match" and not cross_flags and not correction:
            continue
        flagged_cues.append(
            {
                "cue_id": cue["cue_id"],
                "segment_id": cue["segment_id"],
                "start_sec": cue["start_sec"],
                "end_sec": cue["end_sec"],
                "text": cue["text"],
                "cross_asr_evidence": evidence,
                "machine_text_correction": correction,
                "risk_flags": cue.get("risk_flags", []),
                "review_status": "review_required",
            }
        )
    return {
        "schema_version": "1.0",
        "document_type": "subtitle_machine_crosscheck_report",
        "project_id": draft.get("project_id"),
        "subtitle_version": draft.get("subtitle_version"),
        "status": "review_required",
        "coverage": {"status": "pending"},
        "draft": draft_path,
        "machine_crosscheck": crosscheck,
        "machine_text_corrections": draft.get("machine_text_corrections"),
        "flagged_cue_count": len(flagged_cues),
        "flagged_cues": flagged_cues,
        "human_review_requirements": [
            "listen_to_every_cue_before_setting_review_status_verified",
            "resolve_all_cross_asr_disagreements_and_missing_evidence",
            "confirm_timing_at_every_edit_boundary",
            "recheck_every_machine_text_correction_against_audio",
        ],
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }


def build_subtitle_review_record(
    draft: dict[str, Any],
    *,
    draft_path: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    risk_counts: dict[str, int] = {}
    for cue in draft.get("cues", []):
        for flag in cue.get("risk_flags", []):
            risk_counts[flag] = risk_counts.get(flag, 0) + 1
    return {
        "schema_version": "1.0",
        "document_type": "subtitle_review_record",
        "project_id": draft.get("project_id"),
        "subtitle_version": draft.get("subtitle_version"),
        "status": "review_required",
        "coverage": {"status": "pending"},
        "draft": draft_path,
        "summary": {
            "cue_count": len(draft.get("cues", [])),
            "reviewed_cue_count": 0,
            "remaining_cue_count": len(draft.get("cues", [])),
            "risk_cue_count": sum(
                bool(cue.get("risk_flags")) for cue in draft.get("cues", [])
            ),
            "risk_counts": dict(sorted(risk_counts.items())),
            "machine_crosscheck": draft.get("machine_crosscheck", {}).get(
                "summary"
            ),
            "machine_text_correction_count": draft.get(
                "machine_text_corrections", {}
            ).get("count", 0),
        },
        "machine_crosscheck": draft.get("machine_crosscheck"),
        "machine_text_corrections": draft.get("machine_text_corrections"),
        "readability": draft.get("readability"),
        "required_checks": [
            "audio_text_accuracy",
            "wording_and_proper_nouns",
            "sentence_break_and_punctuation",
            "start_and_end_timing",
            "cut_boundary_residue",
            "line_break_and_safe_layout",
        ],
        "segment_reviews": [
            {
                "segment_id": segment["segment_id"],
                "source": segment["source"],
                "actual_start_sec": segment["actual_start_sec"],
                "actual_end_sec": segment["actual_end_sec"],
                "draft_cue_count": segment["draft_cue_count"],
                "cross_asr_disagreement_cue_count": sum(
                    cue.get("segment_id") == segment["segment_id"]
                    and cue.get("cross_asr_evidence", {}).get("status")
                    == "disagreement"
                    for cue in draft.get("cues", [])
                ),
                "cross_asr_no_evidence_cue_count": sum(
                    cue.get("segment_id") == segment["segment_id"]
                    and cue.get("cross_asr_evidence", {}).get("status")
                    == "no_evidence"
                    for cue in draft.get("cues", [])
                ),
                "review_status": "review_required",
                "notes": [],
            }
            for segment in draft.get("segment_coverage", [])
        ],
        "cue_reviews": [
            {
                "cue_id": cue["cue_id"],
                "segment_id": cue["segment_id"],
                "start_sec": cue["start_sec"],
                "end_sec": cue["end_sec"],
                "risk_flags": cue.get("risk_flags", []),
                "cross_asr_evidence": cue.get("cross_asr_evidence"),
                "machine_text_correction": cue.get("machine_text_correction"),
                "review_status": "review_required",
                "checks": {
                    "audio_text_accuracy": "pending",
                    "wording_and_proper_nouns": "pending",
                    "sentence_break_and_punctuation": "pending",
                    "start_and_end_timing": "pending",
                    "cut_boundary_residue": "pending",
                    "line_break_and_safe_layout": "pending",
                },
                "notes": [],
            }
            for cue in draft.get("cues", [])
        ],
        "created_at": created_at or datetime.now(UTC).isoformat(),
    }


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, fraction = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{fraction:03d}"


def write_subtitle_review_bundle(
    draft: dict[str, Any],
    review_record: dict[str, Any],
    *,
    draft_output: Path,
    review_output: Path,
    srt_output: Path | None = None,
) -> None:
    for path, document in (
        (draft_output, draft),
        (review_output, review_record),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if srt_output is not None:
        srt_output.parent.mkdir(parents=True, exist_ok=True)
        blocks = []
        for cue_index, cue in enumerate(draft.get("cues", []), start=1):
            blocks.append(
                f"{cue_index}\n"
                f"{_srt_time(float(cue['start_sec']))} --> "
                f"{_srt_time(float(cue['end_sec']))}\n"
                f"{cue['text']}"
            )
        srt_output.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
