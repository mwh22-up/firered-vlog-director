from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeVar

ABSOLUTE_MODEL_REQUEST_LIMIT = 200_000
DEFAULT_MODEL_CONTEXT_LIMIT = 180_000

_HUMOR_TERMS = (
    "哈哈",
    "笑",
    "尴尬",
    "社恐",
    "完了",
    "没票",
    "来不及",
    "怎么办",
    "崩溃",
    "奇怪",
    "不行了",
    "太贵",
)


class ModelContextLimitError(ValueError):
    """Raised before a request can cross the model character limit."""


T = TypeVar("T")


def validate_serialized_model_request(
    serialized: str,
    *,
    max_characters: int = ABSOLUTE_MODEL_REQUEST_LIMIT,
) -> None:
    if len(serialized) >= max_characters:
        raise ModelContextLimitError(
            "model request must be smaller than "
            f"{max_characters:,} characters; got {len(serialized):,}"
        )


def serialize_model_request(
    payload: dict[str, Any],
    *,
    max_characters: int = ABSOLUTE_MODEL_REQUEST_LIMIT,
) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    validate_serialized_model_request(
        serialized,
        max_characters=max_characters,
    )
    return serialized


def dispatch_model_request(
    payload: dict[str, Any],
    transport: Callable[[str], T],
    *,
    max_characters: int = ABSOLUTE_MODEL_REQUEST_LIMIT,
) -> T:
    """The only supported transport boundary for future model integrations."""
    serialized = serialize_model_request(
        payload,
        max_characters=max_characters,
    )
    return transport(serialized)


def build_reference_context_packet(
    analysis: dict[str, Any],
    *,
    max_characters: int = DEFAULT_MODEL_CONTEXT_LIMIT,
) -> dict[str, Any]:
    if not 10_000 <= max_characters < ABSOLUTE_MODEL_REQUEST_LIMIT:
        raise ValueError(
            "max_characters must be at least 10,000 and smaller than 200,000"
        )

    transcript = analysis.get("transcription", {})
    segments = transcript.get("segments", [])
    transcript_windows = _transcript_windows(segments)
    shots = _select_shots(analysis.get("shots", []))
    events = _select_evenly(
        [_compact_event(event) for event in analysis.get("events", [])],
        120,
    )
    music_segments = sorted(
        (
            _compact_audio_segment(segment)
            for segment in analysis.get("audio_segments", [])
            if segment.get("kind") == "music_likely"
        ),
        key=lambda row: row["duration_sec"],
        reverse=True,
    )[:80]

    packet: dict[str, Any] = {
        "schema_version": "1.0",
        "packet_kind": "bounded_reference_context",
        "source": deepcopy(analysis.get("source", {})),
        "configuration": deepcopy(analysis.get("configuration", {})),
        "media": deepcopy(analysis.get("media", {})),
        "transcription": {
            "status": transcript.get("status"),
            "provider": transcript.get("provider"),
            "model": transcript.get("model"),
            "language": transcript.get("language"),
            "segment_count": len(segments),
            "word_count": len(transcript.get("words", [])),
            "windows": transcript_windows,
        },
        "selected_shots": shots,
        "selected_events": events,
        "music_likely_segments": music_segments,
        "learning_summary": deepcopy(analysis.get("learning_summary", {})),
        "selection_notes": [
            "The full transcript, raw words, raw feature samples, and local media stay outside this packet.",
            "Transcript windows preserve chronological coverage and prioritize likely humor wording when compaction is required.",
            "Playback-rate and visual-effect claims still require manual frame review; they are not inferred from this packet alone.",
        ],
        "context_budget": {
            "maximum_characters": max_characters,
            "serialized_characters": 0,
            "hard_limit_characters": ABSOLUTE_MODEL_REQUEST_LIMIT,
            "comparison": "strictly_less_than",
        },
    }
    packet["source"].pop("media_path", None)

    _shrink_packet(packet, max_characters)
    _set_stable_character_count(packet)
    serialized = _pretty_json(packet)
    if len(serialized) >= max_characters:
        raise ModelContextLimitError(
            f"unable to compact reference packet below {max_characters:,} characters"
        )
    validate_serialized_model_request(serialized)
    return packet


def write_reference_context_packet(
    packet: dict[str, Any],
    output_path: Path,
) -> int:
    serialized = _pretty_json(packet)
    maximum = int(
        packet.get("context_budget", {}).get(
            "maximum_characters",
            DEFAULT_MODEL_CONTEXT_LIMIT,
        )
    )
    if len(serialized) >= maximum:
        raise ModelContextLimitError(
            f"context packet is {len(serialized):,} characters; limit is {maximum:,}"
        )
    validate_serialized_model_request(serialized)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized + "\n", encoding="utf-8")
    return len(serialized)


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _set_stable_character_count(packet: dict[str, Any]) -> None:
    for _ in range(8):
        size = len(_pretty_json(packet))
        if packet["context_budget"]["serialized_characters"] == size:
            return
        packet["context_budget"]["serialized_characters"] = size


