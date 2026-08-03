from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .subtitle_readability import select_high_risk_cue_ids


PREVIEW_MANIFEST_SCHEMA_VERSION = "1.0"
PREVIEW_RENDER_VERSION = "subtitle-only-libass-v1"
PROGRESS_VERSION = "subtitle-preview-progress-v1"
_SAFE_IDENTIFIER = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without a BOM")
    try:
        result = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label} contains non-finite JSON number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _finite_non_negative(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return result


def _confined_path(
    project: Path,
    path: Path,
    relative_root: str,
    label: str,
    *,
    must_exist: bool = True,
) -> Path:
    project = project.resolve()
    root = (project / relative_root).resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} must stay inside {relative_root}") from error
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def _cue_id(cue: Mapping[str, Any]) -> str:
    value = cue.get("cue_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("every subtitle cue requires a stable cue_id")
    return value.strip()


def _ordered_cues(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("cues")
    if not isinstance(raw, list) or not raw:
        raise ValueError("subtitle source requires a non-empty cues array")
    cues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("subtitle cues must be objects")
        cue = dict(item)
        cue_id = _cue_id(cue)
        if cue_id in seen:
            raise ValueError("subtitle cue IDs must be unique")
        seen.add(cue_id)
        start = _finite_non_negative(cue.get("start_sec"), f"{cue_id}.start_sec")
        end = _finite_non_negative(cue.get("end_sec"), f"{cue_id}.end_sec")
        if end <= start:
            raise ValueError(f"{cue_id}.end_sec must be greater than start_sec")
        if not isinstance(cue.get("text"), str) or not str(cue["text"]).strip():
            raise ValueError(f"{cue_id}.text must be non-empty")
        cue["start_sec"] = start
        cue["end_sec"] = end
        cues.append(cue)
    cues.sort(key=lambda cue: (cue["start_sec"], cue["end_sec"], _cue_id(cue)))
    for left, right in zip(cues, cues[1:]):
        if right["start_sec"] < left["end_sec"]:
            raise ValueError(f"subtitle cues overlap: {_cue_id(left)} and {_cue_id(right)}")
    return cues


def _timeline_segments(document: Mapping[str, Any]) -> tuple[float, list[dict[str, Any]]]:
    duration = _finite_non_negative(document.get("duration_sec"), "timeline.duration_sec")
    if duration <= 0:
        raise ValueError("timeline.duration_sec must be positive")
    raw = document.get("segments")
    if raw is None:
        raw = document.get("segment_measurements")
    if not isinstance(raw, list) or not raw:
        raise ValueError("realized timeline requires segment measurements")
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError("realized timeline segments must be objects")
        segment_id = str(item.get("segment_id", "")).strip()
        if not segment_id or segment_id in seen:
            raise ValueError("realized timeline segment IDs must be non-empty and unique")
        seen.add(segment_id)
        start = item.get("start_sec", item.get("actual_start_sec"))
        end = item.get("end_sec", item.get("actual_end_sec"))
        start_value = _finite_non_negative(start, f"timeline.segment-{index}.start")
        end_value = _finite_non_negative(end, f"timeline.segment-{index}.end")
        if end_value <= start_value or end_value > duration + 0.001:
            raise ValueError("realized timeline segment bounds are invalid")
        segments.append({"segment_id": segment_id, "start_sec": start_value, "end_sec": end_value})
    segments.sort(key=lambda segment: (segment["start_sec"], segment["end_sec"]))
    return duration, segments


def create_unique_preview_directory(project: Path) -> Path:
    project = project.resolve()
    root = project / "work" / "proxy" / "subtitle-preview"
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        identifier = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
        candidate = root / identifier
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate.resolve()
    raise FileExistsError("unable to allocate a unique subtitle preview directory")


def _slug(value: str) -> str:
    safe = _SAFE_IDENTIFIER.sub("-", value).strip("-._")[:64]
    return safe or hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def select_preview_units(
    subtitle_document: Mapping[str, Any],
    realized_timeline: Mapping[str, Any],
    *,
    scope: str,
    proxy_unit: str,
    padding_sec: float,
    high_risk_cue_ids: Iterable[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if scope not in {"all", "risk"}:
        raise ValueError("scope must be all or risk")
    if proxy_unit not in {"timeline", "cue", "segment", "chapter"}:
        raise ValueError("proxy_unit must be timeline, cue, segment, or chapter")
    if scope == "risk" and proxy_unit == "timeline":
        raise ValueError("risk scope cannot render the complete timeline")
    padding = _finite_non_negative(padding_sec, "padding_sec")
    cues = _ordered_cues(subtitle_document)
    duration, segments = _timeline_segments(realized_timeline)
    cue_by_id = {_cue_id(cue): cue for cue in cues}
    risk = {str(value) for value in high_risk_cue_ids}
    unknown = risk - set(cue_by_id)
    if unknown:
        raise ValueError("readability QA references unknown cue IDs: " + ", ".join(sorted(unknown)))
    trigger_ids = list(cue_by_id) if scope == "all" else [cue_id for cue_id in cue_by_id if cue_id in risk]
    segment_by_id = {segment["segment_id"]: segment for segment in segments}
    units: list[dict[str, Any]] = []

    if proxy_unit == "timeline":
        units.append({"unit_type": "timeline", "unit_id": "timeline", "start_sec": 0.0,
                      "end_sec": duration, "trigger_cue_ids": trigger_ids,
                      "rendered_cue_ids": list(cue_by_id)})
    elif proxy_unit == "cue":
        for cue_id in trigger_ids:
            cue = cue_by_id[cue_id]
            units.append({"unit_type": "cue", "unit_id": cue_id,
                          "start_sec": max(0.0, cue["start_sec"] - padding),
                          "end_sec": min(duration, cue["end_sec"] + padding),
                          "trigger_cue_ids": [cue_id], "rendered_cue_ids": [cue_id]})
    elif proxy_unit == "segment":
        grouped: dict[str, list[str]] = {}
        for cue_id in trigger_ids:
            segment_id = str(cue_by_id[cue_id].get("segment_id", "")).strip()
            if segment_id not in segment_by_id:
                raise ValueError(f"cue {cue_id} has no matching realized segment")
            grouped.setdefault(segment_id, []).append(cue_id)
        for segment in segments:
            segment_id = segment["segment_id"]
            if segment_id not in grouped:
                continue
            rendered = [_cue_id(cue) for cue in cues if str(cue.get("segment_id")) == segment_id]
            units.append({"unit_type": "segment", "unit_id": segment_id,
                          "start_sec": segment["start_sec"], "end_sec": segment["end_sec"],
                          "trigger_cue_ids": grouped[segment_id], "rendered_cue_ids": rendered})
    else:
        grouped_chapters: dict[str, list[str]] = {}
        for cue_id in trigger_ids:
            chapter_id = str(cue_by_id[cue_id].get("chapter_id", "")).strip()
            if not chapter_id:
                raise ValueError(f"cue {cue_id} has no chapter_id")
            grouped_chapters.setdefault(chapter_id, []).append(cue_id)
        for chapter_id, chapter_trigger_ids in grouped_chapters.items():
            chapter_cues = [cue for cue in cues if str(cue.get("chapter_id")) == chapter_id]
            segment_ids = {str(cue.get("segment_id")) for cue in chapter_cues}
            chapter_segments = [segment for segment in segments if segment["segment_id"] in segment_ids]
            if not chapter_segments:
                raise ValueError(f"chapter {chapter_id} has no matching realized segment")
            units.append({"unit_type": "chapter", "unit_id": chapter_id,
                          "start_sec": min(item["start_sec"] for item in chapter_segments),
                          "end_sec": max(item["end_sec"] for item in chapter_segments),
                          "trigger_cue_ids": chapter_trigger_ids,
                          "rendered_cue_ids": [_cue_id(cue) for cue in chapter_cues]})
        units.sort(key=lambda unit: (unit["start_sec"], unit["unit_id"]))

    rendered = {cue_id for unit in units for cue_id in unit["rendered_cue_ids"]}
    trigger_set = set(trigger_ids)
    selection = {
        "planned_cue_ids": list(cue_by_id),
        "selected_trigger_cue_ids": trigger_ids,
        "planned_rendered_cue_ids": [cue_id for cue_id in cue_by_id if cue_id in rendered],
        "missing_selected_cue_ids": [cue_id for cue_id in trigger_ids if cue_id not in rendered],
        "unrendered_due_to_scope_cue_ids": [
            cue_id for cue_id in cue_by_id if cue_id not in rendered and cue_id not in trigger_set
        ],
    }
    return units, selection


def render_subtitle_preview(**arguments: Any) -> dict[str, Any]:
    from .subtitle_preview_runtime import render_subtitle_preview as implementation

    return implementation(**arguments)


def submit_subtitle_preview_job(**arguments: Any) -> dict[str, Any]:
    from .subtitle_preview_runtime import submit_subtitle_preview_job as implementation

    return implementation(**arguments)


def run_subtitle_preview_job(job_spec: Path) -> dict[str, Any]:
    from .subtitle_preview_runtime import run_subtitle_preview_job as implementation

    return implementation(job_spec)
