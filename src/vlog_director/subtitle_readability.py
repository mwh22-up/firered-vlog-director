from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, fields
from typing import Any, Iterable, Mapping


READABILITY_POLICY_VERSION = "1.0"
READABILITY_QA_SCHEMA_VERSION = "1.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LATIN_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")
TERMINAL_PUNCTUATION = frozenset("。！？!?；;")
HIGH_RISK_WARNING_CODES = frozenset(
    {
        "near_edit_boundary",
        "machine_text_correction_requires_review",
        "cross_asr_disagreement_requires_review",
        "cross_asr_evidence_missing",
        "zero_duration_word_timing_requires_review",
    }
)
HIGH_RISK_SOURCE_FLAGS = frozenset(
    {
        "machine_text_corrected_review_required",
        "cross_asr_disagreement",
        "cross_asr_no_evidence",
        "source_boundary_clipped",
        "zero_duration_word_timing",
        "line_limit_exceeded",
        "near_cut_in",
        "near_cut_out",
    }
)


def _strict_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    exclusive_minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a real number, not bool")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    if exclusive_minimum is not None and number <= exclusive_minimum:
        raise ValueError(f"{field} must be greater than {exclusive_minimum}")
    return number


def _strict_integer(
    value: Any,
    field: str,
    *,
    minimum: int = 1,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer, not bool")
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _strict_boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


@dataclass(frozen=True)
class SubtitleReadabilityPolicy:
    """Versioned subtitle readability limits shared by preview and release gates."""

    policy_version: str = READABILITY_POLICY_VERSION
    min_duration_sec: float = 0.8
    max_duration_sec: float = 5.5
    min_gap_sec: float = 0.08
    max_merge_gap_sec: float = 0.65
    zh_max_chars_per_sec: float = 8.0
    latin_max_words_per_sec: float = 3.0
    latin_max_chars_per_sec: float = 15.0
    max_lines: int = 2
    max_chars_per_line: int = 18
    cut_boundary_tolerance_sec: float = 0.3
    allow_auto_merge: bool = True
    allow_safe_extension: bool = True
    preview_violation_action: str = "warn"
    release_violation_action: str = "block"

    def __post_init__(self) -> None:
        if self.policy_version != READABILITY_POLICY_VERSION:
            raise ValueError(
                f"unsupported policy_version: {self.policy_version!r}"
            )
        min_duration = _strict_number(
            self.min_duration_sec,
            "min_duration_sec",
            exclusive_minimum=0,
        )
        max_duration = _strict_number(
            self.max_duration_sec,
            "max_duration_sec",
            exclusive_minimum=0,
        )
        min_gap = _strict_number(self.min_gap_sec, "min_gap_sec", minimum=0)
        max_merge_gap = _strict_number(
            self.max_merge_gap_sec,
            "max_merge_gap_sec",
            minimum=0,
        )
        _strict_number(
            self.zh_max_chars_per_sec,
            "zh_max_chars_per_sec",
            exclusive_minimum=0,
        )
        _strict_number(
            self.latin_max_words_per_sec,
            "latin_max_words_per_sec",
            exclusive_minimum=0,
        )
        _strict_number(
            self.latin_max_chars_per_sec,
            "latin_max_chars_per_sec",
            exclusive_minimum=0,
        )
        max_lines = _strict_integer(self.max_lines, "max_lines")
        _strict_integer(self.max_chars_per_line, "max_chars_per_line")
        _strict_number(
            self.cut_boundary_tolerance_sec,
            "cut_boundary_tolerance_sec",
            minimum=0,
        )
        _strict_boolean(self.allow_auto_merge, "allow_auto_merge")
        _strict_boolean(self.allow_safe_extension, "allow_safe_extension")
        if min_duration > max_duration:
            raise ValueError(
                "min_duration_sec cannot exceed max_duration_sec"
            )
        if min_gap > max_duration:
            raise ValueError("min_gap_sec cannot exceed max_duration_sec")
        if max_merge_gap > max_duration:
            raise ValueError("max_merge_gap_sec cannot exceed max_duration_sec")
        if max_lines not in {1, 2}:
            raise ValueError("max_lines must be one or two")
        if self.preview_violation_action != "warn":
            raise ValueError("preview_violation_action must be 'warn'")
        if self.release_violation_action != "block":
            raise ValueError("release_violation_action must be 'block'")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "SubtitleReadabilityPolicy":
        if not isinstance(document, Mapping):
            raise ValueError("subtitle readability policy must be an object")
        allowed = {item.name for item in fields(cls)}
        unknown = sorted(set(document) - allowed)
        if unknown:
            raise ValueError("unknown policy fields: " + ", ".join(unknown))
        return cls(**dict(document))


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value is not canonical JSON") from error
    return serialized.encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _round_metric(value: float) -> float:
    return round(value, 6)


def _identity_number(value: Any, field: str) -> float:
    return round(_strict_number(value, field), 6)


def stable_cue_identity(cue: Mapping[str, Any]) -> str:
    """Return an order-independent identity derived from source evidence when present."""

    if not isinstance(cue, Mapping):
        raise ValueError("subtitle cue must be an object")
    provenance = cue.get("asr_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    word_refs: list[dict[str, Any]] = []
    raw_word_refs = provenance.get("word_refs", [])
    if isinstance(raw_word_refs, list):
        for raw in raw_word_refs:
            if not isinstance(raw, Mapping):
                continue
            word_ref: dict[str, Any] = {
                "asr_segment_id": str(raw.get("asr_segment_id", "")),
                "word_index": raw.get("word_index"),
            }
            for field in ("source_start_sec", "source_end_sec"):
                if raw.get(field) is not None:
                    word_ref[field] = _identity_number(raw[field], field)
            word_refs.append(word_ref)
    word_refs.sort(
        key=lambda item: (
            float(item.get("source_start_sec", 0.0)),
            float(item.get("source_end_sec", 0.0)),
            str(item.get("asr_segment_id", "")),
            str(item.get("word_index", "")),
        )
    )

    source_identity_available = bool(
        word_refs
        or cue.get("source_id")
        or cue.get("source")
        or cue.get("source_start_sec") is not None
        or cue.get("source_end_sec") is not None
    )
    identity: dict[str, Any] = {
        "identity_version": "subtitle-cue-source-v1",
        "segment_id": str(cue.get("segment_id", "")),
        "chapter_id": str(cue.get("chapter_id", "")),
    }
    if source_identity_available:
        identity.update(
            {
                "source": str(cue.get("source", "")),
                "source_id": str(cue.get("source_id", "")),
                "analysis_source_id": str(
                    provenance.get("analysis_source_id", "")
                ),
                "word_refs": word_refs,
            }
        )
        for field in ("source_start_sec", "source_end_sec"):
            if cue.get(field) is not None:
                identity[field] = _identity_number(cue[field], field)
    else:
        identity.update(
            {
                "fallback_start_sec": _identity_number(
                    cue.get("start_sec"), "start_sec"
                ),
                "fallback_end_sec": _identity_number(
                    cue.get("end_sec"), "end_sec"
                ),
                "fallback_text_sha256": hashlib.sha256(
                    _normalize_newlines(str(cue.get("text", ""))).encode("utf-8")
                ).hexdigest(),
            }
        )
    return _canonical_digest(identity)


def stable_cue_id(cue: Mapping[str, Any], *, prefix: str = "subtitle") -> str:
    explicit = cue.get("cue_id") if isinstance(cue, Mapping) else None
    if explicit is not None:
        explicit_value = str(explicit).strip()
        if not explicit_value:
            raise ValueError("cue_id must be non-empty when provided")
        return explicit_value
    safe_prefix = str(prefix).strip()
    if not safe_prefix or any(character.isspace() for character in safe_prefix):
        raise ValueError("cue ID prefix must be non-empty and contain no whitespace")
    return f"{safe_prefix}-{stable_cue_identity(cue)[:20]}"


def _prepared_cues(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_cues = document.get("cues")
    if not isinstance(raw_cues, list):
        raise ValueError("subtitle document cues must be an array")
    prepared: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_cues:
        if not isinstance(raw, Mapping):
            raise ValueError("subtitle cues must be objects")
        cue_id = stable_cue_id(raw)
        if cue_id in seen_ids:
            raise ValueError(f"duplicate subtitle cue_id: {cue_id}")
        seen_ids.add(cue_id)
        text = _normalize_newlines(str(raw.get("text", "")))
        if not text:
            raise ValueError(f"subtitle text must be non-empty: {cue_id}")
        risk_flags = raw.get("risk_flags", [])
        if not isinstance(risk_flags, list) or any(
            not isinstance(flag, str) or not flag for flag in risk_flags
        ):
            raise ValueError(f"subtitle risk_flags must be strings: {cue_id}")
        prepared.append(
            {
                "raw": raw,
                "cue_id": cue_id,
                "cue_identity": stable_cue_identity(raw),
                "segment_id": str(raw.get("segment_id", "")),
                "chapter_id": str(raw.get("chapter_id", "")),
                "start_sec": _strict_number(raw.get("start_sec"), "start_sec"),
                "end_sec": _strict_number(raw.get("end_sec"), "end_sec"),
                "text": text,
                "position": str(raw.get("position", "")),
                "review_status": str(raw.get("review_status", "")),
                "source_risk_flags": list(dict.fromkeys(risk_flags)),
            }
        )
    prepared.sort(
        key=lambda cue: (cue["start_sec"], cue["end_sec"], cue["cue_id"])
    )
    return prepared


def _segment_boundaries(document: Mapping[str, Any]) -> dict[str, tuple[float, float]]:
    raw_segments = document.get("segment_coverage", [])
    if raw_segments is None:
        return {}
    if not isinstance(raw_segments, list):
        raise ValueError("segment_coverage must be an array")
    boundaries: dict[str, tuple[float, float]] = {}
    for raw in raw_segments:
        if not isinstance(raw, Mapping):
            raise ValueError("segment_coverage entries must be objects")
        segment_id = str(raw.get("segment_id", "")).strip()
        if not segment_id:
            raise ValueError("segment_coverage requires segment_id")
        if segment_id in boundaries:
            raise ValueError(f"duplicate segment boundary: {segment_id}")
        start_value = raw.get("actual_start_sec", raw.get("start_sec"))
        end_value = raw.get("actual_end_sec", raw.get("end_sec"))
        start = _strict_number(start_value, "segment.actual_start_sec", minimum=0)
        end = _strict_number(end_value, "segment.actual_end_sec", minimum=0)
        if end <= start:
            raise ValueError(f"segment boundary runs backwards: {segment_id}")
        boundaries[segment_id] = (start, end)
    return boundaries


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x20000 <= codepoint <= 0x2FA1F
    )


def _is_visible_character(character: str) -> bool:
    if character.isspace():
        return False
    category = unicodedata.category(character)
    return not category.startswith(("P", "Z", "C"))


def _text_metrics(text: str, duration: float) -> dict[str, Any]:
    visible = [character for character in text if _is_visible_character(character)]
    zh_count = sum(_is_han(character) for character in visible)
    latin_count = sum(
        character.isascii() and character.isalnum() for character in visible
    )
    latin_words = LATIN_WORD_PATTERN.findall(text)
    lines = text.split("\n")
    line_visible_counts = [
        sum(_is_visible_character(character) for character in line) for line in lines
    ]
    positive_duration = duration if duration > 0 else None
    return {
        "visible_char_count": len(visible),
        "zh_visible_char_count": zh_count,
        "latin_visible_char_count": latin_count,
        "latin_word_count": len(latin_words),
        "zh_chars_per_sec": (
            _round_metric(zh_count / positive_duration)
            if positive_duration is not None
            else 0.0
        ),
        "latin_words_per_sec": (
            _round_metric(len(latin_words) / positive_duration)
            if positive_duration is not None
            else 0.0
        ),
        "latin_chars_per_sec": (
            _round_metric(latin_count / positive_duration)
            if positive_duration is not None
            else 0.0
        ),
        "line_count": len(lines),
        "max_line_visible_char_count": max(line_visible_counts, default=0),
    }


def _wrap_for_policy(text: str, policy: SubtitleReadabilityPolicy) -> str | None:
    normalized = " ".join(_normalize_newlines(text).split())
    if not normalized:
        return None
    visible_total = sum(_is_visible_character(character) for character in normalized)
    if visible_total <= policy.max_chars_per_line:
        return normalized
    if policy.max_lines == 1 or visible_total > (
        policy.max_lines * policy.max_chars_per_line
    ):
        return None
    candidates: list[tuple[int, int, int, str, str]] = []
    for index in range(1, len(normalized)):
        left = normalized[:index].strip()
        right = normalized[index:].strip()
        if not left or not right:
            continue
        left_count = sum(_is_visible_character(character) for character in left)
        right_count = sum(_is_visible_character(character) for character in right)
        if (
            left_count <= policy.max_chars_per_line
            and right_count <= policy.max_chars_per_line
        ):
            preferred = normalized[index - 1] in "，。！？；：、,.!?;: "
            candidates.append(
                (
                    0 if preferred else 1,
                    max(left_count, right_count),
                    abs(left_count - right_count),
                    left,
                    right,
                )
            )
    if not candidates:
        return None
    _, _, _, left, right = min(candidates, key=lambda item: item[:3])
    return f"{left}\n{right}"


def _join_subtitle_text(left: str, right: str) -> str:
    left_flat = " ".join(_normalize_newlines(left).split())
    right_flat = " ".join(_normalize_newlines(right).split())
    if not left_flat:
        return right_flat
    if not right_flat:
        return left_flat
    add_space = (
        left_flat[-1].isascii()
        and left_flat[-1].isalnum()
        and right_flat[0].isascii()
        and right_flat[0].isalnum()
    )
    return left_flat + (" " if add_space else "") + right_flat


def _proposal_fits(
    start: float,
    end: float,
    text: str,
    policy: SubtitleReadabilityPolicy,
) -> tuple[bool, str | None]:
    duration = end - start
    if duration < policy.min_duration_sec or duration > policy.max_duration_sec:
        return False, None
    laid_out = _wrap_for_policy(text, policy)
    if laid_out is None:
        return False, None
    metrics = _text_metrics(laid_out, duration)
    if metrics["zh_chars_per_sec"] > policy.zh_max_chars_per_sec:
        return False, None
    if metrics["latin_words_per_sec"] > policy.latin_max_words_per_sec:
        return False, None
    if metrics["latin_chars_per_sec"] > policy.latin_max_chars_per_sec:
        return False, None
    return True, laid_out


def _cue_state(cues: list[dict[str, Any]], *, text: str | None = None) -> dict[str, Any]:
    return {
        "cue_ids": [cue["cue_id"] for cue in cues],
        "start_sec": _round_metric(min(cue["start_sec"] for cue in cues)),
        "end_sec": _round_metric(max(cue["end_sec"] for cue in cues)),
        "text": text if text is not None else "\n".join(cue["text"] for cue in cues),
    }


def _repair_document(
    repair_type: str,
    targets: list[dict[str, Any]],
    proposed: dict[str, Any],
    evidence: list[str],
) -> dict[str, Any]:
    core = {
        "type": repair_type,
        "target_cue_ids": [cue["cue_id"] for cue in targets],
        "original": _cue_state(targets),
        "proposed": proposed,
        "reason": "duration_below_minimum",
        "evidence": evidence,
        "review_required": True,
    }
    return {
        "repair_id": f"subtitle-repair-{_canonical_digest(core)[:20]}",
        **core,
    }


def plan_safe_readability_repairs(
    subtitle_document: Mapping[str, Any],
    *,
    policy: SubtitleReadabilityPolicy | None = None,
) -> list[dict[str, Any]]:
    """Plan deterministic repairs without mutating text or review state."""

    if not isinstance(subtitle_document, Mapping):
        raise ValueError("subtitle document must be an object")
    active_policy = policy or SubtitleReadabilityPolicy()
    cues = _prepared_cues(subtitle_document)
    boundaries = _segment_boundaries(subtitle_document)
    repairs: list[dict[str, Any]] = []
    consumed: set[str] = set()

    for index, cue in enumerate(cues):
        duration = cue["end_sec"] - cue["start_sec"]
        if duration >= active_policy.min_duration_sec or cue["cue_id"] in consumed:
            continue

        if active_policy.allow_auto_merge:
            candidates: list[
                tuple[int, float, int, list[dict[str, Any]], str]
            ] = []
            for direction, neighbor_index in ((0, index - 1), (1, index + 1)):
                if not 0 <= neighbor_index < len(cues):
                    continue
                neighbor = cues[neighbor_index]
                if neighbor["cue_id"] in consumed:
                    continue
                if (
                    not cue["segment_id"]
                    or cue["segment_id"] != neighbor["segment_id"]
                ):
                    continue
                pair = sorted(
                    [cue, neighbor],
                    key=lambda item: (
                        item["start_sec"],
                        item["end_sec"],
                        item["cue_id"],
                    ),
                )
                gap = pair[1]["start_sec"] - pair[0]["end_sec"]
                if gap < 0 or gap > active_policy.max_merge_gap_sec:
                    continue
                combined_text = _join_subtitle_text(
                    pair[0]["text"], pair[1]["text"]
                )
                fits, laid_out = _proposal_fits(
                    pair[0]["start_sec"],
                    pair[1]["end_sec"],
                    combined_text,
                    active_policy,
                )
                if not fits or laid_out is None:
                    continue
                semantic_penalty = int(
                    pair[0]["text"].rstrip()[-1:] in TERMINAL_PUNCTUATION
                )
                candidates.append(
                    (semantic_penalty, gap, direction, pair, laid_out)
                )
            if candidates:
                _, gap, _, targets, laid_out = min(
                    candidates,
                    key=lambda item: (item[0], item[1], item[2], item[3][0]["cue_id"]),
                )
                proposed = {
                    "cue_ids": [cue_item["cue_id"] for cue_item in targets],
                    "start_sec": _round_metric(targets[0]["start_sec"]),
                    "end_sec": _round_metric(targets[-1]["end_sec"]),
                    "text": laid_out,
                }
                repairs.append(
                    _repair_document(
                        "merge",
                        targets,
                        proposed,
                        [
                            "same_realized_segment",
                            f"non_overlapping_gap_sec={_round_metric(gap)}",
                            "combined_duration_within_policy",
                            "combined_layout_and_reading_speed_within_policy",
                            "dialogue_order_preserved",
                        ],
                    )
                )
                consumed.update(target["cue_id"] for target in targets)
                continue

        if active_policy.allow_safe_extension:
            segment_boundary = boundaries.get(cue["segment_id"])
            if segment_boundary is None:
                continue
            desired_end = cue["start_sec"] + active_policy.min_duration_sec
            maximum_end = segment_boundary[1]
            if index + 1 < len(cues):
                maximum_end = min(
                    maximum_end,
                    cues[index + 1]["start_sec"] - active_policy.min_gap_sec,
                )
            if desired_end <= cue["end_sec"] or desired_end > maximum_end + 1e-9:
                continue
            fits, laid_out = _proposal_fits(
                cue["start_sec"],
                desired_end,
                cue["text"],
                active_policy,
            )
            if not fits or laid_out is None:
                continue
            proposed = {
                "cue_ids": [cue["cue_id"]],
                "start_sec": _round_metric(cue["start_sec"]),
                "end_sec": _round_metric(desired_end),
                "text": laid_out,
            }
            repairs.append(
                _repair_document(
                    "extend",
                    [cue],
                    proposed,
                    [
                        "same_realized_segment",
                        "extension_ends_before_next_cue_minimum_gap",
                        "extension_does_not_cross_edit_boundary",
                        "text_unchanged",
                    ],
                )
            )
            consumed.add(cue["cue_id"])

    repairs.sort(key=lambda item: (item["original"]["start_sec"], item["repair_id"]))
    return repairs


def canonical_subtitle_payload_digest(document: Mapping[str, Any]) -> str:
    if not isinstance(document, Mapping):
        raise ValueError("subtitle document must be an object")
    cues = _prepared_cues(document)
    payload = {
        "digest_version": "subtitle-payload-v1",
        "project_id": document.get("project_id"),
        "subtitle_version": document.get("subtitle_version"),
        "language": document.get("language"),
        "cues": sorted(
            [
                {
                    "cue_id": cue["cue_id"],
                    "cue_identity": cue["cue_identity"],
                    "segment_id": cue["segment_id"],
                    "chapter_id": cue["chapter_id"],
                    "start_sec": _round_metric(cue["start_sec"]),
                    "end_sec": _round_metric(cue["end_sec"]),
                    "text": cue["text"],
                    "position": cue["position"],
                    "review_status": cue["review_status"],
                }
                for cue in cues
            ],
            key=lambda item: item["cue_id"],
        ),
    }
    return _canonical_digest(payload)


def canonical_subtitle_style_digest(style: Mapping[str, Any]) -> str:
    if not isinstance(style, Mapping):
        raise ValueError("subtitle style must be an object")
    return _canonical_digest(
        {
            "digest_version": "subtitle-style-v1",
            "style": dict(style),
        }
    )


def canonical_verified_cue_set_digest(
    cues_or_ids: Iterable[Mapping[str, Any] | str],
) -> str:
    verified_ids: list[str] = []
    for item in cues_or_ids:
        if isinstance(item, str):
            cue_id = item.strip()
            if not cue_id:
                raise ValueError("verified cue IDs must be non-empty")
            verified_ids.append(cue_id)
            continue
        if not isinstance(item, Mapping):
            raise ValueError("verified cue set must contain cue objects or IDs")
        if item.get("review_status") != "verified":
            continue
        verified_ids.append(stable_cue_id(item))
    if len(verified_ids) != len(set(verified_ids)):
        raise ValueError("verified cue IDs must be unique")
    return _canonical_digest(
        {
            "digest_version": "verified-cue-set-v1",
            "cue_ids": sorted(verified_ids),
        }
    )


def _cut_proximity(
    cue: Mapping[str, Any],
    boundaries: Mapping[str, tuple[float, float]],
    policy: SubtitleReadabilityPolicy,
) -> dict[str, Any]:
    boundary = boundaries.get(str(cue["segment_id"]))
    if boundary is None:
        return {
            "boundary_known": False,
            "nearest_boundary": None,
            "distance_sec": None,
            "within_tolerance": False,
            "crosses_boundary": False,
        }
    segment_start, segment_end = boundary
    distance_start = abs(float(cue["start_sec"]) - segment_start)
    distance_end = abs(segment_end - float(cue["end_sec"]))
    nearest = "start" if distance_start <= distance_end else "end"
    distance = min(distance_start, distance_end)
    return {
        "boundary_known": True,
        "nearest_boundary": nearest,
        "distance_sec": _round_metric(distance),
        "within_tolerance": distance <= policy.cut_boundary_tolerance_sec,
        "crosses_boundary": (
            float(cue["start_sec"]) < segment_start - 1e-9
            or float(cue["end_sec"]) > segment_end + 1e-9
        ),
    }


def _source_flag_issues(source_flags: Iterable[str]) -> tuple[list[str], list[str]]:
    source = set(source_flags)
    blockers: list[str] = []
    warnings: list[str] = []
    if "source_boundary_clipped" in source:
        blockers.append("unresolved_cut_boundary_risk")
    if "line_limit_exceeded" in source:
        blockers.append("source_line_limit_exceeded")
    if "zero_duration_word_timing" in source:
        warnings.append("zero_duration_word_timing_requires_review")
    if "machine_text_corrected_review_required" in source:
        warnings.append("machine_text_correction_requires_review")
    if "cross_asr_disagreement" in source:
        warnings.append("cross_asr_disagreement_requires_review")
    if "cross_asr_no_evidence" in source:
        warnings.append("cross_asr_evidence_missing")
    if source & {"near_cut_in", "near_cut_out"}:
        warnings.append("near_edit_boundary")
    return blockers, warnings


def select_high_risk_cue_ids(readability_qa: Mapping[str, Any]) -> list[str]:
    if not isinstance(readability_qa, Mapping):
        raise ValueError("readability QA must be an object")
    cues = readability_qa.get("cues")
    if not isinstance(cues, list):
        raise ValueError("readability QA cues must be an array")
    selected: list[str] = []
    for cue in cues:
        if not isinstance(cue, Mapping):
            raise ValueError("readability QA cues must be objects")
        cue_id = str(cue.get("cue_id", "")).strip()
        if not cue_id:
            raise ValueError("readability QA cue_id must be non-empty")
        blocker_codes = cue.get("blocker_codes", [])
        warning_codes = cue.get("warning_codes", [])
        source_flags = cue.get("source_risk_flags", [])
        if not all(
            isinstance(items, list)
            for items in (blocker_codes, warning_codes, source_flags)
        ):
            raise ValueError("readability QA risk code fields must be arrays")
        high_risk = bool(blocker_codes) or bool(
            set(warning_codes) & HIGH_RISK_WARNING_CODES
        ) or bool(set(source_flags) & HIGH_RISK_SOURCE_FLAGS)
        if cue.get("proposed_repair") is not None:
            high_risk = True
        if high_risk and cue_id not in selected:
            selected.append(cue_id)
    return selected


def audit_subtitle_readability(
    subtitle_document: Mapping[str, Any],
    *,
    policy: SubtitleReadabilityPolicy | None = None,
    mode: str = "preview",
    subtitle_source_sha256: str,
    realized_timeline_sha256: str,
) -> dict[str, Any]:
    if not isinstance(subtitle_document, Mapping):
        raise ValueError("subtitle document must be an object")
    if mode not in {"preview", "release"}:
        raise ValueError("readability mode must be preview or release")
    for value, field in (
        (subtitle_source_sha256, "subtitle_source_sha256"),
        (realized_timeline_sha256, "realized_timeline_sha256"),
    ):
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")

    active_policy = policy or SubtitleReadabilityPolicy()
    cues = _prepared_cues(subtitle_document)
    boundaries = _segment_boundaries(subtitle_document)
    repairs = plan_safe_readability_repairs(
        subtitle_document,
        policy=active_policy,
    )
    repair_by_cue: dict[str, dict[str, Any]] = {}
    for repair in repairs:
        for cue_id in repair["target_cue_ids"]:
            repair_by_cue[cue_id] = repair

    previous_gaps: list[float | None] = [None] * len(cues)
    next_gaps: list[float | None] = [None] * len(cues)
    overlap_ids: set[str] = set()
    short_gap_ids: set[str] = set()
    for index, (left, right) in enumerate(zip(cues, cues[1:])):
        gap = right["start_sec"] - left["end_sec"]
        next_gaps[index] = gap
        previous_gaps[index + 1] = gap
        if gap < 0:
            overlap_ids.update({left["cue_id"], right["cue_id"]})
        elif gap < active_policy.min_gap_sec:
            short_gap_ids.update({left["cue_id"], right["cue_id"]})

    qa_cues: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        duration = cue["end_sec"] - cue["start_sec"]
        metrics = _text_metrics(cue["text"], duration)
        blocker_codes: list[str] = []
        warning_codes: list[str] = []
        if cue["start_sec"] < 0 or cue["end_sec"] <= cue["start_sec"]:
            blocker_codes.append("invalid_cue_timing")
        if 0 < duration < active_policy.min_duration_sec:
            blocker_codes.append("duration_below_minimum")
        if duration > active_policy.max_duration_sec:
            blocker_codes.append("duration_above_maximum")
        if cue["cue_id"] in overlap_ids:
            blocker_codes.append("subtitle_overlap")
        if cue["cue_id"] in short_gap_ids:
            blocker_codes.append("gap_below_minimum")
        if metrics["zh_chars_per_sec"] > active_policy.zh_max_chars_per_sec:
            blocker_codes.append("zh_reading_speed_exceeded")
        if (
            metrics["latin_words_per_sec"]
            > active_policy.latin_max_words_per_sec
            or metrics["latin_chars_per_sec"]
            > active_policy.latin_max_chars_per_sec
        ):
            blocker_codes.append("latin_reading_speed_exceeded")
        if metrics["line_count"] > active_policy.max_lines:
            blocker_codes.append("line_count_exceeded")
        if metrics["max_line_visible_char_count"] > active_policy.max_chars_per_line:
            blocker_codes.append("line_length_exceeded")

        proximity = _cut_proximity(cue, boundaries, active_policy)
        if not proximity["boundary_known"]:
            blocker_codes.append("cut_boundary_evidence_missing")
        elif proximity["crosses_boundary"]:
            blocker_codes.append("cue_crosses_edit_boundary")
        elif proximity["within_tolerance"]:
            warning_codes.append("near_edit_boundary")

        source_blockers, source_warnings = _source_flag_issues(
            cue["source_risk_flags"]
        )
        blocker_codes.extend(source_blockers)
        warning_codes.extend(source_warnings)
        if mode == "release" and cue["review_status"] != "verified":
            blocker_codes.append("cue_not_verified")

        blocker_codes = list(dict.fromkeys(blocker_codes))
        warning_codes = list(dict.fromkeys(warning_codes))
        risk_level = (
            "blocker"
            if blocker_codes
            else "warning"
            if warning_codes
            else "none"
        )
        qa_cues.append(
            {
                "cue_id": cue["cue_id"],
                "cue_identity": cue["cue_identity"],
                "segment_id": cue["segment_id"],
                "chapter_id": cue["chapter_id"],
                "text_sha256": hashlib.sha256(
                    cue["text"].encode("utf-8")
                ).hexdigest(),
                "start_sec": _round_metric(cue["start_sec"]),
                "end_sec": _round_metric(cue["end_sec"]),
                "duration_sec": _round_metric(duration),
                **metrics,
                "previous_gap_sec": (
                    _round_metric(previous_gaps[index])
                    if previous_gaps[index] is not None
                    else None
                ),
                "next_gap_sec": (
                    _round_metric(next_gaps[index])
                    if next_gaps[index] is not None
                    else None
                ),
                "cut_proximity": proximity,
                "risk_level": risk_level,
                "blocker_codes": blocker_codes,
                "warning_codes": warning_codes,
                "source_risk_flags": cue["source_risk_flags"],
                "proposed_repair": repair_by_cue.get(cue["cue_id"]),
                "requires_human_review": bool(
                    blocker_codes
                    or warning_codes
                    or cue["review_status"] != "verified"
                    or repair_by_cue.get(cue["cue_id"])
                ),
            }
        )

    document_blocker_codes: list[str] = []
    document_warning_codes: list[str] = []
    coverage_status = (
        subtitle_document.get("coverage", {}).get("status")
        if isinstance(subtitle_document.get("coverage"), Mapping)
        else None
    )
    if mode == "release" and coverage_status != "verified":
        document_blocker_codes.append("subtitle_coverage_unverified")
    elif mode == "preview" and coverage_status != "verified":
        document_warning_codes.append("subtitle_coverage_pending")

    blocker_count = len(document_blocker_codes) + sum(
        len(cue["blocker_codes"]) for cue in qa_cues
    )
    warning_count = len(document_warning_codes) + sum(
        len(cue["warning_codes"]) for cue in qa_cues
    )
    if mode == "release" and blocker_count:
        status = "blocked"
    elif blocker_count or warning_count:
        status = "warnings"
    else:
        status = "passed"
    report: dict[str, Any] = {
        "schema_version": READABILITY_QA_SCHEMA_VERSION,
        "document_type": "subtitle_readability_qa",
        "policy_version": active_policy.policy_version,
        "project_id": str(subtitle_document.get("project_id", "")),
        "mode": mode,
        "status": status,
        "subtitle_source_sha256": subtitle_source_sha256,
        "realized_timeline_sha256": realized_timeline_sha256,
        "subtitle_payload_sha256": canonical_subtitle_payload_digest(
            subtitle_document
        ),
        "policy_sha256": _canonical_digest(active_policy.to_dict()),
        "cue_count": len(qa_cues),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "repair_count": len(repairs),
        "cue_ids": [cue["cue_id"] for cue in qa_cues],
        "high_risk_cue_ids": [],
        "document_blocker_codes": document_blocker_codes,
        "document_warning_codes": document_warning_codes,
        "policy": active_policy.to_dict(),
        "cues": qa_cues,
        "limitations": [
            "readability_metrics_do_not_verify_spoken_word_accuracy",
            "machine_repair_proposals_require_human_review",
            "character_and_word_rates_do_not_replace_real_libass_layout_evidence",
        ],
        "release_ready": mode == "release" and blocker_count == 0,
    }
    report["high_risk_cue_ids"] = select_high_risk_cue_ids(report)
    return report


__all__ = [
    "READABILITY_POLICY_VERSION",
    "READABILITY_QA_SCHEMA_VERSION",
    "SubtitleReadabilityPolicy",
    "audit_subtitle_readability",
    "canonical_subtitle_payload_digest",
    "canonical_subtitle_style_digest",
    "canonical_verified_cue_set_digest",
    "plan_safe_readability_repairs",
    "select_high_risk_cue_ids",
    "stable_cue_id",
    "stable_cue_identity",
]