def _shrink_packet(packet: dict[str, Any], maximum: int) -> None:
    _set_stable_character_count(packet)
    while len(_pretty_json(packet)) >= maximum:
        windows = packet["transcription"]["windows"]
        shots = packet["selected_shots"]
        events = packet["selected_events"]
        music = packet["music_likely_segments"]
        if len(windows) > 24:
            packet["transcription"]["windows"] = _priority_window_sample(
                windows,
                max(24, int(len(windows) * 0.8)),
            )
        elif len(shots) > 48:
            packet["selected_shots"] = _select_evenly(
                shots,
                max(48, int(len(shots) * 0.8)),
            )
        elif len(events) > 30:
            packet["selected_events"] = _select_evenly(
                events,
                max(30, int(len(events) * 0.8)),
            )
        elif len(music) > 20:
            packet["music_likely_segments"] = music[: max(20, int(len(music) * 0.8))]
        elif any(len(str(row.get("text", ""))) > 160 for row in windows):
            for row in windows:
                text = str(row.get("text", ""))
                if len(text) > 160:
                    row["text"] = text[:157] + "..."
                    row["text_truncated"] = True
        else:
            raise ModelContextLimitError(
                "reference packet has no remaining safe compaction step"
            )
        _set_stable_character_count(packet)


def _transcript_windows(
    segments: list[dict[str, Any]],
    *,
    window_sec: float = 60.0,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for segment in segments:
        start = float(segment.get("start_sec", 0.0))
        grouped.setdefault(int(start // window_sec), []).append(segment)
    windows = []
    for bucket, rows in sorted(grouped.items()):
        text = " ".join(
            str(row.get("text", "")).strip()
            for row in rows
            if str(row.get("text", "")).strip()
        )
        windows.append(
            {
                "start_sec": round(bucket * window_sec, 3),
                "end_sec": round(
                    max(float(row.get("end_sec", 0.0)) for row in rows),
                    3,
                ),
                "text": text,
                "segment_count": len(rows),
                "humor_signal": any(term in text for term in _HUMOR_TERMS),
            }
        )
    return windows


def _select_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not shots:
        return []
    indexes: set[int] = {
        index
        for index, shot in enumerate(shots)
        if float(shot.get("start_sec", 0.0)) < 120.0
    }
    for role in ("reaction", "payoff", "establishing", "dialogue", "action"):
        candidates = sorted(
            (
                (index, shot)
                for index, shot in enumerate(shots)
                if shot.get("role") == role
            ),
            key=lambda pair: float(pair[1].get("keep_score", 0.0)),
            reverse=True,
        )
        indexes.update(index for index, _ in candidates[:20])
    stride = max(1, len(shots) // 40)
    indexes.update(range(0, len(shots), stride))
    indexes.add(len(shots) - 1)
    selected = [_compact_shot(shots[index]) for index in sorted(indexes)]
    return _select_evenly(selected, 180)


def _compact_shot(shot: dict[str, Any]) -> dict[str, Any]:
    visual = shot.get("visual", {})
    audio = shot.get("audio", {})
    return {
        "shot_id": shot.get("shot_id"),
        "start_sec": shot.get("start_sec"),
        "end_sec": shot.get("end_sec"),
        "duration_sec": shot.get("duration_sec"),
        "role": shot.get("role"),
        "recommendation": shot.get("recommendation"),
        "keep_score": shot.get("keep_score"),
        "speech_ratio": shot.get("speech_ratio"),
        "motion": visual.get("motion"),
        "brightness": visual.get("brightness"),
        "sharpness": visual.get("sharpness"),
        "audio_kind": audio.get("kind"),
        "audio_rms": audio.get("rms"),
    }


def _compact_event(event: dict[str, Any]) -> dict[str, Any]:
    dependency = event.get("sequence_dependency", {})
    return {
        "event_id": event.get("event_id"),
        "start_sec": event.get("start_sec"),
        "end_sec": event.get("end_sec"),
        "event_type": event.get("event_type"),
        "shot_count": event.get("shot_count"),
        "priority_score": event.get("priority_score"),
        "recommendation": event.get("recommendation"),
        "setup_shot_id": dependency.get("setup_shot_id"),
        "payoff_shot_id": dependency.get("payoff_shot_id"),
        "reaction_shot_id": dependency.get("reaction_shot_id"),
    }


def _compact_audio_segment(segment: dict[str, Any]) -> dict[str, Any]:
    start = float(segment.get("start_sec", 0.0))
    end = float(segment.get("end_sec", start))
    return {
        "start_sec": start,
        "end_sec": end,
        "duration_sec": round(max(0.0, end - start), 3),
        "average_rms": segment.get("average_rms"),
        "peak": segment.get("peak"),
    }


def _priority_window_sample(
    rows: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    priority = {
        0,
        1,
        2,
        len(rows) - 3,
        len(rows) - 2,
        len(rows) - 1,
    }
    priority.update(
        index
        for index, row in enumerate(rows)
        if row.get("humor_signal")
    )
    selected = {index for index in priority if 0 <= index < len(rows)}
    if len(selected) > limit:
        return _select_evenly([rows[index] for index in sorted(selected)], limit)
    remaining = [index for index in range(len(rows)) if index not in selected]
    slots = limit - len(selected)
    if slots:
        selected.update(
            remaining[index]
            for index in _even_indexes(len(remaining), slots)
        )
    return [rows[index] for index in sorted(selected)]


def _select_evenly(rows: list[T], limit: int) -> list[T]:
    if len(rows) <= limit:
        return rows
    return [rows[index] for index in _even_indexes(len(rows), limit)]


def _even_indexes(length: int, count: int) -> list[int]:
    if count <= 0 or length <= 0:
        return []
    if count == 1:
        return [0]
    return sorted(
        {
            round(index * (length - 1) / (count - 1))
            for index in range(count)
        }
    )
