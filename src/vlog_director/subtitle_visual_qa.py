from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .ffmpeg import FFmpegError, filter_path, find_ffmpeg, require_filters
from .subtitle_layout_probe import inspect_ffmpeg_identity
from .subtitle_preview import (
    _canonical_sha256,
    _confined_path,
    _cue_id,
    _load_json,
    _ordered_cues,
    _relative,
    _sha256_file,
    _timeline_segments,
    _write_json,
)
from .subtitle_readability import select_high_risk_cue_ids


VISUAL_QA_SCHEMA_VERSION = "1.0"
VISUAL_QA_VERSION = "subtitle-visual-evidence-v1"
HUMAN_REVIEW_LIMITATION = "已生成视觉帧和布局证据，文字准确性仍需人工听校。"
_CATEGORIES = (
    "two_line",
    "dense_segment",
    "position_change",
    "cut_boundary",
    "ultra_short",
)


@lru_cache(maxsize=None)
def _runtime_validator(schema_name: str) -> Draft202012Validator:
    schema_path = Path(__file__).with_name("schemas") / schema_name
    with schema_path.open("r", encoding="utf-8") as source:
        schema = json.load(source)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_issues(document: Mapping[str, Any], schema_name: str) -> list[str]:
    errors = sorted(
        _runtime_validator(schema_name).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues = []
    for error in errors:
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        issues.append(f"{location}: {error.message}")
    return issues


def _schema_blocker(code: str, subject_id: str, issues: list[str]) -> dict[str, str]:
    return _issue(code, subject_id, "; ".join(issues))


def _issue(code: str, subject_id: str, message: str) -> dict[str, str]:
    return {"code": code, "subject_id": subject_id, "message": message}


def _bound_path(
    project: Path,
    binding: Mapping[str, Any],
    label: str,
    relative_root: str,
) -> Path:
    value = binding.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} binding has no path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label} binding path is not project-relative")
    resolved = (project / relative).resolve()
    allowed_root = (project / relative_root).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError(f"{label} binding path must stay under {relative_root}") from error
    return resolved


