from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from .ffmpeg import FFmpegError, find_ffmpeg, probe_media, require_filters
from .subtitle_layout_probe import inspect_ffmpeg_identity
from .subtitle_preview import (
    PREVIEW_MANIFEST_SCHEMA_VERSION,
    PREVIEW_RENDER_VERSION,
    PROGRESS_VERSION,
    _canonical_sha256,
    _confined_path,
    _cue_id,
    _load_json,
    _ordered_cues,
    _relative,
    _sha256_file,
    _slug,
    _timeline_segments,
    _utc_now,
    _write_json,
    create_unique_preview_directory,
    select_preview_units,
)
from .subtitle_readability import select_high_risk_cue_ids
from .subtitle_render_contract import (
    build_subtitle_render_contract,
    subtitle_filter_expression,
    write_contract_ass,
)


_PREVIEW_JOB_IDENTIFIER = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{12}$")
_JOB_REQUIRED_FIELDS = frozenset(
    {
        "project",
        "base_video",
        "subtitle_source",
        "realized_timeline",
        "scope",
        "proxy_unit",
        "padding_sec",
        "output_directory",
        "executable",
    }
)
_JOB_OPTIONAL_FIELDS = frozenset(
    {"enhancement_plan", "readability_qa", "layout_qa"}
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
    return [
        f"{'.'.join(str(item) for item in error.absolute_path) or '$'}: {error.message}"
        for error in errors
    ]

def _media_identity(executable: str, media_path: Path) -> dict[str, Any]:
    probe = probe_media(executable, media_path)
    ffmpeg = find_ffmpeg(executable)
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(media_path),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
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
    output = completed.stderr + "\n" + completed.stdout
    match = re.search(
        r"(?:^|,\s)([0-9]+(?:\.[0-9]+)?)\s+fps(?:,|\s)",
        output,
    )
    return {
        "name": media_path.name,
        "size_bytes": media_path.stat().st_size,
        "sha256": _sha256_file(media_path),
        "duration_sec": round(float(probe["duration_sec"]), 6),
        "width": int(probe["width"]),
        "height": int(probe["height"]),
        "frame_rate": float(match.group(1)) if match else None,
        "has_video": bool(probe["has_video"]),
        "has_audio": bool(probe["has_audio"]),
    }


def _write_exact_ass(
    project: Path,
    cues: list[dict[str, Any]],
    style: Mapping[str, Any],
    width: int,
    height: int,
    output: Path,
) -> str:
    contract = build_subtitle_render_contract(
        project,
        dict(style),
        canvas_width=width,
        canvas_height=height,
    )
    write_contract_ass(cues, contract, output)
    return subtitle_filter_expression(output, contract)


def _rebased_cues(
    cues_by_id: Mapping[str, dict[str, Any]],
    cue_ids: Iterable[str],
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    duration = end_sec - start_sec
    for cue_id in cue_ids:
        source = cues_by_id[cue_id]
        start = max(0.0, float(source["start_sec"]) - start_sec)
        end = min(duration, float(source["end_sec"]) - start_sec)
        if end <= start:
            raise ValueError(f"preview unit does not contain cue {cue_id}")
        cue = dict(source)
        cue["start_sec"] = round(start, 6)
        cue["end_sec"] = round(end, 6)
        result.append(cue)
    return result


def _run_ffmpeg_logged(command: list[str], log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write("COMMAND " + json.dumps(command, ensure_ascii=False) + "\n")
        log.flush()
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
    if completed.returncode != 0:
        raise FFmpegError(
            f"subtitle preview FFmpeg failed with exit code {completed.returncode}"
        )


def _binding_for(
    project: Path,
    path: Path,
    document: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": _relative(project, path),
        "sha256": _sha256_file(path),
    }
    if document is not None:
        for field in (
            "policy_version",
            "probe_version",
            "probe_mode",
            "status",
            "mode",
        ):
            if field in document:
                result[field] = document[field]
    return result


def render_subtitle_preview(
    *,
    project: Path,
    base_video: Path,
    subtitle_source: Path,
    realized_timeline: Path,
    enhancement_plan: Path | None = None,
    readability_qa: Path | None = None,
    layout_qa: Path | None = None,
    scope: str = "all",
    proxy_unit: str = "timeline",
    padding_sec: float = 0.75,
    output_directory: Path | None = None,
    executable: str = "ffmpeg",
    _reuse_output_directory: bool = False,
) -> dict[str, Any]:
    """Render proxies whose only creative operation is burning the exact ASS."""

    project = Path(project).resolve()
    base = Path(base_video).resolve()
    if not base.is_file():
        raise FileNotFoundError(base)
    source_path = _confined_path(
        project,
        Path(subtitle_source),
        "work/subtitles",
        "subtitle source",
    )
    timeline_path = _confined_path(
        project,
        Path(realized_timeline),
        "work/qa",
        "realized timeline",
    )
    plan_path = (
        _confined_path(
            project,
            Path(enhancement_plan),
            "work/enhancement",
            "enhancement plan",
        )
        if enhancement_plan is not None
        else None
    )
    readability_path = (
        _confined_path(
            project,
            Path(readability_qa),
            "work/qa",
            "readability QA",
        )
        if readability_qa is not None
        else None
    )
    layout_path = (
        _confined_path(
            project,
            Path(layout_qa),
            "work/qa",
            "layout QA",
        )
        if layout_qa is not None
        else None
    )
    if output_directory is None:
        job_directory = create_unique_preview_directory(project)
    else:
        job_directory = _confined_path(
            project,
            Path(output_directory),
            "work/proxy",
            "preview output directory",
            must_exist=False,
        )
        if job_directory == (project / "work" / "proxy").resolve():
            raise ValueError("preview output directory must be below work/proxy, not the root")
        if (
            job_directory.exists()
            and not _reuse_output_directory
            and any(job_directory.iterdir())
        ):
            raise FileExistsError("preview output directory must be new or empty")
        job_directory.mkdir(parents=True, exist_ok=True)

    source = _load_json(source_path, "subtitle source")
    timeline = _load_json(timeline_path, "realized timeline")
    plan = _load_json(plan_path, "enhancement plan") if plan_path else None
    readability = (
        _load_json(readability_path, "readability QA")
        if readability_path
        else None
    )
    layout = _load_json(layout_path, "layout QA") if layout_path else None
    source_sha = _sha256_file(source_path)
    timeline_sha = _sha256_file(timeline_path)
    if readability is not None:
        readability_issues = _schema_issues(
            readability,
            "subtitle-readability-qa.schema.json",
        )
        if readability_issues:
            raise ValueError(
                "readability QA schema invalid: " + "; ".join(readability_issues)
            )
        if readability.get("subtitle_source_sha256") != source_sha:
            raise ValueError("readability QA subtitle source SHA does not match")
        if readability.get("realized_timeline_sha256") != timeline_sha:
            raise ValueError("readability QA realized timeline SHA does not match")
        if readability.get("project_id") != source.get("project_id"):
            raise ValueError("readability QA project ID does not match")
        policy = readability.get("policy")
        if not isinstance(policy, dict):
            raise ValueError("readability QA policy content is invalid")
        readability_policy_sha = _canonical_sha256(policy)
        if readability.get("policy_sha256") != readability_policy_sha:
            raise ValueError(
                "readability QA policy SHA does not match canonical policy content"
            )
        if policy.get("policy_version") != readability.get("policy_version"):
            raise ValueError(
                "readability QA policy version does not match policy content"
            )
    else:
        readability_policy_sha = None
    if layout is not None:
        layout_issues = _schema_issues(layout, "subtitle-layout-qa.schema.json")
        if layout_issues:
            raise ValueError("layout QA schema invalid: " + "; ".join(layout_issues))
        if readability is None or plan_path is None:
            raise ValueError("layout QA requires the bound readability QA and enhancement plan")
        layout_bindings = layout.get("bindings", {})
        if layout.get("project_id") != source.get("project_id"):
            raise ValueError("layout QA project ID does not match")
        if layout_bindings.get("subtitle_source_sha256") != source_sha:
            raise ValueError("layout QA subtitle source SHA does not match")
        if layout_bindings.get("realized_timeline_sha256") != timeline_sha:
            raise ValueError("layout QA realized timeline SHA does not match")
        if layout_bindings.get("readability_qa_sha256") != _sha256_file(
            readability_path
        ):
            raise ValueError("layout QA readability QA SHA does not match")
        if layout_bindings.get("readability_policy_sha256") != readability_policy_sha:
            raise ValueError("layout QA readability policy SHA does not match")
        if layout_bindings.get("enhancement_plan_sha256") != _sha256_file(plan_path):
            raise ValueError("layout QA enhancement plan SHA does not match")
        if layout_bindings.get("readability_policy_version") != readability.get(
            "policy_version"
        ):
            raise ValueError("layout QA readability policy version does not match")
    if scope == "risk" and readability is None:
        raise ValueError("risk scope requires readability QA")
    high_risk = (
        select_high_risk_cue_ids(readability) if readability is not None else []
    )
    units, selection = select_preview_units(
        source,
        timeline,
        scope=scope,
        proxy_unit=proxy_unit,
        padding_sec=padding_sec,
        high_risk_cue_ids=high_risk,
    )
    cues = _ordered_cues(source)
    cues_by_id = {_cue_id(cue): cue for cue in cues}
    source_cue_ids = list(cues_by_id)
    if readability is not None and readability.get("cue_ids") != source_cue_ids:
        raise ValueError("readability QA cue set does not match the subtitle source")
    if layout is not None:
        layout_cue_ids = [
            str(item.get("cue_id"))
            for item in layout.get("cues", [])
            if isinstance(item, dict)
        ]
        if layout_cue_ids != source_cue_ids:
            raise ValueError("layout QA cue set does not match the subtitle source")
    style: Mapping[str, Any] = (
        source.get("style", {}) if isinstance(source.get("style"), dict) else {}
    )
    if plan is not None:
        plan_subtitles = plan.get("subtitles", {})
        if isinstance(plan_subtitles, dict) and isinstance(
            plan_subtitles.get("style"),
            dict,
        ):
            style = plan_subtitles["style"]

    progress_path = job_directory / "progress.jsonl"
    log_path = job_directory / "ffmpeg.log"
    manifest_path = job_directory / "manifest.json"
    protected_outputs = [progress_path, log_path, manifest_path]
    protected_outputs.extend(job_directory.glob("*.ass"))
    protected_outputs.extend(job_directory.glob("*.mkv"))
    existing_outputs = [path for path in protected_outputs if path.exists()]
    if existing_outputs:
        raise FileExistsError(
            "subtitle preview output directory contains existing evidence: "
            + ", ".join(sorted(path.name for path in existing_outputs))
        )
    sequence = 0

    def progress(stage: str, status: str, **details: Any) -> None:
        nonlocal sequence
        sequence += 1
        event = {
            "progress_version": PROGRESS_VERSION,
            "sequence": sequence,
            "timestamp": _utc_now(),
            "stage": stage,
            "status": status,
            **details,
        }
        with progress_path.open("a", encoding="utf-8", newline="\n") as output:
            output.write(
                json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
            )

    progress("preflight", "started", unit_count=len(units))
    ffmpeg = find_ffmpeg(executable)
    require_filters(ffmpeg, {"subtitles"})
    ffmpeg_identity = inspect_ffmpeg_identity(ffmpeg)
    base_identity = _media_identity(ffmpeg, base)
    if layout is not None:
        layout_ffmpeg = layout.get("ffmpeg_identity")
        if (
            not isinstance(layout_ffmpeg, dict)
            or layout_ffmpeg.get("executable_sha256")
            != ffmpeg_identity.get("executable_sha256")
        ):
            raise ValueError("layout QA FFmpeg identity does not match the preview renderer")
        if layout.get("canvas") != {
            "width": int(base_identity["width"]),
            "height": int(base_identity["height"]),
        }:
            raise ValueError("layout QA canvas does not match the preview base media")
    if not base_identity["has_video"] or not base_identity["has_audio"]:
        raise ValueError("subtitle review base must contain video and audio")
    expected_duration, _ = _timeline_segments(timeline)
    if abs(base_identity["duration_sec"] - expected_duration) > 0.2:
        raise ValueError(
            "explicit base video duration does not match realized timeline"
        )
    progress("preflight", "completed", unit_count=len(units))

    outputs: list[dict[str, Any]] = []
    for index, unit in enumerate(units, start=1):
        output_id = (
            f"{unit['unit_type']}-{_slug(str(unit['unit_id']))}-{index:04d}"
        )
        ass_path = job_directory / f"{output_id}.ass"
        media_path = job_directory / f"{output_id}.mkv"
        if ass_path.exists() or media_path.exists():
            raise FileExistsError(
                f"subtitle preview output already exists: {output_id}"
            )
        unit_cues = _rebased_cues(
            cues_by_id,
            unit["rendered_cue_ids"],
            float(unit["start_sec"]),
            float(unit["end_sec"]),
        )
        subtitle_filter = _write_exact_ass(
            project,
            unit_cues,
            style,
            int(base_identity["width"]),
            int(base_identity["height"]),
            ass_path,
        )
        progress(
            "render_proxy",
            "started",
            output_id=output_id,
            completed_units=index - 1,
            total_units=len(units),
        )
        command = [
            ffmpeg,
            "-nostdin",
            "-n",
            "-hide_banner",
            "-loglevel",
            "verbose",
            "-ss",
            f"{float(unit['start_sec']):.6f}",
            "-i",
            str(base),
            "-t",
            f"{float(unit['end_sec']) - float(unit['start_sec']):.6f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(media_path),
        ]
        _run_ffmpeg_logged(command, log_path)
        media_identity = _media_identity(ffmpeg, media_path)
        outputs.append(
            {
                "output_id": output_id,
                "unit_type": unit["unit_type"],
                "unit_id": unit["unit_id"],
                "clip_start_sec": round(float(unit["start_sec"]), 6),
                "clip_end_sec": round(float(unit["end_sec"]), 6),
                "trigger_cue_ids": list(unit["trigger_cue_ids"]),
                "rendered_cue_ids": list(unit["rendered_cue_ids"]),
                "ass_path": _relative(project, ass_path),
                "ass_sha256": _sha256_file(ass_path),
                "media_path": _relative(project, media_path),
                "media_sha256": media_identity["sha256"],
                "media_size_bytes": media_identity["size_bytes"],
                "duration_sec": media_identity["duration_sec"],
                "width": media_identity["width"],
                "height": media_identity["height"],
                "frame_rate": media_identity["frame_rate"],
                "audio_stream_copied": True,
                "ffmpeg_exit_code": 0,
            }
        )
        progress(
            "render_proxy",
            "completed",
            output_id=output_id,
            completed_units=index,
            total_units=len(units),
        )

    bindings: dict[str, Any] = {
        "subtitle_source": _binding_for(project, source_path, source),
        "realized_timeline": _binding_for(project, timeline_path, timeline),
        "base_media": base_identity,
        "ffmpeg_identity": ffmpeg_identity,
        "readability_policy_version": (
            str(readability.get("policy_version"))
            if readability is not None
            else "unprovided"
        ),
        "layout_probe_version": (
            str(layout.get("probe_version"))
            if layout is not None
            else "unprovided"
        ),
    }
    if plan_path is not None and plan is not None:
        bindings["enhancement_plan"] = _binding_for(project, plan_path, plan)
    if readability_path is not None and readability is not None:
        bindings["readability_qa"] = _binding_for(
            project,
            readability_path,
            readability,
        )
    if layout_path is not None and layout is not None:
        bindings["layout_qa"] = _binding_for(project, layout_path, layout)
    manifest: dict[str, Any] = {
        "schema_version": PREVIEW_MANIFEST_SCHEMA_VERSION,
        "document_type": "subtitle_preview_manifest",
        "render_version": PREVIEW_RENDER_VERSION,
        "status": "completed",
        "project_id": str(source.get("project_id", "")),
        "scope": scope,
        "proxy_unit": proxy_unit,
        "padding_sec": float(padding_sec),
        "cue_count": len(cues),
        "actual_rendered_cue_count": len(
            {cue_id for item in outputs for cue_id in item["rendered_cue_ids"]}
        ),
        "selection": selection,
        "bindings": bindings,
        "outputs": outputs,
        "ass_bundle_sha256": _canonical_sha256(
            [item["ass_sha256"] for item in outputs]
        ),
        "media_bundle_sha256": _canonical_sha256(
            [item["media_sha256"] for item in outputs]
        ),
        "progress_path": _relative(project, progress_path),
        "ffmpeg_log_path": _relative(project, log_path),
        "manifest_path": _relative(project, manifest_path),
        "cleanup_paths": [_relative(project, job_directory)],
        "created_at": _utc_now(),
    }
    manifest_issues = _schema_issues(
        manifest,
        "subtitle-preview-manifest.schema.json",
    )
    if manifest_issues:
        raise ValueError(
            "subtitle preview manifest schema invalid: " + "; ".join(manifest_issues)
        )
    if manifest_path.exists():
        raise FileExistsError(manifest_path)
    _write_json(manifest_path, manifest)
    progress("manifest", "completed", manifest_path=manifest["manifest_path"])
    return manifest


def _write_job_status(path: Path, status: str, **fields: Any) -> None:
    _write_json(
        path,
        {
            "schema_version": "1.0",
            "document_type": "subtitle_preview_job_status",
            "status": status,
            "updated_at": _utc_now(),
            **fields,
        },
    )


def _validated_job_directory(
    spec_path: Path,
    spec: Mapping[str, Any],
) -> tuple[Path, Path]:
    unknown = sorted(set(spec) - _JOB_REQUIRED_FIELDS - _JOB_OPTIONAL_FIELDS)
    missing = sorted(_JOB_REQUIRED_FIELDS - set(spec))
    if unknown or missing:
        raise ValueError(
            "subtitle preview job spec fields are invalid: "
            f"unknown={unknown}, missing={missing}"
        )
    project = Path(str(spec["project"])).resolve()
    jobs_root = (project / "work" / "proxy" / "subtitle-preview").resolve()
    try:
        relative = spec_path.relative_to(jobs_root)
    except ValueError as error:
        raise ValueError(
            "subtitle preview job spec must be inside a unique subtitle preview directory"
        ) from error
    if (
        len(relative.parts) != 2
        or relative.parts[1] != "job.json"
        or not _PREVIEW_JOB_IDENTIFIER.fullmatch(relative.parts[0])
    ):
        raise ValueError(
            "subtitle preview job spec must be job.json inside a unique subtitle preview directory"
        )
    job_directory = spec_path.parent.resolve()
    output_directory = Path(str(spec["output_directory"])).resolve()
    if output_directory != job_directory:
        raise ValueError("subtitle preview job output_directory must equal its job directory")
    return project, job_directory


def _assert_fresh_job(job_directory: Path, status_path: Path) -> None:
    if not status_path.is_file():
        raise FileNotFoundError(status_path)
    status = _load_json(status_path, "subtitle preview job status")
    if status.get("status") != "queued":
        raise ValueError("subtitle preview job status must be queued and never replayed")
    conflicts = [
        job_directory / "manifest.json",
        job_directory / "ffmpeg.log",
        job_directory / "progress.jsonl",
        *job_directory.glob("*.ass"),
        *job_directory.glob("*.mkv"),
        *job_directory.glob("*.mp4"),
        *job_directory.glob("*.mov"),
        *job_directory.glob("*.webm"),
    ]
    existing = sorted({path.resolve() for path in conflicts if path.exists()})
    if existing:
        raise FileExistsError(
            "subtitle preview job contains existing formal evidence: "
            + ", ".join(path.name for path in existing)
        )


def _claim_job(job_directory: Path, spec_path: Path) -> None:
    claim_path = job_directory / "claim.json"
    try:
        with claim_path.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(
                {
                    "schema_version": "1.0",
                    "document_type": "subtitle_preview_job_claim",
                    "job_spec_sha256": _sha256_file(spec_path),
                    "claimed_at": _utc_now(),
                },
                output,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            output.write("\n")
    except FileExistsError as error:
        raise ValueError("subtitle preview job has already been claimed") from error


def submit_subtitle_preview_job(
    *,
    project: Path,
    base_video: Path,
    subtitle_source: Path,
    realized_timeline: Path,
    enhancement_plan: Path | None = None,
    readability_qa: Path | None = None,
    layout_qa: Path | None = None,
    scope: str = "all",
    proxy_unit: str = "timeline",
    padding_sec: float = 0.75,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    """Submit a durable worker that does not depend on the caller's console."""

    project = Path(project).resolve()
    base = Path(base_video).resolve()
    if not base.is_file():
        raise FileNotFoundError(base)
    _confined_path(
        project,
        Path(subtitle_source),
        "work/subtitles",
        "subtitle source",
    )
    _confined_path(
        project,
        Path(realized_timeline),
        "work/qa",
        "realized timeline",
    )
    job_directory = create_unique_preview_directory(project)
    spec_path = job_directory / "job.json"
    status_path = job_directory / "status.json"
    worker_log_path = job_directory / "worker.log"
    spec: dict[str, Any] = {
        "project": str(project),
        "base_video": str(base),
        "subtitle_source": str(Path(subtitle_source).resolve()),
        "realized_timeline": str(Path(realized_timeline).resolve()),
        "scope": scope,
        "proxy_unit": proxy_unit,
        "padding_sec": padding_sec,
        "output_directory": str(job_directory),
        "executable": executable,
    }
    for field, value in (
        ("enhancement_plan", enhancement_plan),
        ("readability_qa", readability_qa),
        ("layout_qa", layout_qa),
    ):
        if value is not None:
            spec[field] = str(Path(value).resolve())
    _write_json(spec_path, spec)
    _write_job_status(status_path, "queued", job_spec=str(spec_path))
    command = [
        sys.executable,
        "-m",
        "vlog_director.subtitle_preview_runtime",
        "--job-spec",
        str(spec_path),
    ]
    worker_log = worker_log_path.open("a", encoding="utf-8", newline="\n")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": worker_log,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    try:
        try:
            process = subprocess.Popen(command, **kwargs)
        except Exception as error:
            _write_job_status(
                status_path,
                "failed",
                job_spec=str(spec_path),
                worker_log=str(worker_log_path),
                error_type=type(error).__name__,
                error_message=str(error),
                exit_code=1,
            )
            raise
    finally:
        worker_log.close()
    return {
        "status": "queued",
        "pid": process.pid,
        "job_spec": str(spec_path),
        "job_status": str(status_path),
        "worker_log": str(worker_log_path),
        "output_directory": str(job_directory),
    }


def run_subtitle_preview_job(job_spec: Path) -> dict[str, Any]:
    spec_path = Path(job_spec).resolve()
    spec = _load_json(spec_path, "subtitle preview job spec")
    project, job_directory = _validated_job_directory(spec_path, spec)
    status_path = job_directory / "status.json"
    _assert_fresh_job(job_directory, status_path)
    _claim_job(job_directory, spec_path)
    _write_job_status(status_path, "running", job_spec=str(spec_path))
    try:
        arguments = dict(spec)
        arguments["project"] = project
        arguments["base_video"] = Path(arguments["base_video"])
        arguments["subtitle_source"] = Path(arguments["subtitle_source"])
        arguments["realized_timeline"] = Path(arguments["realized_timeline"])
        arguments["output_directory"] = job_directory
        for field in ("enhancement_plan", "readability_qa", "layout_qa"):
            if field in arguments:
                arguments[field] = Path(arguments[field])
        arguments["_reuse_output_directory"] = True
        manifest = render_subtitle_preview(**arguments)
    except Exception as error:
        _write_job_status(
            status_path,
            "failed",
            job_spec=str(spec_path),
            error_type=type(error).__name__,
            error_message=str(error),
            exit_code=1,
        )
        raise
    _write_job_status(
        status_path,
        "completed",
        job_spec=str(spec_path),
        manifest_path=str(spec_path.parent / "manifest.json"),
        exit_code=0,
    )
    return manifest


def _main() -> int:
    parser = argparse.ArgumentParser(description="Internal durable subtitle preview worker")
    parser.add_argument("--job-spec", type=Path, required=True)
    args = parser.parse_args()
    run_subtitle_preview_job(args.job_spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
