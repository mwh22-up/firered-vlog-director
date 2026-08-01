from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, TypeVar

ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT = 200_000
# Backward-compatible name for callers that imported the original constant.
ABSOLUTE_MODEL_REQUEST_LIMIT = ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT
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
    """Raised before context or a UTF-8 request body can cross its limit."""


T = TypeVar("T")


def _resolve_request_byte_limit(
    *,
    max_bytes: int | None,
    max_characters: int | None,
) -> int:
    if max_bytes is not None and max_characters is not None:
        raise ValueError("pass max_bytes or max_characters, not both")
    if max_characters is not None:
        warnings.warn(
            "max_characters is deprecated and is enforced as a UTF-8 byte "
            "limit; use max_bytes instead",
            DeprecationWarning,
            stacklevel=3,
        )
        maximum = max_characters
    else:
        maximum = (
            ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT
            if max_bytes is None
            else max_bytes
        )
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError("model request byte limit must be a positive integer")
    return maximum


def _reject_non_finite_json_constant(value: str) -> None:
    raise ValueError(f"model request contains non-finite JSON value: {value}")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"model request contains duplicate JSON field: {key}")
        result[key] = value
    return result


def _forbidden_credential_fields(payload: Any) -> set[str]:
    forbidden_names = {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "id_token",
        "refresh_token",
        "token",
        "x_api_key",
    }
    found: set[str] = set()
    pending = [payload]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            for key, nested in value.items():
                if isinstance(key, str):
                    normalized = key.lower().replace("-", "_")
                    if normalized in forbidden_names:
                        found.add(normalized)
                pending.append(nested)
        elif isinstance(value, list):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            pending.extend(value)
    return found


def validate_serialized_model_request(
    serialized: str,
    *,
    max_bytes: int | None = None,
    max_characters: int | None = None,
) -> None:
    """Reject a request at or above its UTF-8 byte ceiling.

    ``max_characters`` remains as a compatibility alias for the original API,
    but its value is intentionally enforced as bytes so legacy callers cannot
    bypass the upstream body-size gate with multibyte text.
    """
    maximum = _resolve_request_byte_limit(
        max_bytes=max_bytes,
        max_characters=max_characters,
    )
    size = serialized_model_request_size(serialized)
    if size["serialized_utf8_bytes"] >= maximum:
        raise ModelContextLimitError(
            "model request must be smaller than "
            f"{maximum:,} UTF-8 bytes; got "
            f"{size['serialized_utf8_bytes']:,} bytes across "
            f"{size['serialized_characters']:,} characters"
        )


def serialized_model_request_size(serialized: str) -> dict[str, int]:
    return {
        "serialized_characters": len(serialized),
        "serialized_utf8_bytes": len(serialized.encode("utf-8")),
    }


def serialize_model_request(
    payload: dict[str, Any],
    *,
    max_bytes: int | None = None,
    max_characters: int | None = None,
) -> str:
    if not isinstance(payload, dict):
        raise ValueError("model request payload must be an object")
    maximum = _resolve_request_byte_limit(
        max_bytes=max_bytes,
        max_characters=max_characters,
    )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    validate_serialized_model_request(
        serialized,
        max_bytes=maximum,
    )
    return serialized


def preflight_serialized_responses_request(
    serialized: str,
    *,
    max_bytes: int = ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT,
) -> dict[str, int | str]:
    """Validate the exact UTF-8 Responses body that a transport will send."""
    if serialized.startswith("\ufeff"):
        raise ValueError("model request must be UTF-8 without BOM")
    validate_serialized_model_request(serialized, max_bytes=max_bytes)
    try:
        payload = json.loads(
            serialized,
            parse_constant=_reject_non_finite_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"model request is not valid JSON: {error.msg}") from error
    validate_responses_request_payload(payload)
    encoded = serialized.encode("utf-8")
    return {
        **serialized_model_request_size(serialized),
        "body_sha256": sha256(encoded).hexdigest(),
    }


