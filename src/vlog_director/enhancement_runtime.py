from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .audio_qa import analyze_music_mix, write_music_mix_qa
from .enhancement import (
    normalize_enhancement_plan,
    normalize_realized_timeline,
    validate_enhancement_plan,
)
from .enhancement_assets import validate_enhancement_assets
from .release import release_readiness_issues, verify_rendered_media
from .renderers import load_json, render_enhanced_video
from .schema_validation import enhancement_schema_errors


def render_enhancement(
    *,
    project: Path,
    base_video: Path,
    plan_path: Path,
    output: Path,
    qa_output: Path | None = None,
    ffmpeg_executable: str = "ffmpeg",
    realized_timeline_path: Path | None = None,
    mode: str = "preview",
    video_preset: str = "medium",
    video_crf: int = 18,
) -> dict[str, Any]:
    """Validate, render, and verify one immutable enhancement output."""
    project = project.resolve()
    base_video = base_video.resolve()
    plan_path = plan_path.resolve()
    output = output.resolve()
    if mode not in {"preview", "release"}:
        raise ValueError("enhancement render mode must be preview or release")
    resolved_qa_output = (qa_output or output.with_suffix(".music-mix-qa.json")).resolve()
    conflicts = [path for path in (output, resolved_qa_output) if path.exists()]
    if conflicts:
        raise FileExistsError(
            "enhancement render evidence already exists: "
            + ", ".join(str(path) for path in conflicts)
        )

    enhancement_plan, migrations = normalize_enhancement_plan(load_json(plan_path))
    schema_errors = enhancement_schema_errors(enhancement_plan)
    if schema_errors:
        result: dict[str, Any] = {
            "status": "blocked",
            "mode": mode,
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
        return result

    edit_version = enhancement_plan.get("edit_plan_version")
    edit_plan_path = project / "work" / "plans" / f"edit_plan.v{edit_version}.json"
    if not edit_plan_path.is_file():
        raise FileNotFoundError(f"edit plan is missing: {edit_plan_path}")
    edit_plan = load_json(edit_plan_path)
    if realized_timeline_path is None:
        candidate = project / "work" / "qa" / f"render.v{edit_version}.json"
        realized_timeline_path = candidate if candidate.is_file() else None
    else:
        realized_timeline_path = realized_timeline_path.resolve()
        if not realized_timeline_path.is_file():
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
    validation["issues"].extend(validate_enhancement_assets(project, enhancement_plan))
    if mode == "release":
        validation["issues"].extend(release_readiness_issues(enhancement_plan))
    validation["blocking_count"] = sum(
        issue["severity"] == "error" for issue in validation["issues"]
    )
    validation["warning_count"] = sum(
        issue["severity"] == "warning" for issue in validation["issues"]
    )
    validation["status"] = "blocked" if validation["blocking_count"] else "passed"
    if validation["status"] != "passed":
        validation["mode"] = mode
        if migrations:
            validation["migrations"] = migrations
        return validation

    render_enhanced_video(
        project,
        base_video,
        enhancement_plan,
        output,
        executable=ffmpeg_executable,
        realized_timeline=realized_timeline,
        video_preset=video_preset,
        video_crf=video_crf,
    )
    verification, verification_issues = verify_rendered_media(
        output,
        enhancement_plan,
        realized_timeline=realized_timeline,
        executable=ffmpeg_executable,
    )
    if verification_issues:
        qa_report: dict[str, Any] = {
            "schema_version": "1.0",
            "status": "blocked",
            "media": str(output),
            "issues": verification_issues,
            "blocking_count": len(verification_issues),
            "warning_count": 0,
        }
    else:
        qa_report = analyze_music_mix(
            output,
            enhancement_plan,
            executable=ffmpeg_executable,
        )
    qa_report["mode"] = mode
    qa_report["render_verification"] = verification
    write_music_mix_qa(qa_report, resolved_qa_output)
    result = {
        "status": (
            "ready"
            if mode == "release" and qa_report["status"] == "passed"
            else "preview_ready"
            if mode == "preview" and qa_report["status"] == "passed"
            else "blocked"
        ),
        "mode": mode,
        "output": str(output),
        "music_mix_qa": str(resolved_qa_output),
        "qa_status": qa_report["status"],
        "render_verification": verification,
    }
    warnings = [
        issue for issue in validation["issues"] if issue["severity"] == "warning"
    ]
    if warnings:
        result["warnings"] = warnings
    if migrations:
        result["migrations"] = migrations
    if realized_timeline_path is not None:
        result["realized_timeline"] = str(realized_timeline_path)
    return result