def _run(command: list[str], log_path: Path) -> bool:
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write("COMMAND " + json.dumps(command, ensure_ascii=False) + "\n")
        completed = subprocess.run(
            command,
            check=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        log.write(f"EXIT {completed.returncode}\n")
    return completed.returncode == 0


def _times(cue: Mapping[str, Any], output: Mapping[str, Any]) -> dict[str, float]:
    clip_start = float(output["clip_start_sec"])
    start = max(0.0, float(cue["start_sec"]) - clip_start)
    end = min(float(output["duration_sec"]), float(cue["end_sec"]) - clip_start)
    if end <= start:
        raise ValueError(f"output does not contain cue {_cue_id(cue)}")
    raw_fps = output.get("frame_rate")
    fps = (
        float(raw_fps)
        if isinstance(raw_fps, (int, float))
        and not isinstance(raw_fps, bool)
        and math.isfinite(float(raw_fps))
        and float(raw_fps) > 0
        else 25.0
    )
    step = 1.0 / fps
    middle = start + (end - start) / 2.0
    maximum = max(0.0, float(output["duration_sec"]) - step / 2.0)
    return {
        "entry": round(min(maximum, min(middle, start + step / 2.0)), 6),
        "middle": round(min(maximum, middle), 6),
        "exit": round(min(maximum, max(middle, end - step / 2.0)), 6),
    }


def _extract(
    executable: str,
    media: Path,
    time_sec: float,
    output: Path,
    log_path: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if not _run(
        [
            executable, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{time_sec:.6f}", "-i", str(media), "-map", "0:v:0",
            "-frames:v", "1", str(output),
        ],
        log_path,
    ):
        raise FFmpegError("subtitle visual QA frame extraction failed")


def _sheets(
    project: Path,
    category: str,
    cue_ids: list[str],
    middle_frames: Mapping[str, dict[str, Any]],
    output_directory: Path,
) -> list[dict[str, Any]]:
    available = [cue_id for cue_id in cue_ids if cue_id in middle_frames]
    if not available:
        return []
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("Pillow is required for subtitle visual QA") from error
    pages: list[dict[str, Any]] = []
    for offset in range(0, len(available), 12):
        page_ids = available[offset : offset + 12]
        cells = []
        try:
            for cue_id in page_ids:
                image = Image.open(project / middle_frames[cue_id]["path"]).convert("RGB")
                image.thumbnail((320, 180))
                cell = Image.new("RGB", (320, 208), "black")
                cell.paste(image, ((320 - image.width) // 2, (180 - image.height) // 2))
                ImageDraw.Draw(cell).text((6, 187), cue_id[:46], fill="white")
                image.close()
                cells.append(cell)
            columns = min(4, len(cells))
            rows = (len(cells) + columns - 1) // columns
            sheet = Image.new("RGB", (columns * 320, rows * 208), "black")
            for index, cell in enumerate(cells):
                sheet.paste(cell, ((index % columns) * 320, (index // columns) * 208))
            path = output_directory / f"{category}-{offset // 12 + 1:03d}.jpg"
            sheet.save(path, quality=90)
            sheet.close()
        finally:
            for cell in cells:
                cell.close()
        pages.append(
            {"path": _relative(project, path), "sha256": _sha256_file(path), "cue_ids": page_ids}
        )
    return pages


def _categories(
    cues: list[dict[str, Any]],
    readability: Mapping[str, Any] | None,
    layout: Mapping[str, Any] | None,
    timeline: Mapping[str, Any],
) -> dict[str, list[str]]:
    result = {name: [] for name in _CATEGORIES}
    layout_lines = {
        str(item.get("cue_id")): item.get("line_count")
        for item in (layout or {}).get("cues", [])
        if isinstance(item, dict)
    }
    for cue in cues:
        cue_id = _cue_id(cue)
        if "\n" in str(cue["text"]) or layout_lines.get(cue_id) == 2:
            result["two_line"].append(cue_id)
        if float(cue["end_sec"]) - float(cue["start_sec"]) < 0.8:
            result["ultra_short"].append(cue_id)
    for left, right in zip(cues, cues[1:]):
        if str(left.get("position", "bottom_center")) != str(
            right.get("position", "bottom_center")
        ):
            for cue_id in (_cue_id(left), _cue_id(right)):
                if cue_id not in result["position_change"]:
                    result["position_change"].append(cue_id)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cue in cues:
        grouped.setdefault(str(cue.get("segment_id", "")), []).append(cue)
    for segment_cues in grouped.values():
        if len(segment_cues) >= 4:
            result["dense_segment"].extend(_cue_id(cue) for cue in segment_cues)
    _, segments = _timeline_segments(timeline)
    boundaries = [float(segment["end_sec"]) for segment in segments[:-1]]
    for cue in cues:
        if any(
            abs(float(cue["start_sec"]) - boundary) <= 0.3
            or abs(float(cue["end_sec"]) - boundary) <= 0.3
            for boundary in boundaries
        ):
            result["cut_boundary"].append(_cue_id(cue))
    if readability:
        for item in readability.get("cues", []):
            if not isinstance(item, dict):
                continue
            codes = [
                *item.get("blocker_codes", []),
                *item.get("warning_codes", []),
                *item.get("source_risk_flags", []),
            ]
            cue_id = str(item.get("cue_id", ""))
            if cue_id and any("cut" in str(code) or "boundary" in str(code) for code in codes):
                if cue_id not in result["cut_boundary"]:
                    result["cut_boundary"].append(cue_id)
    return result


def qa_subtitles(
    *,
    project: Path,
    preview_manifest: Path,
    output: Path | None = None,
    evidence_directory: Path | None = None,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    project = Path(project).resolve()
    manifest_path = _confined_path(
        project, Path(preview_manifest), "work/proxy", "subtitle preview manifest"
    )
    manifest = _load_json(manifest_path, "subtitle preview manifest")
    manifest_schema_issues = _schema_issues(
        manifest,
        "subtitle-preview-manifest.schema.json",
    )
    manifest_sha = _sha256_file(manifest_path)
    if evidence_directory is None:
        evidence = project / "work" / "qa" / "subtitle-visual" / (
            f"{manifest_sha[:12]}-{uuid.uuid4().hex[:8]}"
        )
        evidence.mkdir(parents=True)
    else:
        evidence = _confined_path(
            project, Path(evidence_directory), "work/qa",
            "subtitle visual evidence directory", must_exist=False
        )
        if evidence == (project / "work" / "qa").resolve():
            raise ValueError("visual evidence directory must be below work/qa, not the root")
        if evidence.exists() and any(evidence.iterdir()):
            raise FileExistsError("subtitle visual evidence directory must be empty")
        evidence.mkdir(parents=True, exist_ok=True)
    report_path = (
        _confined_path(
            project, Path(output), "work/qa", "subtitle visual QA output", must_exist=False
        )
        if output is not None
        else evidence / "subtitle-visual-qa.json"
    )
    log_path = evidence / "ffmpeg.log"
    log_path.touch()
    frame_directory = evidence / "frames"
    sheet_directory = evidence / "contact-sheets"
    frame_directory.mkdir()
    sheet_directory.mkdir()
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    deferred_contract_blockers: list[dict[str, str]] = []
    if manifest_schema_issues:
        deferred_contract_blockers.append(
            _schema_blocker(
                "subtitle_preview_manifest_schema_invalid",
                "preview_manifest",
                manifest_schema_issues,
            )
        )
    cleanup_paths = manifest.get("cleanup_paths")
    if isinstance(cleanup_paths, list):
        cleanup_roots = (
            (project / "work" / "proxy").resolve(),
            (project / "work" / "qa").resolve(),
        )
        for raw_path in cleanup_paths:
            valid = isinstance(raw_path, str) and bool(raw_path)
            relative = Path(raw_path) if valid else Path()
            valid = bool(
                valid
                and not relative.is_absolute()
                and ".." not in relative.parts
            )
            resolved = (project / relative).resolve() if valid else project
            if valid:
                valid = any(
                    resolved != root and root in resolved.parents
                    for root in cleanup_roots
                )
            if not valid:
                blockers.append(
                    _issue(
                        "subtitle_cleanup_path_invalid",
                        "cleanup_paths",
                        "cleanup paths must be strict descendants of work/proxy or work/qa",
                    )
                )
    else:
        blockers.append(
            _issue(
                "subtitle_cleanup_path_invalid",
                "cleanup_paths",
                "cleanup paths must be an array of strict cleanup descendants",
            )
        )
    raw_bindings = manifest.get("bindings")
    bindings = raw_bindings if isinstance(raw_bindings, dict) else {}
    if not isinstance(raw_bindings, dict):
        blockers.append(
            _issue(
                "subtitle_preview_bindings_invalid",
                "preview_manifest",
                "subtitle preview manifest has no valid bindings object",
            )
        )
    source_binding = bindings.get("subtitle_source")
    timeline_binding = bindings.get("realized_timeline")
    source_binding = source_binding if isinstance(source_binding, dict) else {}
    timeline_binding = timeline_binding if isinstance(timeline_binding, dict) else {}

    def verify(name: str, path: Path, expected: Any) -> None:
        if not path.is_file():
            blockers.append(_issue(f"{name}_missing", name, f"{name} is missing"))
        elif _sha256_file(path) != expected:
            blockers.append(
                _issue(
                    f"{name}_sha256_mismatch", name,
                    f"{name} SHA-256 no longer matches preview evidence"
                )
            )

    def resolve_binding(
        name: str,
        binding: Mapping[str, Any],
        label: str,
        relative_root: str,
    ) -> Path | None:
        if not binding:
            blockers.append(
                _issue(f"{name}_binding_invalid", name, f"{label} binding is missing")
            )
            return None
        try:
            return _bound_path(project, binding, label, relative_root)
        except (FileNotFoundError, OSError, ValueError) as error:
            blockers.append(_issue(f"{name}_path_invalid", name, str(error)))
            return None

    source_path = resolve_binding(
        "subtitle_source", source_binding, "subtitle source", "work/subtitles"
    )
    timeline_path = resolve_binding(
        "realized_timeline", timeline_binding, "realized timeline", "work/qa"
    )
    if source_path is not None:
        verify("subtitle_source", source_path, source_binding.get("sha256"))
    if timeline_path is not None:
        verify("realized_timeline", timeline_path, timeline_binding.get("sha256"))

    optional: dict[str, dict[str, Any]] = {}
    for name, relative_root in (
        ("enhancement_plan", "work/enhancement"),
        ("readability_qa", "work/qa"),
        ("layout_qa", "work/qa"),
    ):
        binding = bindings.get(name)
        if not isinstance(binding, dict):
            continue
        path = resolve_binding(name, binding, name, relative_root)
        if path is None:
            continue
        verify(name, path, binding.get("sha256"))
        if path.is_file():
            try:
                optional[name] = _load_json(path, name)
            except ValueError as error:
                blockers.append(_issue(f"{name}_json_invalid", name, str(error)))
    for name, schema_name in (
        ("readability_qa", "subtitle-readability-qa.schema.json"),
        ("layout_qa", "subtitle-layout-qa.schema.json"),
    ):
        document = optional.get(name)
        if document is None:
            continue
        issues = _schema_issues(document, schema_name)
        if issues:
            deferred_contract_blockers.append(
                _schema_blocker(
                    f"subtitle_{name}_schema_invalid",
                    name,
                    issues,
                )
            )
    for item in manifest.get("outputs", []):
        if not isinstance(item, dict):
            blockers.append(_issue("preview_output_invalid", "outputs", "invalid output"))
            continue
        for kind in ("ass", "media"):
            relative = item.get(f"{kind}_path")
            try:
                path = _confined_path(
                    project,
                    project / str(relative),
                    "work/proxy",
                    f"preview {kind}",
                )
            except (FileNotFoundError, ValueError) as error:
                blockers.append(_issue(f"preview_{kind}_path_invalid", str(item.get("output_id")), str(error)))
                continue
            verify(f"preview_{kind}", path, item.get(f"{kind}_sha256"))
    source: dict[str, Any] = {"cues": []}
    timeline: dict[str, Any] = {"duration_sec": 0, "segments": []}
    cues: list[dict[str, Any]] = []
    if source_path is not None and source_path.is_file():
        try:
            source = _load_json(source_path, "subtitle source")
            cues = _ordered_cues(source)
        except ValueError as error:
            blockers.append(_issue("subtitle_source_json_invalid", "subtitle_source", str(error)))
    if timeline_path is not None and timeline_path.is_file():
        try:
            timeline = _load_json(timeline_path, "realized timeline")
            _timeline_segments(timeline)
        except ValueError as error:
            blockers.append(_issue("realized_timeline_json_invalid", "realized_timeline", str(error)))

    readability = optional.get("readability_qa")
    layout = optional.get("layout_qa")
    readability_policy_sha: str | None = None
    if readability is not None:
        policy = readability.get("policy")
        if not isinstance(policy, dict):
            blockers.append(
                _issue(
                    "readability_policy_content_invalid",
                    "readability_qa",
                    "readability QA policy content is missing or invalid",
                )
            )
        else:
            readability_policy_sha = _canonical_sha256(policy)
            if readability.get("policy_sha256") != readability_policy_sha:
                blockers.append(
                    _issue(
                        "readability_policy_sha_mismatch",
                        "readability_qa",
                        "readability QA policy SHA does not match canonical policy content",
                    )
                )
            if policy.get("policy_version") != readability.get("policy_version"):
                blockers.append(
                    _issue(
                        "readability_policy_version_mismatch",
                        "readability_qa",
                        "readability QA policy version does not match policy content",
                    )
                )
    try:
        high_risk = select_high_risk_cue_ids(readability) if readability else []
    except ValueError as error:
        blockers.append(_issue("subtitle_readability_qa_invalid", "readability_qa", str(error)))
        high_risk = []
    raw_selection = manifest.get("selection")
    selection = raw_selection if isinstance(raw_selection, dict) else {}
    if not isinstance(raw_selection, dict):
        blockers.append(_issue("subtitle_preview_selection_invalid", "selection", "selection must be an object"))
    planned = [str(value) for value in selection.get("planned_cue_ids", [])]
    source_cue_ids = [_cue_id(cue) for cue in cues]
    if manifest.get("cue_count") != len(source_cue_ids) or planned != source_cue_ids:
        blockers.append(
            _issue(
                "subtitle_manifest_cue_set_mismatch",
                "subtitles",
                "preview manifest cue count and planned cue IDs must exactly match the bound source",
            )
        )
    manifest_outputs = manifest.get("outputs")
    manifest_outputs = manifest_outputs if isinstance(manifest_outputs, list) else []
    rendered = list(
        dict.fromkeys(
            str(cue_id)
            for item in manifest_outputs
            if isinstance(item, dict)
            for cue_id in item.get("rendered_cue_ids", [])
        )
    )
    if any(cue_id not in source_cue_ids for cue_id in rendered):
        blockers.append(
            _issue(
                "subtitle_manifest_unknown_rendered_cue",
                "subtitles",
                "preview outputs reference cue IDs absent from the bound source",
            )
        )
    selected_rendered = [
        str(value) for value in selection.get("planned_rendered_cue_ids", [])
    ]
    if (
        manifest.get("actual_rendered_cue_count") != len(rendered)
        or selected_rendered != [cue_id for cue_id in source_cue_ids if cue_id in rendered]
    ):
        blockers.append(
            _issue(
                "subtitle_manifest_rendered_set_mismatch",
                "subtitles",
                "preview rendered counts and cue selections do not match its outputs",
            )
        )
    ass_hashes = [
        item.get("ass_sha256") for item in manifest_outputs if isinstance(item, dict)
    ]
    media_hashes = [
        item.get("media_sha256") for item in manifest_outputs if isinstance(item, dict)
    ]
    if all(isinstance(value, str) for value in ass_hashes) and manifest.get(
        "ass_bundle_sha256"
    ) != _canonical_sha256(ass_hashes):
        blockers.append(_issue("subtitle_ass_bundle_mismatch", "outputs", "ASS bundle SHA is stale"))
    if all(isinstance(value, str) for value in media_hashes) and manifest.get(
        "media_bundle_sha256"
    ) != _canonical_sha256(media_hashes):
        blockers.append(_issue("subtitle_media_bundle_mismatch", "outputs", "media bundle SHA is stale"))
    required = planned if manifest.get("scope") == "all" else [
        str(value) for value in selection.get("selected_trigger_cue_ids", [])
    ]
    missing = [cue_id for cue_id in required if cue_id not in rendered]
    if missing:
        blockers.append(_issue("subtitle_render_evidence_missing", "subtitles", "required cues have no proxy"))
    if manifest.get("scope") != "all":
        warnings.append(_issue("subtitle_visual_qa_scope_partial", "scope", "risk scope cannot satisfy release coverage"))
    ffmpeg = find_ffmpeg(executable)
    current_ffmpeg_identity: dict[str, Any] | None = None
    try:
        require_filters(ffmpeg, {"subtitles"})
        current_ffmpeg_identity = inspect_ffmpeg_identity(ffmpeg)
    except (FFmpegError, FileNotFoundError, OSError, ValueError) as error:
        blockers.append(_issue("libass_subtitles_filter_unavailable", "ffmpeg", str(error)))
    else:
        manifest_ffmpeg_sha = (
            bindings.get("ffmpeg_identity", {}).get("executable_sha256")
            if isinstance(bindings.get("ffmpeg_identity"), dict)
            else None
        )
        if current_ffmpeg_identity.get("executable_sha256") != manifest_ffmpeg_sha:
            deferred_contract_blockers.append(
                _issue(
                    "subtitle_qa_ffmpeg_identity_mismatch",
                    "ffmpeg",
                    "QA FFmpeg executable does not match the preview renderer",
                )
            )
    cue_by_id = {_cue_id(cue): cue for cue in cues}
    output_by_cue: dict[str, dict[str, Any]] = {}
    parse_passed = 0
    if not blockers:
        for item in manifest.get("outputs", []):
            media_path = project / item["media_path"]
            ass_path = project / item["ass_path"]
            for cue_id in item["rendered_cue_ids"]:
                output_by_cue.setdefault(str(cue_id), item)
            if _run(
                [
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    f"color=c=white:s={int(item['width'])}x{int(item['height'])}:d=0.04",
                    "-vf", f"subtitles=filename='{filter_path(ass_path)}'",
                    "-frames:v", "1", "-f", "null", os.devnull,
                ],
                log_path,
            ):
                parse_passed += 1
            else:
                blockers.append(_issue("ass_libass_parse_failed", str(item["output_id"]), "ASS failed real libass parsing"))
            if not _run(
                [
                    ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-xerror", "-i", str(media_path), "-map", "0:v:0",
                    "-map", "0:a:0", "-f", "null", os.devnull,
                ],
                log_path,
            ):
                blockers.append(_issue("subtitle_proxy_decode_failed", str(item["output_id"]), "proxy failed full decode"))
    cue_evidence: list[dict[str, Any]] = []
    frame_cache: dict[tuple[str, float], dict[str, Any]] = {}
    middle_frames: dict[str, dict[str, Any]] = {}
    risk_set = set(high_risk)
    for cue_id in required if not blockers else []:
        cue, item = cue_by_id.get(cue_id), output_by_cue.get(cue_id)
        if cue is None or item is None:
            continue
        frame_objects: dict[str, dict[str, Any]] = {}
        times = _times(cue, item)
        for role in ("entry", "middle", "exit") if cue_id in risk_set else ("middle",):
            time_sec = times[role]
            key = (str(item["output_id"]), time_sec)
            frame = frame_cache.get(key)
            if frame is None:
                filename = hashlib.sha256(f"{key[0]}:{time_sec:.6f}".encode()).hexdigest()[:16] + ".png"
                path = frame_directory / filename
                try:
                    _extract(ffmpeg, project / item["media_path"], time_sec, path, log_path)
                except FFmpegError:
                    blockers.append(_issue("subtitle_evidence_frame_failed", cue_id, "frame extraction failed"))
                    continue
                frame = {"path": _relative(project, path), "sha256": _sha256_file(path), "time_sec": time_sec}
                frame_cache[key] = frame
            frame_objects[role] = dict(frame)
        if "middle" in frame_objects:
            middle_frames[cue_id] = frame_objects["middle"]
        cue_evidence.append(
            {
                "cue_id": cue_id, "output_id": item["output_id"],
                "ass_sha256": item["ass_sha256"], "media_sha256": item["media_sha256"],
                "frames": frame_objects,
            }
        )
    categories = _categories(cues, readability, layout, timeline) if cues and not blockers else {
        name: [] for name in _CATEGORIES
    }
    for cue_ids in categories.values():
        for cue_id in cue_ids:
            if cue_id in middle_frames or cue_id not in cue_by_id or cue_id not in output_by_cue:
                continue
            cue, item = cue_by_id[cue_id], output_by_cue[cue_id]
            time_sec = _times(cue, item)["middle"]
            filename = hashlib.sha256(f"{item['output_id']}:{time_sec:.6f}".encode()).hexdigest()[:16] + ".png"
            path = frame_directory / filename
            if not path.is_file():
                try:
                    _extract(ffmpeg, project / item["media_path"], time_sec, path, log_path)
                except FFmpegError:
                    blockers.append(_issue("subtitle_contact_frame_failed", cue_id, "contact frame failed"))
                    continue
            middle_frames[cue_id] = {"path": _relative(project, path), "sha256": _sha256_file(path), "time_sec": time_sec}
    contact_sheets = {
        name: _sheets(project, name, categories[name], middle_frames, sheet_directory)
        for name in _CATEGORIES
    }
    blockers.extend(deferred_contract_blockers)

    # Visual evidence and real layout evidence are complementary.  The frames
    # prove what libass rendered; the probe proves the measured pixels stayed
    # inside the requested safe area.  Never infer either result from FFmpeg's
    # exit code alone.
    if readability is None:
        warnings.append(
            _issue(
                "subtitle_readability_qa_not_bound",
                "readability_qa",
                "visual evidence has no bound readability audit",
            )
        )
    else:
        if readability.get("subtitle_source_sha256") != source_binding.get("sha256"):
            blockers.append(
                _issue(
                    "readability_subtitle_source_mismatch",
                    "readability_qa",
                    "readability QA does not bind the current subtitle source",
                )
            )
        if readability.get("realized_timeline_sha256") != timeline_binding.get("sha256"):
            blockers.append(
                _issue(
                    "readability_realized_timeline_mismatch",
                    "readability_qa",
                    "readability QA does not bind the current realized timeline",
                )
            )
        for item in readability.get("cues", []):
            if not isinstance(item, dict):
                continue
            cue_id = str(item.get("cue_id", ""))
            if (
                "duration_below_minimum" in item.get("blocker_codes", [])
                and item.get("proposed_repair") is None
            ):
                warnings.append(
                    _issue(
                        "subtitle_unresolved_short_flash",
                        cue_id or "subtitles",
                        "an ultra-short cue remains unresolved and cannot be release-ready",
                    )
                )

    if layout is None:
        warnings.append(
            _issue(
                "subtitle_real_layout_qa_not_bound",
                "layout_qa",
                "frames were generated, but real glyph layout was not supplied",
            )
        )
    else:
        layout_bindings = layout.get("bindings", {})
        if layout_bindings.get("subtitle_source_sha256") != source_binding.get("sha256"):
            blockers.append(
                _issue(
                    "layout_subtitle_source_mismatch",
                    "layout_qa",
                    "layout QA does not bind the current subtitle source",
                )
            )
        if layout_bindings.get("realized_timeline_sha256") != timeline_binding.get("sha256"):
            blockers.append(
                _issue(
                    "layout_realized_timeline_mismatch",
                    "layout_qa",
                    "layout QA does not bind the current realized timeline",
                )
            )
        readability_binding = bindings.get("readability_qa")
        if (
            not isinstance(readability_binding, dict)
            or layout_bindings.get("readability_qa_sha256")
            != readability_binding.get("sha256")
        ):
            blockers.append(
                _issue(
                    "layout_readability_qa_mismatch",
                    "layout_qa",
                    "layout QA does not bind the current readability QA artifact",
                )
            )
        if layout_bindings.get("readability_policy_sha256") != readability_policy_sha:
            blockers.append(
                _issue(
                    "layout_readability_policy_sha_mismatch",
                    "layout_qa",
                    "layout QA does not bind the current readability policy content",
                )
            )
        plan_binding = bindings.get("enhancement_plan")
        if isinstance(plan_binding, dict) and layout_bindings.get(
            "enhancement_plan_sha256"
        ) != plan_binding.get("sha256"):
            blockers.append(
                _issue(
                    "layout_enhancement_plan_mismatch",
                    "layout_qa",
                    "layout QA does not bind the current enhancement plan",
                )
            )
        if layout_bindings.get("readability_policy_version") != bindings.get(
            "readability_policy_version"
        ):
            blockers.append(
                _issue(
                    "layout_readability_policy_mismatch",
                    "layout_qa",
                    "layout QA uses a different readability policy version",
                )
            )
        if layout.get("probe_version") != bindings.get("layout_probe_version"):
            blockers.append(
                _issue(
                    "layout_probe_version_mismatch",
                    "layout_qa",
                    "layout QA probe version does not match the preview binding",
                )
            )
        manifest_ffmpeg = bindings.get("ffmpeg_identity", {})
        layout_ffmpeg = layout.get("ffmpeg_identity")
        if (
            not isinstance(layout_ffmpeg, dict)
            or layout_ffmpeg.get("executable_sha256")
            != (
                manifest_ffmpeg.get("executable_sha256")
                if isinstance(manifest_ffmpeg, dict)
                else None
            )
        ):
            blockers.append(
                _issue(
                    "layout_ffmpeg_identity_mismatch",
                    "layout_qa",
                    "layout QA was measured with a different or unknown FFmpeg",
                )
            )
        base_media = bindings.get("base_media", {})
        canvas = layout.get("canvas")
        if (
            not isinstance(canvas, dict)
            or not isinstance(base_media, dict)
            or canvas.get("width") != base_media.get("width")
            or canvas.get("height") != base_media.get("height")
        ):
            blockers.append(
                _issue(
                    "layout_canvas_mismatch",
                    "layout_qa",
                    "layout QA canvas does not match the rendered base media",
                )
            )
        if layout.get("probe_mode") != "real_libass":
            blockers.append(
                _issue(
                    "real_layout_probe_required",
                    "layout_qa",
                    "visual layout claims require real libass pixel measurement",
                )
            )
        layout_by_id = {
            str(item.get("cue_id")): item
            for item in layout.get("cues", [])
            if isinstance(item, dict) and item.get("cue_id")
        }
        plan = optional.get("enhancement_plan", {})
        plan_subtitles = plan.get("subtitles", {}) if isinstance(plan, dict) else {}
        source_style = source.get("style", {}) if isinstance(source.get("style"), dict) else {}
        active_style = (
            plan_subtitles.get("style", source_style)
            if isinstance(plan_subtitles, dict)
            else source_style
        )
        active_style = active_style if isinstance(active_style, dict) else source_style
        for cue_id in planned:
            cue = cue_by_id.get(cue_id)
            measurement = layout_by_id.get(cue_id)
            if cue is None or measurement is None:
                blockers.append(
                    _issue(
                        "subtitle_layout_evidence_missing",
                        cue_id,
                        "planned cue has no corresponding layout measurement",
                    )
                )
                continue
            expected_text_sha = hashlib.sha256(
                str(cue.get("text", "")).encode("utf-8")
            ).hexdigest()
            expected_position = str(
                cue.get("position", active_style.get("position", "bottom_center"))
            )
            expected_style = dict(active_style)
            expected_style["position"] = expected_position
            expected_style_sha = hashlib.sha256(
                json.dumps(
                    expected_style,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if measurement.get("text_sha256") != expected_text_sha:
                blockers.append(_issue("subtitle_layout_text_mismatch", cue_id, "layout text hash is stale"))
            if measurement.get("style_sha256") != expected_style_sha:
                blockers.append(_issue("subtitle_layout_style_mismatch", cue_id, "layout style hash is stale"))
            if measurement.get("position") != expected_position:
                blockers.append(_issue("subtitle_layout_position_mismatch", cue_id, "top/bottom layout evidence is stale"))
            if measurement.get("clipped") is not False:
                blockers.append(_issue("subtitle_layout_clipped", cue_id, "glyph or background pixels may be clipped"))
            if measurement.get("inside_safe_area") is not True:
                blockers.append(_issue("subtitle_layout_outside_safe_area", cue_id, "subtitle pixels are not proven inside the safe area"))
            if measurement.get("real_layout_verified") is not True:
                blockers.append(_issue("subtitle_real_layout_unverified", cue_id, "cue lacks verified real libass layout evidence"))
    evidence_by_id = {item["cue_id"]: item for item in cue_evidence}
    high_risk_queue = []
    for cue_id in high_risk:
        evidence_item = evidence_by_id.get(cue_id)
        if evidence_item:
            frames = evidence_item["frames"]
            high_risk_queue.append(
                {
                    "cue_id": cue_id, "frames": frames,
                    "distinct_frame_count": len(
                        {(frame["path"], frame["time_sec"]) for frame in frames.values()}
                    ),
                }
            )
    if manifest.get("scope") == "all":
        evidenced = {
            item["cue_id"] for item in cue_evidence if "middle" in item["frames"]
        }
        absent = [cue_id for cue_id in planned if cue_id not in evidenced]
        if absent:
            blockers.append(_issue("subtitle_per_cue_visual_evidence_missing", "subtitles", "all cues require a middle frame"))
            missing = list(dict.fromkeys([*missing, *absent]))
    report = {
        "schema_version": VISUAL_QA_SCHEMA_VERSION,
        "document_type": "subtitle_visual_qa",
        "qa_version": VISUAL_QA_VERSION,
        "status": "blocked" if blockers else "review_required",
        "machine_status": "blocked" if blockers else "passed",
        "project_id": str(manifest.get("project_id", "")),
        "scope": str(manifest.get("scope", "")),
        "cue_count": len(planned),
        "actual_rendered_cue_count": len(rendered),
        "cue_ids": planned,
        "rendered_cue_ids": rendered,
        "missing_cue_ids": missing,
        "unrendered_due_to_scope_cue_ids": [
            str(value) for value in selection.get("unrendered_due_to_scope_cue_ids", [])
        ],
        "bindings": {
            "preview_manifest_path": _relative(project, manifest_path),
            "preview_manifest_sha256": manifest_sha,
            "subtitle_source_path": source_binding.get("path"),
            "subtitle_source_sha256": source_binding.get("sha256"),
            "realized_timeline_path": timeline_binding.get("path"),
            "realized_timeline_sha256": timeline_binding.get("sha256"),
            "enhancement_plan_sha256": (
                bindings.get("enhancement_plan", {}).get("sha256")
                if isinstance(bindings.get("enhancement_plan"), dict)
                else None
            ),
            "readability_qa_sha256": (
                bindings.get("readability_qa", {}).get("sha256")
                if isinstance(bindings.get("readability_qa"), dict)
                else None
            ),
            "readability_policy_sha256": (
                readability_policy_sha
            ),
            "layout_qa_sha256": (
                bindings.get("layout_qa", {}).get("sha256")
                if isinstance(bindings.get("layout_qa"), dict)
                else None
            ),
            "ass_bundle_sha256": manifest.get("ass_bundle_sha256"),
            "media_bundle_sha256": manifest.get("media_bundle_sha256"),
            "base_media_sha256": bindings.get("base_media", {}).get("sha256"),
            "ffmpeg_executable_sha256": (
                current_ffmpeg_identity.get("executable_sha256")
                if current_ffmpeg_identity is not None
                else None
            ),
            "readability_policy_version": bindings.get("readability_policy_version"),
            "layout_probe_version": bindings.get("layout_probe_version"),
        },
        "readability_summary": {
            "provided": readability is not None,
            "status": readability.get("status") if readability else None,
            "high_risk_cue_count": len(high_risk),
        },
        "layout_probe_summary": {
            "provided": layout is not None,
            "status": layout.get("status") if layout else None,
            "probe_mode": layout.get("probe_mode") if layout else None,
            "cue_count": len(layout.get("cues", [])) if layout else 0,
        },
        "ass_parse_summary": {
            "ass_count": len(manifest.get("outputs", [])),
            "passed_count": parse_passed,
            "failed_count": max(0, len(manifest.get("outputs", [])) - parse_passed),
        },
        "blockers": blockers,
        "warnings": warnings,
        "cue_evidence": cue_evidence,
        "high_risk_review_queue": high_risk_queue,
        "contact_sheets": contact_sheets,
        "human_review": {
            "status": "pending", "approval_path": None, "approval_sha256": None
        },
        "release_ready": False,
        "limitations": [HUMAN_REVIEW_LIMITATION],
        "ffmpeg_log_path": _relative(project, log_path),
        "report_path": _relative(project, report_path),
    }
    visual_schema_issues = _schema_issues(report, "subtitle-visual-qa.schema.json")
    if visual_schema_issues:
        raise ValueError(
            "subtitle visual QA schema invalid: " + "; ".join(visual_schema_issues)
        )
    _write_json(report_path, report)
    return report
