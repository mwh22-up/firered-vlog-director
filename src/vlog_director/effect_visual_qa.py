from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .effect_plan import canonical_effect_payload_sha256, validate_effect_plan
from .ffmpeg import FFmpegError, find_ffmpeg, probe_media, run_command


MEDIA_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
VIDEO_STREAM = re.compile(r"^\s*Stream #.*Video:.*$", re.MULTILINE)
VIDEO_SIZE = re.compile(r"(?<![0-9])([1-9][0-9]{1,4})x([1-9][0-9]{1,4})(?![0-9])")
ALPHA_PIXEL_FORMAT = re.compile(r"\b(?:yuva|gbrap|rgba|argb|bgra|abgr)[a-z0-9_]*\b", re.IGNORECASE)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
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
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _project_relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def _strict_output_directory(project: Path, output_directory: Path) -> Path:
    allowed = (project / "work" / "qa" / "effects").resolve()
    output = output_directory.resolve()
    try:
        relative = output.relative_to(allowed)
    except ValueError as error:
        raise ValueError("effect visual QA must stay under project/work/qa/effects") from error
    if output == allowed or len(relative.parts) != 1:
        raise ValueError("effect visual QA output must be one unique child directory")
    if output.exists():
        raise FileExistsError(output)
    return output


def _confined_file(project: Path, relative: Any, allowed: Path, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"{label} path is invalid")
    path = (project / relative).resolve()
    try:
        path.relative_to(allowed.resolve())
    except ValueError as error:
        raise ValueError(f"{label} escaped its allowed root") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _probe_effect_video(executable: str, media: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            find_ffmpeg(executable),
            "-hide_banner",
            "-i",
            str(media),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-vf",
            "showinfo",
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
    output = (completed.stderr or "") + "\n" + (completed.stdout or "")
    if completed.returncode != 0:
        raise FFmpegError(output.strip() or "Unable to decode HyperFrames effect")
    duration_match = MEDIA_DURATION.search(output)
    stream_match = VIDEO_STREAM.search(output)
    size_match = VIDEO_SIZE.search(stream_match.group(0)) if stream_match else None
    if duration_match is None or size_match is None:
        raise FFmpegError("Unable to determine HyperFrames effect duration or geometry")
    hours, minutes, seconds = duration_match.groups()
    return {
        "duration_sec": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        "width": int(size_match.group(1)),
        "height": int(size_match.group(2)),
        "has_alpha": bool(ALPHA_PIXEL_FORMAT.search(stream_match.group(0))),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def qa_hyperframes_effects(
    project: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
    base_media: Path,
    output_directory: Path,
    *,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    project = project.resolve()
    output = _strict_output_directory(project, output_directory)
    effect_plan_path = _confined_file(
        project,
        _project_relative(project, effect_plan_path),
        project / "work" / "effects",
        "effect plan",
    )
    render_manifest_path = _confined_file(
        project,
        _project_relative(project, render_manifest_path),
        project / "work" / "effects",
        "render manifest",
    )
    base_media = base_media.resolve()
    if not base_media.is_file():
        raise FileNotFoundError(base_media)
    if not any(
        base_media.is_relative_to(root.resolve())
        for root in (project / "output", project / "work" / "proxy")
    ):
        raise ValueError("effect QA base media must stay under project/output or work/proxy")

    effect_plan = _load_json(effect_plan_path, "effect plan")
    edit_path = project / "work" / "plans" / f"edit_plan.v{effect_plan.get('edit_plan_version')}.json"
    edit_plan = _load_json(edit_path, "edit plan")
    edit_sha256 = _canonical_sha256(edit_plan)
    validation = validate_effect_plan(
        edit_plan,
        effect_plan,
        edit_plan_sha256=edit_sha256,
    )
    if validation["status"] != "passed":
        raise ValueError("effect plan validation failed")
    effect_plan_sha256 = _sha256_file(effect_plan_path)
    payload_sha256 = canonical_effect_payload_sha256(effect_plan)
    render = _load_json(render_manifest_path, "render manifest")
    expected_ids = [str(row["effect_id"]) for row in effect_plan["effects"]]
    if (
        render.get("contract_version") != "hyperframes-render-manifest-v1"
        or render.get("status") != "rendered"
        or render.get("project_id") != effect_plan["project_id"]
        or render.get("edit_plan_sha256") != edit_sha256
        or render.get("effect_plan_sha256") != effect_plan_sha256
        or render.get("effect_payload_sha256") != payload_sha256
    ):
        raise ValueError("render manifest does not bind the current effect and edit plans")
    render_rows = render.get("effects")
    if not isinstance(render_rows, list) or [str(row.get("effect_id")) for row in render_rows] != expected_ids:
        raise ValueError("render manifest effect set changed")
    for row in render_rows:
        effect_file = _confined_file(
            project,
            row.get("output"),
            project / "work" / "effects",
            f"{row.get('effect_id')} output",
        )
        if _sha256_file(effect_file) != row.get("output_sha256"):
            raise ValueError(f"{row.get('effect_id')} output SHA-256 changed")

    ffmpeg = find_ffmpeg(executable)
    base_info = probe_media(ffmpeg, base_media)
    if not base_info.get("has_video") or not base_info.get("has_audio"):
        raise ValueError("effect QA base media requires video and audio")
    if float(base_info["duration_sec"]) + 0.05 < float(effect_plan["timeline_duration_sec"]):
        raise ValueError("effect QA base media is shorter than the approved edit timeline")
    output.mkdir(parents=True, exist_ok=False)
    plan_by_id = {str(row["effect_id"]): row for row in effect_plan["effects"]}
    qa_rows: list[dict[str, Any]] = []
    for rendered in render_rows:
        effect_id = str(rendered["effect_id"])
        cue = plan_by_id[effect_id]
        effect_file = (project / rendered["output"]).resolve()
        effect_info = _probe_effect_video(ffmpeg, effect_file)
        if effect_info.get("has_alpha") is not True:
            raise ValueError(f"{effect_id} must contain a real alpha pixel format")
        expected_duration = float(cue["placement"]["end_sec"]) - float(cue["placement"]["start_sec"])
        if abs(float(effect_info["duration_sec"]) - expected_duration) > 0.12:
            raise ValueError(f"{effect_id} duration differs from its plan")
        if (
            int(effect_info["width"]) != int(base_info["width"])
            or int(effect_info["height"]) != int(base_info["height"])
        ):
            raise ValueError(f"{effect_id} geometry differs from base media")
        preview = output / f"{effect_id}.preview.mp4"
        start = float(cue["placement"]["start_sec"])
        end = float(cue["placement"]["end_sec"])
        filter_graph = (
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[basev];"
            "[1:v]format=rgba,setpts=PTS-STARTPTS[fx];"
            "[basev][fx]overlay=x=0:y=0:eof_action=pass:repeatlast=0:shortest=0[video];"
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[audio]"
        )
        run_command(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(base_media),
                "-i",
                str(effect_file),
                "-filter_complex",
                filter_graph,
                "-map",
                "[video]",
                "-map",
                "[audio]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-t",
                f"{expected_duration:.6f}",
                str(preview),
            ]
        )
        if not preview.is_file() or preview.stat().st_size <= 0:
            raise RuntimeError(f"effect preview was not created: {effect_id}")
        preview_info = probe_media(ffmpeg, preview)
        if not preview_info.get("has_video") or not preview_info.get("has_audio"):
            raise ValueError(f"effect preview decode failed: {effect_id}")
        times = {
            "entry": min(0.08, expected_duration * 0.1),
            "peak": expected_duration * 0.5,
            "exit": max(
                0.0,
                min(expected_duration * 0.85, expected_duration - 0.08),
            ),
        }
        frames: list[dict[str, str]] = []
        for role, time_sec in times.items():
            frame = output / f"{effect_id}.{role}.png"
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
                    str(frame),
                ]
            )
            if not frame.is_file() or frame.stat().st_size <= 0:
                raise RuntimeError(f"effect QA frame was not created: {effect_id}/{role}")
            frames.append(
                {
                    "role": role,
                    "path": _project_relative(project, frame),
                    "sha256": _sha256_file(frame),
                }
            )
        qa_rows.append(
            {
                "effect_id": effect_id,
                "output_sha256": rendered["output_sha256"],
                "preview": {
                    "path": _project_relative(project, preview),
                    "sha256": _sha256_file(preview),
                },
                "frames": frames,
                "machine_checks": {
                    "decode": "passed",
                    "duration": "passed",
                    "geometry": "passed",
                    "alpha": "passed",
                },
            }
        )

    report = {
        "schema_version": "1.0",
        "contract_version": "effect-visual-qa-v1",
        "status": "evidence_ready",
        "project_id": effect_plan["project_id"],
        "edit_plan_version": effect_plan["edit_plan_version"],
        "edit_plan_sha256": edit_sha256,
        "effect_plan_sha256": effect_plan_sha256,
        "effect_payload_sha256": payload_sha256,
        "render_manifest_sha256": _sha256_file(render_manifest_path),
        "base_media": {
            "path": _project_relative(project, base_media),
            "size_bytes": base_media.stat().st_size,
            "sha256": _sha256_file(base_media),
        },
        "effects": qa_rows,
        "human_review": {"status": "pending"},
        "conclusion": "已生成视觉帧和布局证据，效果适配性仍需人工检查。",
    }
    _write_report(output / "visual-qa.json", report)
    return report
