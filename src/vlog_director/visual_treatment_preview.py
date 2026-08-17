from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .enhancement import normalize_realized_timeline
from .ffmpeg import find_ffmpeg, probe_media, run_command
from .renderers import _visual_filter_chain
from .visual_treatments import (
    canonical_treatment_payload_sha256,
    validate_visual_treatment_plan,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _write_new(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _confined(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {allowed}") from error
    if resolved == allowed or not relative.parts:
        raise ValueError(f"{label} cannot equal its allowed root")
    return resolved


def _base_media(project: Path, path: Path) -> Path:
    resolved = path.resolve()
    roots = ((project / "output").resolve(), (project / "work" / "proxy").resolve())
    if not any(resolved != root and resolved.is_relative_to(root) for root in roots):
        raise ValueError("base media must stay under project/output or project/work/proxy")
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _ffmpeg_identity(executable: str) -> tuple[str, str]:
    resolved = find_ffmpeg(executable)
    completed = subprocess.run(
        [resolved, "-version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError("unable to identify FFmpeg")
    return resolved, (completed.stdout or completed.stderr).splitlines()[0].strip()


@lru_cache(maxsize=2)
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("vlog_director.schemas").joinpath(name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_schema(document: Mapping[str, Any], name: str) -> None:
    errors = sorted(
        _validator(name).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise ValueError(
            "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        )


def _load_bound_contract(
    project: Path,
    plan_path: Path,
    realized_timeline_path: Path,
    base_video: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan_path = _confined(plan_path, project / "work" / "treatments", "treatment plan")
    realized_timeline_path = _confined(
        realized_timeline_path,
        project / "work" / "qa",
        "realized timeline",
    )
    base_video = _base_media(project, base_video)
    plan = _load_json(plan_path, "treatment plan")
    analysis_path = project / str(plan.get("analysis", {}).get("path", ""))
    analysis_path = _confined(
        analysis_path,
        project / "work" / "analysis" / "visual",
        "visual analysis",
    )
    if _sha256_file(analysis_path) != plan.get("analysis", {}).get("sha256"):
        raise ValueError("visual analysis SHA-256 changed")
    analysis = _load_json(analysis_path, "visual analysis")
    edit_path = project / "work" / "plans" / f"edit_plan.v{plan.get('edit_plan_version')}.json"
    edit_plan = _load_json(edit_path, "edit plan")
    validation = validate_visual_treatment_plan(edit_plan, analysis, plan)
    if validation["status"] != "passed":
        raise ValueError(json.dumps(validation["issues"], ensure_ascii=False))
    realized_document = _load_json(realized_timeline_path, "realized timeline")
    realized = normalize_realized_timeline(
        edit_plan,
        realized_document,
        edit_plan_sha256=_sha256_file(edit_path),
    )
    if _sha256_file(realized_timeline_path) != plan["realized_timeline_sha256"]:
        raise ValueError("realized timeline SHA-256 changed")
    if _sha256_file(base_video) != plan["base_media_sha256"]:
        raise ValueError("base media SHA-256 changed")
    return plan, analysis, realized, edit_plan


def render_treatment_previews(
    project: Path,
    base_video: Path,
    plan_path: Path,
    realized_timeline_path: Path,
    output_directory: Path,
    *,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    project = project.resolve()
    output_directory = _confined(
        output_directory,
        project / "work" / "proxy" / "treatments",
        "treatment preview directory",
    )
    if output_directory.exists():
        raise FileExistsError(output_directory)
    plan, analysis, realized, _ = _load_bound_contract(
        project,
        plan_path,
        realized_timeline_path,
        base_video,
    )
    if not plan["proposals"]:
        raise ValueError("visual treatment plan contains no proposals")
    base_video = _base_media(project, base_video)
    ffmpeg, identity = _ffmpeg_identity(executable)
    media = probe_media(ffmpeg, base_video)
    width = int(media["width"])
    height = int(media["height"])
    timeline = {
        str(row["segment_id"]): row
        for row in realized.get("segments", [])
        if isinstance(row, Mapping)
    }
    output_directory.mkdir(parents=True)
    previews: list[dict[str, Any]] = []
    for proposal in plan["proposals"]:
        segment_id = str(proposal["segment_id"])
        if segment_id not in timeline:
            raise ValueError(f"realized timeline is missing {segment_id}")
        segment = timeline[segment_id]
        start = float(segment["start_sec"])
        end = float(segment["end_sec"])
        if end <= start:
            raise ValueError(f"invalid realized bounds for {segment_id}")
        treatment = {"visual": dict(proposal["changes"])}
        visual_filters, _ = _visual_filter_chain(treatment, width, height)
        treated_chain = ",".join(visual_filters) if visual_filters else "null"
        graph = (
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height},setsar=1[before];"
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"{treated_chain},scale={width}:{height},setsar=1[after];"
            "[before][after]hstack=inputs=2[video];"
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[audio]"
        )
        output = output_directory / f"{proposal['proposal_id']}.mp4"
        run_command(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(base_video),
                "-filter_complex",
                graph,
                "-map",
                "[video]",
                "-map",
                "[audio]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                str(output),
            ]
        )
        run_command(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-f",
                "null",
                os.devnull,
            ]
        )
        previews.append(
            {
                "proposal_id": proposal["proposal_id"],
                "segment_id": segment_id,
                "start_sec": round(start, 6),
                "end_sec": round(end, 6),
                "path": output.relative_to(project).as_posix(),
                "sha256": _sha256_file(output),
                "size_bytes": output.stat().st_size,
                "layout": "before_after_side_by_side",
            }
        )
    manifest = {
        "schema_version": "1.0",
        "contract_version": "visual-treatment-preview-v1",
        "status": "rendered",
        "project_id": plan["project_id"],
        "plan_sha256": _sha256_file(plan_path.resolve()),
        "treatment_payload_sha256": canonical_treatment_payload_sha256(plan),
        "analysis_sha256": plan["analysis"]["sha256"],
        "realized_timeline_sha256": plan["realized_timeline_sha256"],
        "base_media": {
            "path": base_video.relative_to(project).as_posix(),
            "sha256": _sha256_file(base_video),
            "size_bytes": base_video.stat().st_size,
        },
        "ffmpeg_identity": identity,
        "previews": previews,
    }
    _validate_schema(manifest, "visual-treatment-preview-manifest.schema.json")
    _write_new(output_directory / "preview-manifest.json", manifest)
    return manifest


BLACK_START = re.compile(r"black_start:")
FREEZE_START = re.compile(r"freeze_start:")


def _extract_frame(
    ffmpeg: str,
    preview: Path,
    time_sec: float,
    output: Path,
) -> None:
    run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{time_sec:.6f}",
            "-i",
            str(preview),
            "-frames:v",
            "1",
            str(output),
        ]
    )


def qa_visual_treatments(
    project: Path,
    plan_path: Path,
    preview_manifest_path: Path,
    output_directory: Path,
    *,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    project = project.resolve()
    plan_path = _confined(plan_path, project / "work" / "treatments", "treatment plan")
    preview_manifest_path = _confined(
        preview_manifest_path,
        project / "work" / "proxy" / "treatments",
        "preview manifest",
    )
    output_directory = _confined(
        output_directory,
        project / "work" / "qa" / "treatments",
        "treatment QA directory",
    )
    if output_directory.exists():
        raise FileExistsError(output_directory)
    plan = _load_json(plan_path, "treatment plan")
    manifest = _load_json(preview_manifest_path, "preview manifest")
    _validate_schema(manifest, "visual-treatment-preview-manifest.schema.json")
    if manifest["plan_sha256"] != _sha256_file(plan_path):
        raise ValueError("preview manifest treatment plan SHA-256 changed")
    if manifest["treatment_payload_sha256"] != canonical_treatment_payload_sha256(plan):
        raise ValueError("preview manifest treatment payload changed")
    ffmpeg, identity = _ffmpeg_identity(executable)
    if manifest["ffmpeg_identity"] != identity:
        raise ValueError("preview and QA FFmpeg identity differ")
    output_directory.mkdir(parents=True)
    qa_rows: list[dict[str, Any]] = []
    blocker_total = 0
    warning_total = 0
    for row in manifest["previews"]:
        preview = project / row["path"]
        preview = _confined(
            preview,
            project / "work" / "proxy" / "treatments",
            "treatment preview",
        )
        if _sha256_file(preview) != row["sha256"] or preview.stat().st_size != row["size_bytes"]:
            raise ValueError(f"preview changed: {row['proposal_id']}")
        expected_duration = float(row["end_sec"]) - float(row["start_sec"])
        media = probe_media(ffmpeg, preview)
        actual_duration = float(media["duration_sec"])
        duration_delta = abs(actual_duration - expected_duration)
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(preview),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-vf",
                "blackdetect=d=0.10:pix_th=0.10,freezedetect=n=-50dB:d=0.50",
                "-f",
                "null",
                os.devnull,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"full preview decode failed: {row['proposal_id']}")
        black = bool(BLACK_START.search(completed.stderr))
        freeze = bool(FREEZE_START.search(completed.stderr))
        blockers: list[str] = []
        warnings: list[str] = []
        # Low-frame-rate proxies can quantize the encoded tail by nearly two frames.
        if duration_delta > 0.15:
            blockers.append("preview_duration_mismatch")
        if black:
            blockers.append("unexpected_black_frame")
        if freeze:
            warnings.append("possible_freeze_detected")
        frame_directory = output_directory / str(row["proposal_id"])
        frame_directory.mkdir()
        frame_specs = (
            ("entry", max(0.0, actual_duration * 0.10)),
            ("middle", actual_duration * 0.5),
            ("exit", max(0.0, actual_duration * 0.85)),
        )
        frames: list[dict[str, str]] = []
        for role, time_sec in frame_specs:
            frame_path = frame_directory / f"{role}.png"
            _extract_frame(ffmpeg, preview, time_sec, frame_path)
            frames.append(
                {
                    "role": role,
                    "path": frame_path.relative_to(project).as_posix(),
                    "sha256": _sha256_file(frame_path),
                }
            )
        blocker_total += len(blockers)
        warning_total += len(warnings)
        qa_rows.append(
            {
                "proposal_id": row["proposal_id"],
                "segment_id": row["segment_id"],
                "preview_sha256": row["sha256"],
                "duration_delta_sec": round(duration_delta, 6),
                "black_frame_detected": black,
                "freeze_detected": freeze,
                "blocker_codes": blockers,
                "warning_codes": warnings,
                "frames": frames,
            }
        )
    report = {
        "schema_version": "1.0",
        "contract_version": "visual-treatment-visual-qa-v1",
        "status": "blocked" if blocker_total else "passed",
        "project_id": plan["project_id"],
        "plan_sha256": _sha256_file(plan_path),
        "treatment_payload_sha256": canonical_treatment_payload_sha256(plan),
        "preview_manifest_sha256": _sha256_file(preview_manifest_path),
        "base_media_sha256": manifest["base_media"]["sha256"],
        "ffmpeg_identity": identity,
        "proposal_count": len(qa_rows),
        "blocker_count": blocker_total,
        "warning_count": warning_total,
        "proposals": qa_rows,
        "human_review": {
            "status": "pending",
            "statement": "已生成视觉帧和技术证据，画面审美适配性仍需人工检查。",
        },
    }
    _validate_schema(report, "visual-treatment-visual-qa.schema.json")
    _write_new(output_directory / "visual-qa.json", report)
    return report


__all__ = ["qa_visual_treatments", "render_treatment_previews"]