def validate_responses_request_payload(payload: Any) -> None:
    """Validate the required and typed fields of a Responses request body."""
    if not isinstance(payload, dict):
        raise ValueError("responses request body must be an object")
    if not all(isinstance(key, str) for key in payload):
        raise ValueError("responses request body fields must be strings")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("responses request model must be a non-empty string")
    if "input" not in payload or payload["input"] is None:
        raise ValueError("responses request input is required")
    input_data = payload["input"]
    if not isinstance(input_data, (str, list)) or isinstance(input_data, bool):
        raise ValueError("responses request input must be a string or a list")
    if isinstance(input_data, list) and not all(
        isinstance(item, dict) for item in input_data
    ):
        raise ValueError("responses request input list items must be objects")
    if "instructions" in payload and not isinstance(payload["instructions"], str):
        raise ValueError("responses request instructions must be a string")
    if "tools" in payload and not isinstance(payload["tools"], list):
        raise ValueError("responses request tools must be a list")
    if "tools" in payload and not all(
        isinstance(tool, dict)
        and isinstance(tool.get("type"), str)
        and bool(tool["type"].strip())
        for tool in payload["tools"]
    ):
        raise ValueError(
            "responses request tool entries must be objects with a non-empty type"
        )
    forbidden = _forbidden_credential_fields(payload)
    if forbidden:
        raise ValueError(
            "responses request body cannot contain credential fields: "
            + ", ".join(sorted(forbidden))
        )


def build_responses_request(
    model: str,
    input_data: Any,
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete JSON body for a Responses API request.

    Size validation must happen after model, instructions, input, tools, and
    protocol options are all present. ``dispatch_responses_request`` gives the
    transport the resulting immutable UTF-8 bytes; it must send them without
    wrapping them in another JSON object.
    """
    if request_options is not None and not isinstance(request_options, dict):
        raise ValueError("responses request options must be an object with string keys")
    options = deepcopy(request_options) if request_options is not None else {}
    if not all(
        isinstance(key, str) for key in options
    ):
        raise ValueError("responses request options must be an object with string keys")
    reserved = {"model", "input", "instructions", "tools"} & set(options)
    if reserved:
        raise ValueError(
            "responses request options cannot override reserved fields: "
            + ", ".join(sorted(reserved))
        )

    payload: dict[str, Any] = {"model": model}
    if instructions is not None:
        payload["instructions"] = instructions
    payload["input"] = deepcopy(input_data)
    if tools is not None:
        payload["tools"] = deepcopy(tools)
    payload.update(options)
    validate_responses_request_payload(payload)
    return payload


def dispatch_model_request(
    payload: dict[str, Any],
    transport: Callable[[str], T],
    *,
    max_bytes: int | None = None,
    max_characters: int | None = None,
) -> T:
    """Legacy string transport boundary with UTF-8 byte-size validation."""
    serialized = serialize_model_request(
        payload,
        max_bytes=max_bytes,
        max_characters=max_characters,
    )
    return transport(serialized)


def dispatch_responses_request(
    model: str,
    input_data: Any,
    transport: Callable[[bytes], T],
    *,
    instructions: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    request_options: dict[str, Any] | None = None,
    max_bytes: int = ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT,
) -> T:
    payload = build_responses_request(
        model,
        input_data,
        instructions=instructions,
        tools=tools,
        request_options=request_options,
    )
    serialized = serialize_model_request(
        payload,
        max_bytes=max_bytes,
    )
    return transport(serialized.encode("utf-8"))


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
            "The complete outer model request, including instructions and tools, must pass the UTF-8 byte preflight before transport.",
        ],
        "context_budget": {
            "maximum_characters": max_characters,
            "serialized_characters": 0,
            "serialized_utf8_bytes": 0,
            "hard_limit_characters": ABSOLUTE_MODEL_REQUEST_LIMIT,
            "hard_request_limit_utf8_bytes": ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT,
            "comparison": "strictly_less_than",
        },
    }
    packet["source"].pop("media_path", None)

    _shrink_packet(packet, max_characters)
    _set_stable_size_counts(packet)
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
    _set_stable_size_counts(packet)
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
    output_path.write_bytes(serialized.encode("utf-8"))
    return len(serialized)


def _pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)


def _set_stable_size_counts(packet: dict[str, Any]) -> None:
    for _ in range(12):
        size = serialized_model_request_size(_pretty_json(packet))
        budget = packet["context_budget"]
        if (
            budget.get("serialized_characters") == size["serialized_characters"]
            and budget.get("serialized_utf8_bytes") == size["serialized_utf8_bytes"]
        ):
            return
        budget.update(size)


def _shrink_packet(packet: dict[str, Any], maximum: int) -> None:
    _set_stable_size_counts(packet)
    while True:
        serialized = _pretty_json(packet)
        size = serialized_model_request_size(serialized)
        if (
            size["serialized_characters"] < maximum
            and size["serialized_utf8_bytes"] < ABSOLUTE_MODEL_REQUEST_BYTE_LIMIT
        ):
            return
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
                "reference packet has no remaining safe compaction step; "
                f"got {size['serialized_characters']:,} characters and "
                f"{size['serialized_utf8_bytes']:,} UTF-8 bytes"
            )
        _set_stable_size_counts(packet)


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
