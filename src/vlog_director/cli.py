from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .protection import validate_protection
from .renderers import load_json, render_enhanced_video, stabilize_video
from .project import (
    guard_project_enhancement,
    guard_project_render,
    init_project,
    init_project_enhancement,
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subtitle_failure(code: str, error: object) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "blocked",
        "blocker_codes": [code],
        "issues": [{"code": code, "message": str(error)}],
    }


def _write_subtitle_job_status(
    path: Path | None,
    status: str,
    **fields: Any,
) -> None:
    if path is None:
        return
    status_path = Path(path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        {"schema_version": "1.0", "status": status, **fields},
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    temporary = status_path.with_name(
        f".{status_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(serialized + "\n", encoding="utf-8")
        os.replace(temporary, status_path)
    finally:
        temporary.unlink(missing_ok=True)


def _confined_subtitle_job_status(
    project: Path,
    path: Path | None,
    job_kind: str,
) -> Path | None:
    if path is None:
        return None
    project_root = Path(project).resolve()
    allowed_root = (project_root / "work" / "jobs" / job_kind).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError(
            f"hidden subtitle job status path must stay under project/work/jobs/{job_kind}"
        ) from error
    if (
        len(relative.parts) != 2
        or relative.parts[-1] != "status.json"
        or len(relative.parts[0]) != 32
        or any(character not in "0123456789abcdef" for character in relative.parts[0])
        or not resolved.is_file()
    ):
        raise ValueError(
            "hidden subtitle job status must reference an existing UUID job status.json"
        )
    spec_path = resolved.parent / "job.json"
    if not spec_path.is_file():
        raise ValueError("hidden subtitle job status is missing its bound job.json")
    spec = _read_json(spec_path)
    expected_arguments = spec.get("arguments")
    if (
        spec.get("schema_version") != "1.0"
        or spec.get("job_kind") != job_kind
        or not isinstance(expected_arguments, list)
        or not all(isinstance(value, str) for value in expected_arguments)
        or expected_arguments != sys.argv[1:]
    ):
        raise ValueError(
            "hidden subtitle job status does not bind the current worker arguments"
        )
    return resolved


def _submit_detached_subtitle_cli(
    project: Path,
    job_kind: str,
) -> dict[str, Any]:
    project_root = Path(project).resolve()
    jobs_root = project_root / "work" / "jobs" / job_kind
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_directory = jobs_root / uuid.uuid4().hex
    job_directory.mkdir()
    status_path = job_directory / "status.json"
    spec_path = job_directory / "job.json"
    worker_log_path = job_directory / "worker.log"
    child_arguments = [*sys.argv[1:], "--foreground", "--job-status", str(status_path)]
    command = [sys.executable, "-m", "vlog_director.cli", *child_arguments]
    _write_result(
        {
            "schema_version": "1.0",
            "job_kind": job_kind,
            "arguments": child_arguments,
        },
        spec_path,
    )
    _write_subtitle_job_status(status_path, "queued", job_spec=str(spec_path))
    worker_log = worker_log_path.open("a", encoding="utf-8", newline="\n")
    popen_arguments: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": worker_log,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        popen_arguments["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        popen_arguments["start_new_session"] = True
    try:
        try:
            process = subprocess.Popen(command, **popen_arguments)
        except Exception as error:
            _write_subtitle_job_status(
                status_path,
                "failed",
                job_spec=str(spec_path),
                worker_log=str(worker_log_path),
                error=str(error),
            )
            raise
    finally:
        worker_log.close()
    return {
        "schema_version": "1.0",
        "status": "queued",
        "pid": process.pid,
        "job_spec": str(spec_path),
        "job_status": str(status_path),
        "worker_log": str(worker_log_path),
    }


def _project_artifact(
    project: Path,
    value: Path,
    root: str,
    label: str,
    *,
    must_exist: bool = True,
) -> Path:
    project_root = Path(project).resolve()
    candidate = Path(value)
    resolved = (project_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    allowed_root = (project_root / root).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {allowed_root}") from error
    if must_exist and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _require_new_distinct_outputs(
    outputs: list[Path],
    *,
    protected_inputs: list[Path] | None = None,
) -> None:
    resolved_outputs = [Path(path).resolve() for path in outputs]
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("subtitle output paths must be distinct")
    protected = {
        Path(path).resolve() for path in (protected_inputs or [])
    }
    overlap = [path for path in resolved_outputs if path in protected]
    if overlap:
        raise ValueError(
            "subtitle output must not overwrite an input: " + str(overlap[0])
        )
    existing = [path for path in resolved_outputs if path.exists()]
    if existing:
        raise FileExistsError(
            "subtitle output already exists; choose a new versioned path: "
            + str(existing[0])
        )


def _subtitle_style(plan: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    subtitles = plan.get("subtitles")
    if isinstance(subtitles, dict) and isinstance(subtitles.get("style"), dict):
        return dict(subtitles["style"])
    if source is not None and isinstance(source.get("style"), dict):
        return dict(source["style"])
    return {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vlog-director")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-protection")
    validate.add_argument("--moments", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--policy", type=Path)
    validate.add_argument("--output", type=Path)

    init = subparsers.add_parser("init-project")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--project-id", required=True)

    guard = subparsers.add_parser("guard-render")
    guard.add_argument("--project", type=Path, required=True)
    guard.add_argument("--version", type=int, required=True)
    guard.add_argument("--policy", type=Path)

    init_enhancement = subparsers.add_parser("init-enhancement")
    init_enhancement.add_argument("--project", type=Path, required=True)
    init_enhancement.add_argument("--version", type=int, required=True)

    guard_enhancement = subparsers.add_parser("guard-enhancement")
    guard_enhancement.add_argument("--project", type=Path, required=True)
    guard_enhancement.add_argument("--version", type=int, required=True)
    guard_enhancement.add_argument("--realized-timeline", type=Path)
    guard_enhancement.add_argument(
        "--mode",
        choices=["preview", "release"],
        default="preview",
    )

    stabilize = subparsers.add_parser("stabilize")
    stabilize.add_argument("--input", type=Path, required=True)
    stabilize.add_argument("--output", type=Path, required=True)
    stabilize.add_argument("--work-directory", type=Path, required=True)
    stabilize.add_argument("--strength", type=float, default=0.35)
    stabilize.add_argument("--max-crop-percent", type=float, default=8.0)
    stabilize.add_argument("--ffmpeg-executable", default="ffmpeg")

    render_enhancement = subparsers.add_parser("render-enhancement")
    render_enhancement.add_argument("--project", type=Path, required=True)
    render_enhancement.add_argument("--base-video", type=Path, required=True)
    render_enhancement.add_argument("--plan", type=Path, required=True)
    render_enhancement.add_argument("--output", type=Path, required=True)
    render_enhancement.add_argument("--qa-output", type=Path)
    render_enhancement.add_argument("--ffmpeg-executable", default="ffmpeg")
    render_enhancement.add_argument("--realized-timeline", type=Path)
    render_enhancement.add_argument(
        "--mode",
        choices=["preview", "release"],
        default="preview",
    )
    render_enhancement.add_argument(
        "--video-preset",
        choices=[
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        default="medium",
    )
    render_enhancement.add_argument("--video-crf", type=int, default=18)

    qa_music = subparsers.add_parser("qa-music")
    qa_music.add_argument("--media", type=Path, required=True)
    qa_music.add_argument("--plan", type=Path, required=True)
    qa_music.add_argument("--output", type=Path, required=True)
    qa_music.add_argument("--ffmpeg-executable", default="ffmpeg")

    analyze_reference = subparsers.add_parser("analyze-reference")
    analyze_reference.add_argument("--input", type=Path, required=True)
    analyze_reference.add_argument("--source-id", required=True)
    analyze_reference.add_argument("--url", required=True)
    analyze_reference.add_argument("--work-directory", type=Path, required=True)
    analyze_reference.add_argument("--output", type=Path, required=True)
    analyze_reference.add_argument("--portable-output", type=Path)
    analyze_reference.add_argument("--transcript", type=Path)
    analyze_reference.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_reference.add_argument("--asr-model", default="base")
    analyze_reference.add_argument("--language", default="zh")
    analyze_reference.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_reference.add_argument("--visual-fps", type=float, default=2.0)
    analyze_reference.add_argument("--review-directory", type=Path)
    analyze_reference.add_argument("--review-event-limit", type=int, default=12)

    aggregate_reference = subparsers.add_parser("aggregate-reference")
    aggregate_reference.add_argument(
        "--analysis",
        type=Path,
        nargs="+",
        required=True,
    )
    aggregate_reference.add_argument("--profile", type=Path, nargs="*")
    aggregate_reference.add_argument("--output", type=Path, required=True)

    pack_reference = subparsers.add_parser("pack-reference-context")
    pack_reference.add_argument("--analysis", type=Path, required=True)
    pack_reference.add_argument("--output", type=Path, required=True)
    pack_reference.add_argument("--max-characters", type=int, default=180_000)

    preflight_model_request = subparsers.add_parser("preflight-model-request")
    preflight_model_request.add_argument("--request", type=Path, required=True)
    preflight_model_request.add_argument("--max-bytes", type=int, default=200_000)

    aggregate_techniques = subparsers.add_parser("aggregate-techniques")
    aggregate_techniques.add_argument(
        "--study",
        type=Path,
        nargs="+",
        required=True,
    )
    aggregate_techniques.add_argument("--output", type=Path, required=True)
    aggregate_techniques.add_argument("--minimum-source-support", type=int)

    compare_revision = subparsers.add_parser("compare-revision")
    compare_revision.add_argument("--parent", type=Path, required=True)
    compare_revision.add_argument("--candidate", type=Path, required=True)
    compare_revision.add_argument("--minimum-change-ratio", type=float, default=0.08)
    compare_revision.add_argument("--output", type=Path)

    compile_revision_parser = subparsers.add_parser("compile-revision")
    compile_revision_parser.add_argument("--parent", type=Path, required=True)
    compile_revision_parser.add_argument("--profile", type=Path, required=True)
    compile_revision_parser.add_argument("--directives", type=Path, required=True)
    compile_revision_parser.add_argument("--output", type=Path, required=True)
    compile_revision_parser.add_argument("--report", type=Path)

    analyze_target = subparsers.add_parser("analyze-target")
    analyze_target.add_argument("--input", type=Path, required=True)
    analyze_target.add_argument("--source", required=True)
    analyze_target.add_argument("--work-directory", type=Path, required=True)
    analyze_target.add_argument("--output", type=Path, required=True)
    analyze_target.add_argument("--transcript", type=Path)
    analyze_target.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_target.add_argument("--asr-model", default="small")
    analyze_target.add_argument("--language", default="zh")
    analyze_target.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_target.add_argument("--visual-fps", type=float, default=2.0)

    analyze_project = subparsers.add_parser("analyze-project")
    analyze_project.add_argument("--project", type=Path, required=True)
    analyze_project.add_argument("--output-directory", type=Path, required=True)
    analyze_project.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_project.add_argument("--asr-model", default="small")
    analyze_project.add_argument("--language", default="zh")
    analyze_project.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_project.add_argument("--visual-fps", type=float, default=2.0)

    direct_timeline_parser = subparsers.add_parser("direct-timeline")
    direct_timeline_parser.add_argument("--parent", type=Path, required=True)
    direct_timeline_parser.add_argument("--analysis", type=Path, nargs="*", default=[])
    direct_timeline_parser.add_argument("--analysis-directory", type=Path)
    direct_timeline_parser.add_argument("--profile", type=Path, required=True)
    direct_timeline_parser.add_argument("--technique-profile", type=Path)
    direct_timeline_parser.add_argument("--moments", type=Path, required=True)
    direct_timeline_parser.add_argument(
        "--feedback",
        type=Path,
        help="Optional explicit user shot decisions; these override reference priors.",
    )
    direct_timeline_parser.add_argument("--version", type=int, required=True)
    direct_timeline_parser.add_argument("--output-directory", type=Path, required=True)
    direct_timeline_parser.add_argument("--target-duration-sec", type=float)
    direct_timeline_parser.add_argument("--minimum-change-ratio", type=float, default=0.08)
    direct_timeline_parser.add_argument(
        "--variants",
        nargs="+",
        choices=["concise", "balanced", "immersive"],
        default=["concise", "balanced", "immersive"],
    )

    approve_timeline_parser = subparsers.add_parser("approve-timeline")
    approve_timeline_parser.add_argument("--candidate", type=Path, required=True)
    approve_timeline_parser.add_argument("--output", type=Path, required=True)
    approve_timeline_parser.add_argument("--receipt", type=Path, required=True)
    approve_timeline_parser.add_argument("--approved-by", required=True)

    plan_music = subparsers.add_parser("plan-music")
    plan_music.add_argument("--plan", type=Path, required=True)
    plan_music.add_argument("--profile", type=Path, required=True)
    plan_music.add_argument("--subtitles", type=Path)
    plan_music.add_argument("--dialogue-padding-sec", type=float, default=0.35)
    plan_music.add_argument("--output", type=Path, required=True)

    project_subtitles = subparsers.add_parser(
        "project-subtitles",
        description="Project word-level ASR onto a realized edit timeline.",
    )
    project_subtitles.add_argument("--project", type=Path, required=True, help="Project root used to confine every subtitle artifact.")
    project_subtitles.add_argument("--edit-plan", type=Path, required=True, help="Approved edit plan JSON.")
    project_subtitles.add_argument("--realized-timeline", type=Path, required=True, help="Realized render timeline JSON.")
    project_subtitles.add_argument("--analysis", type=Path, action="append", required=True, help="Target analysis JSON; repeat for every source.")
    project_subtitles.add_argument("--subtitle-version", type=int, required=True, help="Positive subtitle source version.")
    project_subtitles.add_argument("--draft-output", type=Path, required=True, help="UTF-8 subtitle review draft JSON.")
    project_subtitles.add_argument("--review-output", type=Path, required=True, help="UTF-8 human review record JSON.")
    project_subtitles.add_argument("--srt-output", type=Path, help="Optional UTF-8 SRT convenience export.")

    audit_subtitles = subparsers.add_parser(
        "audit-subtitles",
        description="Audit subtitle timing and reading speed with a versioned policy.",
    )
    audit_subtitles.add_argument("--project", type=Path, required=True, help="Project root used to confine subtitle and QA artifacts.")
    audit_subtitles.add_argument("--subtitle-source", type=Path, required=True, help="Subtitle draft/review/ready JSON.")
    audit_subtitles.add_argument("--realized-timeline", type=Path, required=True, help="Realized timeline bound by SHA-256.")
    audit_subtitles.add_argument("--output", type=Path, required=True, help="Readability QA JSON output.")
    audit_subtitles.add_argument("--policy", type=Path, help="Optional strict readability policy JSON.")
    audit_subtitles.add_argument("--mode", choices=["preview", "release"], default="preview", help="Preview warns; release fails closed.")

    probe_layout = subparsers.add_parser(
        "probe-subtitle-layout",
        description="Measure the exact ASS layout using the selected FFmpeg/libass.",
    )
    probe_layout.add_argument("--project", type=Path, required=True, help="Project root containing work and assets.")
    probe_layout.add_argument("--base-video", type=Path, required=True, help="Explicit base/preview media used for canvas geometry.")
    probe_layout.add_argument("--subtitle-source", type=Path, required=True, help="Project subtitle source JSON.")
    probe_layout.add_argument("--plan", type=Path, required=True, help="Enhancement plan supplying the render style.")
    probe_layout.add_argument("--realized-timeline", type=Path, required=True, help="Realized timeline JSON.")
    probe_layout.add_argument("--readability-qa", type=Path, required=True, help="Current readability QA JSON.")
    probe_layout.add_argument("--output", type=Path, required=True, help="Layout QA JSON output under work/qa.")
    probe_layout.add_argument("--cache-directory", type=Path, help="Optional content-hash cache under work/qa.")
    probe_layout.add_argument("--fonts-directory", type=Path, help="Explicit font directory; missing fonts fail according to mode.")
    probe_layout.add_argument("--ffmpeg-executable", default="ffmpeg", help="Explicit FFmpeg executable with libass.")
    probe_layout.add_argument("--mode", choices=["preview", "release"], default="preview", help="Preview permits declared heuristic fallback; release blocks it.")

    render_subtitle_preview = subparsers.add_parser(
        "render-subtitle-preview",
        description="Render subtitle-only proxy media; no treatments, music, ducking, or overlays.",
    )
    render_subtitle_preview.add_argument("--project", type=Path, required=True, help="Project root.")
    render_subtitle_preview.add_argument("--base-video", type=Path, required=True, help="Explicit user-selected base/preview media; no fallback.")
    render_subtitle_preview.add_argument("--subtitle-source", type=Path, required=True, help="Subtitle source under work/subtitles.")
    render_subtitle_preview.add_argument("--realized-timeline", type=Path, required=True, help="Realized timeline under work/qa.")
    render_subtitle_preview.add_argument("--plan", type=Path, help="Optional enhancement plan used only for subtitle style binding.")
    render_subtitle_preview.add_argument("--readability-qa", type=Path, help="Readability QA; mandatory for risk scope.")
    render_subtitle_preview.add_argument("--layout-qa", type=Path, help="Optional current layout QA binding.")
    render_subtitle_preview.add_argument("--scope", choices=["all", "risk"], default="all", help="Render all cues or only the readability risk queue.")
    render_subtitle_preview.add_argument("--proxy-unit", choices=["timeline", "cue", "segment", "chapter"], default="timeline", help="Proxy grouping granularity.")
    render_subtitle_preview.add_argument("--padding-sec", type=float, default=0.75, help="Risk proxy context before and after a cue.")
    render_subtitle_preview.add_argument("--output-directory", type=Path, help="Explicit empty output directory under work/proxy.")
    render_subtitle_preview.add_argument("--manifest-output", type=Path, help="Optional explicit copy of the completed manifest under work/proxy.")
    render_subtitle_preview.add_argument("--ffmpeg-executable", default="ffmpeg", help="Explicit FFmpeg executable with libass.")
    render_subtitle_preview.add_argument("--foreground", action="store_true", help="Run synchronously; default submits a detached durable job.")
    render_subtitle_preview.add_argument("--job-status", type=Path, help=argparse.SUPPRESS)

    qa_subtitles = subparsers.add_parser(
        "qa-subtitles",
        description="Generate bound subtitle visual evidence and contact sheets.",
    )
    qa_subtitles.add_argument("--project", type=Path, required=True, help="Project root.")
    qa_subtitles.add_argument("--preview-manifest", type=Path, required=True, help="Completed subtitle proxy manifest.")
    qa_subtitles.add_argument("--readability-qa", type=Path, required=True, help="Exact readability QA bound by the manifest.")
    qa_subtitles.add_argument("--layout-qa", type=Path, required=True, help="Exact layout QA bound by the manifest.")
    qa_subtitles.add_argument("--output", type=Path, required=True, help="Visual QA report under work/qa.")
    qa_subtitles.add_argument("--evidence-directory", type=Path, help="Explicit empty evidence directory under work/qa.")
    qa_subtitles.add_argument("--ffmpeg-executable", default="ffmpeg", help="Explicit FFmpeg executable used by the proxy.")
    qa_subtitles.add_argument("--foreground", action="store_true", help="Run synchronously; default submits a detached durable job.")
    qa_subtitles.add_argument("--job-status", type=Path, help=argparse.SUPPRESS)

    approve_subtitles = subparsers.add_parser(
        "approve-subtitles",
        description="Build a SHA-bound approval and immutable ready subtitle source.",
    )
    approve_subtitles.add_argument("--project", type=Path, required=True, help="Project root.")
    approve_subtitles.add_argument("--subtitle-source", type=Path, required=True, help="Verified review source; status edits alone are insufficient.")
    approve_subtitles.add_argument("--plan", type=Path, required=True, help="Enhancement plan supplying the exact subtitle style.")
    approve_subtitles.add_argument("--readability-qa", type=Path, required=True, help="Passing release readability QA.")
    approve_subtitles.add_argument("--layout-qa", type=Path, required=True, help="Passing real-libass layout QA.")
    approve_subtitles.add_argument("--visual-qa", type=Path, required=True, help="Current visual QA evidence.")
    approve_subtitles.add_argument("--human-review", type=Path, required=True, help="Independent approved human review record.")
    approve_subtitles.add_argument("--approved-by", required=True, help="Reviewer identity matching the human review.")
    approve_subtitles.add_argument("--approval-output", type=Path, required=True, help="New approval receipt under work/qa.")
    approve_subtitles.add_argument("--ready-source-output", type=Path, required=True, help="New immutable ready subtitle source under work/subtitles.")
    approve_subtitles.add_argument("--evidence-output", type=Path, help="Optional subtitle-ready-evidence-v1 JSON under work/qa.")

    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "project-subtitles":
        try:
            from .subtitle_projection import (
                build_subtitle_review_record,
                project_asr_to_realized_timeline,
                write_subtitle_review_bundle,
            )

            project = args.project.resolve()
            edit_plan_path = _project_artifact(
                project, args.edit_plan, "work/plans", "edit plan"
            )
            timeline_path = _project_artifact(
                project, args.realized_timeline, "work/qa", "realized timeline"
            )
            analysis_paths = [
                _project_artifact(project, path, "work/analysis", "analysis")
                for path in args.analysis
            ]
            draft_output = _project_artifact(
                project, args.draft_output, "work/subtitles", "subtitle draft output", must_exist=False
            )
            review_output = _project_artifact(
                project, args.review_output, "work/subtitles", "subtitle review output", must_exist=False
            )
            srt_output = (
                _project_artifact(project, args.srt_output, "work/subtitles", "subtitle SRT output", must_exist=False)
                if args.srt_output else None
            )
            outputs = [draft_output, review_output, *([srt_output] if srt_output else [])]
            _require_new_distinct_outputs(
                outputs,
                protected_inputs=[edit_plan_path, timeline_path, *analysis_paths],
            )
            draft = project_asr_to_realized_timeline(
                _read_json(edit_plan_path),
                _read_json(timeline_path),
                [_read_json(path) for path in analysis_paths],
                subtitle_version=args.subtitle_version,
            )
            review = build_subtitle_review_record(
                draft,
                draft_path=draft_output.name,
            )
            write_subtitle_review_bundle(
                draft,
                review,
                draft_output=draft_output,
                review_output=review_output,
                srt_output=srt_output,
            )
            _write_result(
                {
                    "status": "review_required",
                    "cue_count": len(draft.get("cues", [])),
                    "draft_output": str(draft_output),
                    "review_output": str(review_output),
                    "srt_output": str(srt_output) if srt_output else None,
                },
                None,
            )
            return 0
        except Exception as error:
            result = _subtitle_failure("subtitle_projection_failed", error)
            _write_result(result, None)
            return 2
    if args.command == "audit-subtitles":
        try:
            from .subtitle_readability import (
                SubtitleReadabilityPolicy,
                audit_subtitle_readability,
            )

            project = args.project.resolve()
            source_path = _project_artifact(
                project, args.subtitle_source, "work/subtitles", "subtitle source"
            )
            timeline_path = _project_artifact(
                project, args.realized_timeline, "work/qa", "realized timeline"
            )
            output_path = _project_artifact(
                project, args.output, "work/qa", "readability QA output", must_exist=False
            )
            policy_path = (
                _project_artifact(project, args.policy, "work/qa", "readability policy")
                if args.policy else None
            )
            _require_new_distinct_outputs(
                [output_path],
                protected_inputs=[source_path, timeline_path, *([policy_path] if policy_path else [])],
            )
            policy = (
                SubtitleReadabilityPolicy.from_dict(_read_json(policy_path))
                if policy_path
                else SubtitleReadabilityPolicy()
            )
            report = audit_subtitle_readability(
                _read_json(source_path),
                policy=policy,
                mode=args.mode,
                subtitle_source_sha256=_sha256_file(source_path),
                realized_timeline_sha256=_sha256_file(timeline_path),
            )
            _write_result(report, output_path)
            return 2 if report["status"] == "blocked" else 0
        except Exception as error:
            result = _subtitle_failure("subtitle_readability_audit_failed", error)
            _write_result(result, None)
            return 2
    if args.command == "probe-subtitle-layout":
        try:
            from .ffmpeg import probe_media
            from .subtitle_layout_probe import probe_subtitle_layout
            from .subtitle_render_contract import (
                build_subtitle_render_contract,
                write_contract_ass,
            )

            project = args.project.resolve()
            source_path = _project_artifact(project, args.subtitle_source, "work/subtitles", "subtitle source")
            plan_path = _project_artifact(project, args.plan, "work/enhancement", "enhancement plan")
            timeline_path = _project_artifact(project, args.realized_timeline, "work/qa", "realized timeline")
            readability_path = _project_artifact(project, args.readability_qa, "work/qa", "readability QA")
            output_path = _project_artifact(project, args.output, "work/qa", "layout QA output", must_exist=False)
            cache_directory = (
                _project_artifact(project, args.cache_directory, "work/qa", "layout cache", must_exist=False)
                if args.cache_directory
                else None
            )
            _require_new_distinct_outputs(
                [output_path],
                protected_inputs=[source_path, plan_path, timeline_path, readability_path],
            )
            if cache_directory is not None:
                if cache_directory == output_path:
                    raise ValueError("layout cache and QA output paths must differ")
                if cache_directory.exists() and not cache_directory.is_dir():
                    raise ValueError("layout cache path must be a directory")
            source = _read_json(source_path)
            plan = _read_json(plan_path)
            readability = _read_json(readability_path)
            source_sha = _sha256_file(source_path)
            timeline_sha = _sha256_file(timeline_path)
            if readability.get("subtitle_source_sha256") != source_sha:
                raise ValueError("readability QA subtitle source SHA-256 mismatch")
            if readability.get("realized_timeline_sha256") != timeline_sha:
                raise ValueError("readability QA realized timeline SHA-256 mismatch")
            policy = readability.get("policy")
            if not isinstance(policy, dict):
                raise ValueError("readability QA policy content is invalid")
            policy_sha = hashlib.sha256(
                json.dumps(
                    policy,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if readability.get("policy_sha256") != policy_sha:
                raise ValueError(
                    "readability QA policy SHA-256 does not match canonical policy content"
                )
            if policy.get("policy_version") != readability.get("policy_version"):
                raise ValueError(
                    "readability QA policy version does not match policy content"
                )
            base_video = args.base_video.resolve()
            if not base_video.is_file():
                raise FileNotFoundError(base_video)
            media = probe_media(args.ffmpeg_executable, base_video)
            style = _subtitle_style(plan, source)
            contract = build_subtitle_render_contract(
                project,
                style,
                canvas_width=int(media["width"]),
                canvas_height=int(media["height"]),
            )
            cues = source.get("cues")
            if not isinstance(cues, list) or not all(isinstance(cue, dict) for cue in cues):
                raise ValueError("subtitle source cues must be an array of objects")
            qa_root = project / "work" / "qa"
            qa_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="subtitle-layout-ass-", dir=qa_root) as temporary:
                ass_path = write_contract_ass(cues, contract, Path(temporary) / "probe.ass")
                fonts_directory = (
                    _project_artifact(project, args.fonts_directory, "assets/fonts", "font directory", must_exist=False)
                    if args.fonts_directory
                    else Path(contract.fonts_directory) if contract.fonts_directory else None
                )
                report = probe_subtitle_layout(
                    ass_path=ass_path,
                    cues=cues,
                    style=contract.payload(),
                    style_binding=style,
                    canvas_width=contract.canvas_width,
                    canvas_height=contract.canvas_height,
                    executable=args.ffmpeg_executable,
                    mode=args.mode,
                    project_id=str(source.get("project_id", "")),
                    subtitle_source_sha256=source_sha,
                    realized_timeline_sha256=timeline_sha,
                    readability_qa_sha256=_sha256_file(readability_path),
                    readability_policy_sha256=policy_sha,
                    readability_policy_version=str(readability.get("policy_version", "")),
                    fonts_directory=fonts_directory,
                    enhancement_plan_sha256=_sha256_file(plan_path),
                    subtitle_source_path=source_path.relative_to(project).as_posix(),
                    cache_directory=cache_directory,
                )
            _write_result(report, output_path)
            return 2 if report["status"] == "blocked" else 0
        except Exception as error:
            result = _subtitle_failure("subtitle_layout_probe_failed", error)
            _write_result(result, None)
            return 2
    if args.command == "render-subtitle-preview":
        if args.scope == "risk" and args.readability_qa is None:
            result = _subtitle_failure(
                "subtitle_readability_qa_required_for_risk_scope",
                "risk scope requires --readability-qa before media inspection",
            )
            _write_result(result, None)
            return 2
        if not args.foreground:
            try:
                result = _submit_detached_subtitle_cli(args.project, "subtitle-preview")
                _write_result(result, None)
                return 0
            except Exception as error:
                result = _subtitle_failure("subtitle_preview_submission_failed", error)
                _write_result(result, None)
                return 2
        try:
            project = args.project.resolve()
            job_status = _confined_subtitle_job_status(
                project, args.job_status, "subtitle-preview"
            )
        except Exception as error:
            result = _subtitle_failure("subtitle_job_status_path_invalid", error)
            _write_result(result, None)
            return 2
        _write_subtitle_job_status(job_status, "running")
        try:
            from .subtitle_preview import render_subtitle_preview

            source_path = _project_artifact(project, args.subtitle_source, "work/subtitles", "subtitle source")
            timeline_path = _project_artifact(project, args.realized_timeline, "work/qa", "realized timeline")
            plan_path = _project_artifact(project, args.plan, "work/enhancement", "enhancement plan") if args.plan else None
            readability_path = _project_artifact(project, args.readability_qa, "work/qa", "readability QA") if args.readability_qa else None
            layout_path = _project_artifact(project, args.layout_qa, "work/qa", "layout QA") if args.layout_qa else None
            output_directory = _project_artifact(project, args.output_directory, "work/proxy", "preview output directory", must_exist=False) if args.output_directory else None
            manifest_output = _project_artifact(project, args.manifest_output, "work/proxy", "preview manifest output", must_exist=False) if args.manifest_output else None
            if manifest_output is not None:
                _require_new_distinct_outputs(
                    [manifest_output],
                    protected_inputs=[
                        source_path,
                        timeline_path,
                        *([plan_path] if plan_path else []),
                        *([readability_path] if readability_path else []),
                        *([layout_path] if layout_path else []),
                    ],
                )
                if output_directory is not None and manifest_output.is_relative_to(output_directory):
                    raise ValueError("preview manifest copy must stay outside the proxy output directory")
            result = render_subtitle_preview(
                project=project,
                base_video=args.base_video.resolve(),
                subtitle_source=source_path,
                realized_timeline=timeline_path,
                enhancement_plan=plan_path,
                readability_qa=readability_path,
                layout_qa=layout_path,
                scope=args.scope,
                proxy_unit=args.proxy_unit,
                padding_sec=args.padding_sec,
                output_directory=output_directory,
                executable=args.ffmpeg_executable,
            )
            if manifest_output is not None:
                _write_result(result, manifest_output)
            _write_subtitle_job_status(
                job_status,
                "completed",
                manifest_path=result.get("manifest_path"),
                exit_code=0,
            )
            _write_result(result, None)
            return 0
        except Exception as error:
            result = _subtitle_failure("subtitle_preview_failed", error)
            _write_subtitle_job_status(job_status, "failed", error=str(error), exit_code=2)
            _write_result(result, None)
            return 2
    if args.command == "qa-subtitles":
        job_status_path: Path | None = None
        try:
            project = args.project.resolve()
            job_status_path = _confined_subtitle_job_status(
                project, args.job_status, "subtitle-visual-qa"
            )
            manifest_path = _project_artifact(project, args.preview_manifest, "work/proxy", "preview manifest")
            readability_path = _project_artifact(project, args.readability_qa, "work/qa", "readability QA")
            layout_path = _project_artifact(project, args.layout_qa, "work/qa", "layout QA")
            manifest = _read_json(manifest_path)
            manifest_bindings = manifest.get("bindings")
            if not isinstance(manifest_bindings, dict):
                raise ValueError("preview manifest bindings are missing")
            for binding_name, bound_path in (("readability_qa", readability_path), ("layout_qa", layout_path)):
                binding = manifest_bindings.get(binding_name)
                if not isinstance(binding, dict) or binding.get("sha256") != _sha256_file(bound_path):
                    raise ValueError(f"{binding_name} SHA-256 does not match preview manifest")
            if not args.foreground:
                result = _submit_detached_subtitle_cli(project, "subtitle-visual-qa")
                _write_result(result, None)
                return 0
            _write_subtitle_job_status(job_status_path, "running")
            from .subtitle_visual_qa import qa_subtitles

            output_path = _project_artifact(project, args.output, "work/qa", "visual QA output", must_exist=False)
            evidence_directory = _project_artifact(project, args.evidence_directory, "work/qa", "visual QA evidence", must_exist=False) if args.evidence_directory else None
            _require_new_distinct_outputs(
                [output_path],
                protected_inputs=[manifest_path, readability_path, layout_path],
            )
            if evidence_directory is not None and evidence_directory.exists() and not evidence_directory.is_dir():
                raise ValueError("visual QA evidence path must be a directory")
            result = qa_subtitles(
                project=project,
                preview_manifest=manifest_path,
                output=output_path,
                evidence_directory=evidence_directory,
                executable=args.ffmpeg_executable,
            )
            final_status = "blocked" if result.get("status") == "blocked" else "completed"
            _write_subtitle_job_status(
                job_status_path,
                final_status,
                report_path=result.get("report_path"),
                exit_code=2 if final_status == "blocked" else 0,
            )
            _write_result(result, None)
            return 2 if result.get("status") == "blocked" else 0
        except Exception as error:
            result = _subtitle_failure("subtitle_visual_qa_failed", error)
            _write_subtitle_job_status(job_status_path, "failed", error=str(error), exit_code=2)
            _write_result(result, None)
            return 2
    if args.command == "approve-subtitles":
        try:
            from .enhancement_assets import (
                SUBTITLE_READY_EVIDENCE_VERSION,
                subtitle_ready_evidence_contract_issues,
            )
            from .subtitle_approval import (
                build_subtitle_approval,
                create_ready_subtitle_source,
            )

            project = args.project.resolve()
            source_path = _project_artifact(project, args.subtitle_source, "work/subtitles", "subtitle review source")
            plan_path = _project_artifact(project, args.plan, "work/enhancement", "enhancement plan")
            readability_path = _project_artifact(project, args.readability_qa, "work/qa", "readability QA")
            layout_path = _project_artifact(project, args.layout_qa, "work/qa", "layout QA")
            visual_path = _project_artifact(project, args.visual_qa, "work/qa", "visual QA")
            human_path = _project_artifact(project, args.human_review, "work/qa", "human review")
            approval_output = _project_artifact(project, args.approval_output, "work/qa", "subtitle approval output", must_exist=False)
            ready_output = _project_artifact(project, args.ready_source_output, "work/subtitles", "ready subtitle output", must_exist=False)
            evidence_output = (
                _project_artifact(project, args.evidence_output, "work/qa", "ready subtitle evidence output", must_exist=False)
                if args.evidence_output
                else None
            )
            outputs = [approval_output, ready_output]
            if evidence_output is not None:
                outputs.append(evidence_output)
            if len(set(outputs)) != len(outputs):
                raise ValueError("subtitle approval outputs must use distinct paths")
            existing_outputs = [output for output in outputs if output.exists()]
            if existing_outputs:
                raise FileExistsError(existing_outputs[0])
            source = _read_json(source_path)
            approval = build_subtitle_approval(
                source_path,
                _subtitle_style(_read_json(plan_path), source),
                readability_path,
                layout_path,
                visual_path,
                human_path,
                args.approved_by,
                output_path=approval_output,
            )
            ready = create_ready_subtitle_source(source_path, approval_output, ready_output)

            def evidence_binding(path: Path) -> dict[str, str]:
                return {
                    "path": path.relative_to(project).as_posix(),
                    "sha256": _sha256_file(path),
                }

            ready_evidence = {
                "contract_version": SUBTITLE_READY_EVIDENCE_VERSION,
                "subtitle_payload_sha256": approval["subtitle_payload_sha256"],
                "subtitle_style_sha256": approval["subtitle_style_sha256"],
                "verified_cue_set_sha256": approval["verified_cue_set_sha256"],
                "readability": evidence_binding(readability_path),
                "layout": evidence_binding(layout_path),
                "visual": evidence_binding(visual_path),
                "human_review": evidence_binding(human_path),
                "approval": evidence_binding(approval_output),
            }
            evidence_issues = subtitle_ready_evidence_contract_issues(ready_evidence)
            if evidence_issues:
                raise ValueError(
                    "generated subtitle ready evidence is invalid: "
                    + "; ".join(evidence_issues)
                )
            if evidence_output is not None:
                _write_result(ready_evidence, evidence_output)
            _write_result(
                {
                    "status": "ready",
                    "approval_output": str(approval_output),
                    "ready_source_output": str(ready_output),
                    "approval_sha256": _sha256_file(approval_output),
                    "evidence_output": str(evidence_output) if evidence_output else None,
                    "ready_evidence": ready_evidence,
                    "cue_count": len(ready.get("cues", [])),
                    "approved_by": approval.get("approved_by"),
                },
                None,
            )
            return 0
        except Exception as error:
            result = _subtitle_failure("subtitle_approval_failed", error)
            _write_result(result, None)
            return 2
    if args.command == "validate-protection":
        policy = _read_json(args.policy) if args.policy else None
        result = validate_protection(
            _read_json(args.moments),
            _read_json(args.plan),
            policy=policy,
        )
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-project":
        _write_result(init_project(args.root, args.project_id), None)
        return 0
    if args.command == "guard-render":
        policy = _read_json(args.policy) if args.policy else None
        result = guard_project_render(args.project, args.version, policy=policy)
        _write_result(result, None)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-enhancement":
        _write_result(init_project_enhancement(args.project, args.version), None)
        return 0
    if args.command == "guard-enhancement":
        result = guard_project_enhancement(
            args.project,
            args.version,
            args.realized_timeline,
            mode=args.mode,
        )
        _write_result(result, None)
        return 0 if result["status"] in {"preview_ready", "ready"} else 2
    if args.command == "stabilize":
        stabilize_video(
            args.input,
            args.output,
            args.work_directory,
            strength=args.strength,
            max_crop_percent=args.max_crop_percent,
            executable=args.ffmpeg_executable,
        )
        _write_result({"status": "ready", "output": str(args.output.resolve())}, None)
        return 0
    if args.command == "render-enhancement":
        from .enhancement import (
            normalize_realized_timeline,
            normalize_enhancement_plan,
            validate_enhancement_plan,
        )
        from .enhancement_assets import validate_enhancement_assets
        from .schema_validation import enhancement_schema_errors
        from .release import release_readiness_issues, verify_rendered_media

        project = args.project.resolve()
        enhancement_plan, migrations = normalize_enhancement_plan(load_json(args.plan))
        schema_errors = enhancement_schema_errors(enhancement_plan)
        if schema_errors:
            result = {
                "status": "blocked",
                "mode": args.mode,
                "issues": [
                    {
                        "severity": "error",
                        "code": "enhancement_schema_invalid",
                        "subject_id": str(error.json_path),
                        "message": error.message,
                    }
                    for error in schema_errors
                ],
            }
            if migrations:
                result["migrations"] = migrations
            _write_result(result, None)
            return 2
        edit_version = enhancement_plan.get("edit_plan_version")
        edit_plan_path = project / "work" / "plans" / f"edit_plan.v{edit_version}.json"
        if not edit_plan_path.is_file():
            raise FileNotFoundError(f"edit plan is missing: {edit_plan_path}")
        edit_plan = load_json(edit_plan_path)
        realized_timeline_path = args.realized_timeline
        if realized_timeline_path is None:
            candidate = project / "work" / "qa" / f"render.v{edit_version}.json"
            realized_timeline_path = candidate if candidate.is_file() else None
        elif not realized_timeline_path.is_file():
            raise FileNotFoundError(realized_timeline_path)
        realized_timeline = (
            normalize_realized_timeline(
                edit_plan,
                load_json(realized_timeline_path),
                edit_plan_sha256=hashlib.sha256(edit_plan_path.read_bytes()).hexdigest(),
            )
            if realized_timeline_path is not None
            else None
        )
        validation = validate_enhancement_plan(
            edit_plan,
            enhancement_plan,
            realized_timeline=realized_timeline,
        )
        asset_issues = validate_enhancement_assets(project, enhancement_plan)
        if asset_issues:
            validation["issues"].extend(asset_issues)
            validation["blocking_count"] = sum(
                issue["severity"] == "error" for issue in validation["issues"]
            )
            validation["warning_count"] = sum(
                issue["severity"] == "warning" for issue in validation["issues"]
            )
            if validation["blocking_count"]:
                validation["status"] = "blocked"
        if args.mode == "release":
            release_issues = release_readiness_issues(enhancement_plan)
            if release_issues:
                validation["issues"].extend(release_issues)
                validation["blocking_count"] = sum(
                    issue["severity"] == "error"
                    for issue in validation["issues"]
                )
                validation["warning_count"] = sum(
                    issue["severity"] == "warning"
                    for issue in validation["issues"]
                )
                if validation["blocking_count"]:
                    validation["status"] = "blocked"
        if validation["status"] != "passed":
            validation["mode"] = args.mode
            if migrations:
                validation["migrations"] = migrations
            _write_result(validation, None)
            return 2
        render_enhanced_video(
            project,
            args.base_video.resolve(),
            enhancement_plan,
            args.output.resolve(),
            executable=args.ffmpeg_executable,
            realized_timeline=realized_timeline,
            video_preset=args.video_preset,
            video_crf=args.video_crf,
        )
        from .audio_qa import analyze_music_mix, write_music_mix_qa

        verification, verification_issues = verify_rendered_media(
            args.output.resolve(),
            enhancement_plan,
            realized_timeline=realized_timeline,
            executable=args.ffmpeg_executable,
        )
        if verification_issues:
            qa_report = {
                "schema_version": "1.0",
                "status": "blocked",
                "media": str(args.output.resolve()),
                "issues": verification_issues,
                "blocking_count": len(verification_issues),
                "warning_count": 0,
            }
        else:
            qa_report = analyze_music_mix(
                args.output.resolve(),
                enhancement_plan,
                executable=args.ffmpeg_executable,
            )
        qa_report["mode"] = args.mode
        qa_report["render_verification"] = verification
        qa_output = args.qa_output or args.output.with_suffix(".music-mix-qa.json")
        write_music_mix_qa(qa_report, qa_output.resolve())
        result = {
            "status": (
                "ready"
                if args.mode == "release" and qa_report["status"] == "passed"
                else "preview_ready"
                if args.mode == "preview" and qa_report["status"] == "passed"
                else "blocked"
            ),
            "mode": args.mode,
            "output": str(args.output.resolve()),
            "music_mix_qa": str(qa_output.resolve()),
            "qa_status": qa_report["status"],
            "render_verification": verification,
        }
        asset_warnings = [
            issue for issue in validation["issues"]
            if issue["severity"] == "warning"
        ]
        if asset_warnings:
            result["warnings"] = asset_warnings
        if migrations:
            result["migrations"] = migrations
        if realized_timeline_path is not None:
            result["realized_timeline"] = str(realized_timeline_path.resolve())
        _write_result(result, None)
        return 0 if qa_report["status"] == "passed" else 2
    if args.command == "qa-music":
        from .audio_qa import analyze_music_mix, write_music_mix_qa

        report = analyze_music_mix(
            args.media.resolve(),
            _read_json(args.plan),
            executable=args.ffmpeg_executable,
        )
        write_music_mix_qa(report, args.output.resolve())
        _write_result(report, None)
        return 0 if report["status"] == "passed" else 2
    if args.command == "analyze-reference":
        from .reference_learning import (
            analyze_reference,
            write_analysis,
            write_portable_analysis,
        )

        analysis = analyze_reference(
            args.input.resolve(),
            source_id=args.source_id,
            source_url=args.url,
            work_directory=args.work_directory.resolve(),
            transcript_path=args.transcript.resolve() if args.transcript else None,
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        write_analysis(analysis, args.output.resolve())
        if args.portable_output:
            write_portable_analysis(
                analysis,
                args.portable_output.resolve(),
            )
        review_events = 0
        if args.review_directory:
            from .review_pack import build_review_pack

            review = build_review_pack(
                args.input.resolve(),
                analysis,
                args.review_directory.resolve(),
                event_limit=args.review_event_limit,
            )
            review_events = len(review["events"])
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "shots": len(analysis["shots"]),
                "events": len(analysis["events"]),
                "asr_status": analysis["transcription"]["status"],
                "review_events": review_events,
            },
            None,
        )
        return 0
    if args.command == "analyze-target":
        from .reference_learning import analyze_reference, write_analysis

        analysis = analyze_reference(
            args.input.resolve(),
            source_id=Path(args.source).stem,
            source_url="local-target://" + args.source,
            work_directory=args.work_directory.resolve(),
            transcript_path=args.transcript.resolve() if args.transcript else None,
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        analysis["source"]["target_source"] = args.source
        analysis["source"]["aliases"] = [args.source, Path(args.source).name]
        write_analysis(analysis, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source": args.source,
                "shots": len(analysis["shots"]),
                "events": len(analysis["events"]),
                "transcript_status": analysis["transcription"].get("status"),
            },
            None,
        )
        return 0
    if args.command == "analyze-project":
        from .target_project import analyze_target_project

        result = analyze_target_project(
            args.project,
            args.output_directory.resolve(),
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        _write_result(result, None)
        return 0 if result["status"] == "ready" else 2
    if args.command == "direct-timeline":
        from datetime import datetime, timezone

        from .director_engine import direct_timeline, write_director_result
        from .technique_learning import load_technique_aggregate

        analysis_paths = list(args.analysis)
        if args.analysis_directory:
            analysis_paths.extend(
                sorted(args.analysis_directory.glob("target-analysis.*.json"))
            )
        result = direct_timeline(
            _read_json(args.parent),
            [_read_json(path) for path in analysis_paths],
            _read_json(args.profile),
            _read_json(args.moments),
            version=args.version,
            created_at=datetime.now(timezone.utc).isoformat(),
            target_duration_sec=args.target_duration_sec,
            minimum_change_ratio=args.minimum_change_ratio,
            variants=args.variants,
            technique_profile=(
                load_technique_aggregate(args.technique_profile)
                if args.technique_profile
                else None
            ),
            feedback_document=_read_json(args.feedback) if args.feedback else None,
        )
        write_director_result(result, args.output_directory.resolve())
        _write_result(
            {
                "status": result["status"],
                "recommended_variant": result.get("recommended_variant"),
                "technique_profile_id": result.get("technique_profile_id"),
                "output_directory": str(args.output_directory.resolve()),
                "missing_sources": result.get("missing_sources", []),
            },
            None,
        )
        return 0 if result["status"] in {"ready", "review_required"} else 2
    if args.command == "approve-timeline":
        from .approval import approve_timeline

        result = approve_timeline(
            args.candidate.resolve(),
            args.output.resolve(),
            args.receipt.resolve(),
            approved_by=args.approved_by,
        )
        _write_result(result, None)
        return 0
    if args.command == "compare-revision":
        from .revision import compare_revisions

        result = compare_revisions(
            _read_json(args.parent),
            _read_json(args.candidate),
            minimum_change_ratio=args.minimum_change_ratio,
        )
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    if args.command == "compile-revision":
        from .revision import compile_revision

        candidate, report = compile_revision(
            _read_json(args.parent),
            _read_json(args.profile),
            _read_json(args.directives),
        )
        _write_result(candidate, args.output)
        _write_result(report, args.report)
        return 0
    if args.command == "plan-music":
        from .music_direction import build_music_reference

        result = build_music_reference(
            _read_json(args.plan),
            _read_json(args.profile),
            _read_json(args.subtitles) if args.subtitles else None,
            dialogue_padding_sec=args.dialogue_padding_sec,
        )
        _write_result(result, args.output)
        return 0 if result["status"] in {"reference_ready", "no_music_suggestion"} else 2
    if args.command == "aggregate-reference":
        from .profile_aggregation import (
            aggregate_analyses,
            load_analysis,
            load_profile,
            write_aggregate,
        )

        profile = aggregate_analyses(
            [load_analysis(path) for path in args.analysis],
            [load_profile(path) for path in args.profile or []],
        )
        write_aggregate(profile, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source_count": profile["source_count"],
                "shared_rules": len(profile["shared_rules"]),
            },
            None,
        )
        return 0
    if args.command == "pack-reference-context":
        from .model_context import (
            build_reference_context_packet,
            serialized_model_request_size,
            write_reference_context_packet,
        )

        packet = build_reference_context_packet(
            _read_json(args.analysis),
            max_characters=args.max_characters,
        )
        characters = write_reference_context_packet(
            packet,
            args.output.resolve(),
        )
        size = serialized_model_request_size(
            json.dumps(packet, ensure_ascii=False, indent=2)
        )
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "serialized_characters": characters,
                "serialized_utf8_bytes": size["serialized_utf8_bytes"],
                "maximum_characters": args.max_characters,
                "hard_request_limit_utf8_bytes": 200_000,
            },
            None,
        )
        return 0
    if args.command == "preflight-model-request":
        from .model_context import (
            ModelContextLimitError,
            preflight_serialized_responses_request,
        )

        if args.max_bytes < 1:
            raise ValueError("max-bytes must be a positive integer")
        on_disk_bytes = args.request.stat().st_size
        if on_disk_bytes >= args.max_bytes:
            raise ModelContextLimitError(
                "model request file must be smaller than "
                f"{args.max_bytes:,} UTF-8 bytes; got {on_disk_bytes:,} bytes"
            )
        encoded_body = args.request.read_bytes()
        try:
            serialized = encoded_body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("model request must be valid UTF-8") from error
        size = preflight_serialized_responses_request(
            serialized,
            max_bytes=args.max_bytes,
        )
        _write_result(
            {
                "status": "ready",
                **size,
                "maximum_utf8_bytes": args.max_bytes,
                "comparison": "strictly_less_than",
                "body_binding": "exact_file_utf8_bytes",
                "validation_scope": "byte_limit_and_minimum_responses_structure",
            },
            None,
        )
        return 0
    if args.command == "aggregate-techniques":
        from .technique_learning import (
            aggregate_technique_studies,
            load_technique_study,
            write_technique_aggregate,
        )

        aggregate = aggregate_technique_studies(
            [load_technique_study(path) for path in args.study],
            minimum_source_support=args.minimum_source_support,
        )
        write_technique_aggregate(aggregate, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source_count": aggregate["source_count"],
                "stable_patterns": len(aggregate["stable_patterns"]),
            },
            None,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
