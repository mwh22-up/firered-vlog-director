from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .effect_collision import audit_effect_collisions
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


def _sample_alpha_bbox(
    executable: str,
    media: Path,
    time_sec: float,
    width: int,
    height: int,
) -> dict[str, int] | None:
    completed = subprocess.run(
        [
            executable, "-hide_banner", "-loglevel", "error",
            "-ss", f"{time_sec:.6f}", "-i", str(media),
            "-frames:v", "1", "-vf", "alphaextract",
            "-pix_fmt", "gray", "-f", "rawvideo", "-",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise FFmpegError("Unable to sample HyperFrames alpha channel")
    pixels = completed.stdout
    expected = width * height
    if len(pixels) < expected:
        raise FFmpegError("HyperFrames alpha sample is incomplete")
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for index, value in enumerate(pixels[:expected]):
        if value <= 8:
            continue
        y, x = divmod(index, width)
        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x)
        max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        return None
    return {"x": min_x, "y": min_y, "width": max_x - min_x + 1, "height": max_y - min_y + 1}


def _load_collision_regions(
    project: Path,
    *,
    base_media_sha256: str,
    width: int,
    height: int,
    layout_qa_path: Path | None,
    protected_regions_path: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    regions: list[dict[str, Any]] = []
    bindings: list[dict[str, str]] = []
    if layout_qa_path is not None:
        layout_path = _confined_file(project, _project_relative(project, layout_qa_path), project / "work" / "qa", "subtitle layout QA")
        layout = _load_json(layout_path, "subtitle layout QA")
        if layout.get("probe_mode") != "real_libass":
            raise ValueError("effect collision QA requires real libass subtitle layout")
        if layout.get("canvas") != {"width": width, "height": height}:
            raise ValueError("subtitle layout canvas differs from effect media")
        source_relative = layout.get("bindings", {}).get("subtitle_source_path")
        source_path = _confined_file(project, source_relative, project / "work" / "subtitles", "subtitle source")
        if _sha256_file(source_path) != layout.get("bindings", {}).get("subtitle_source_sha256"):
            raise ValueError("subtitle layout source SHA-256 changed")
        source = _load_json(source_path, "subtitle source")
        timing = {
            str(cue.get("cue_id")): (float(cue["start_sec"]), float(cue["end_sec"]))
            for cue in source.get("cues", [])
            if isinstance(cue, dict) and cue.get("cue_id")
        }
        for cue in layout.get("cues", []):
            cue_id = str(cue.get("cue_id"))
            bbox = cue.get("measured_bbox")
            if cue.get("real_layout_verified") is not True or not isinstance(bbox, dict) or cue_id not in timing:
                continue
            start, end = timing[cue_id]
            regions.append({"region_id": cue_id, "region_type": "subtitle", "start_sec": start, "end_sec": end, "bbox": bbox})
        bindings.append({"path": _project_relative(project, layout_path), "sha256": _sha256_file(layout_path)})
    if protected_regions_path is not None:
        protected_path = _confined_file(project, _project_relative(project, protected_regions_path), project / "work" / "qa", "protected regions")
        document = _load_json(protected_path, "protected regions")
        schema = _load_json(Path(__file__).with_name("schemas") / "effect-protected-regions.schema.json", "protected regions schema")
        if list(Draft202012Validator(schema).iter_errors(document)):
            raise ValueError("protected regions schema invalid")
        if document.get("base_media_sha256") != base_media_sha256 or document.get("provider", {}).get("input_media_sha256") != base_media_sha256:
            raise ValueError("protected regions base media SHA-256 changed")
        regions.extend(dict(region) for region in document.get("regions", []))
        bindings.append({"path": _project_relative(project, protected_path), "sha256": _sha256_file(protected_path)})
    for region in regions:
        bbox = region["bbox"]
        if int(bbox["x"]) + int(bbox["width"]) > width or int(bbox["y"]) + int(bbox["height"]) > height:
            raise ValueError("protected region escaped the effect canvas")
    return regions, bindings


def qa_hyperframes_effects(
    project: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
    base_media: Path,
    output_directory: Path,
    *,
    executable: str = "ffmpeg",
    layout_qa_path: Path | None = None,
    protected_regions_path: Path | None = None,
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
    base_media_sha256 = _sha256_file(base_media)
    protected_regions, protected_bindings = _load_collision_regions(
        project,
        base_media_sha256=base_media_sha256,
        width=int(base_info["width"]),
        height=int(base_info["height"]),
        layout_qa_path=layout_qa_path,
        protected_regions_path=protected_regions_path,
    )
    output.mkdir(parents=True, exist_ok=False)
    plan_by_id = {str(row["effect_id"]): row for row in effect_plan["effects"]}
    qa_rows: list[dict[str, Any]] = []
    all_collisions: list[dict[str, Any]] = []
    collision_sample_count = 0
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
        frames: list[dict[str, Any]] = []
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
            frame_evidence: dict[str, Any] = {
                "role": role,
                "path": _project_relative(project, frame),
                "sha256": _sha256_file(frame),
            }
            if protected_bindings:
                collision_sample_count += 1
                alpha_bbox = _sample_alpha_bbox(
                    ffmpeg,
                    effect_file,
                    time_sec,
                    int(effect_info["width"]),
                    int(effect_info["height"]),
                )
                collisions = audit_effect_collisions(
                    effect_id=effect_id,
                    sample_time_sec=start + time_sec,
                    effect_bbox=alpha_bbox,
                    protected_regions=protected_regions,
                )
                frame_evidence["alpha_bbox"] = alpha_bbox
                frame_evidence["collisions"] = collisions
                all_collisions.extend(collisions)
            frames.append(frame_evidence)
        effect_collisions = [row for row in all_collisions if row["effect_id"] == effect_id]
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
                    "protected_regions": (
                        "blocked"
                        if any(row["severity"] == "error" for row in effect_collisions)
                        else "passed"
                        if protected_bindings
                        else "not_provided"
                    ),
                },
            }
        )

    collision_blockers = sum(row["severity"] == "error" for row in all_collisions)
    collision_warnings = sum(row["severity"] == "warning" for row in all_collisions)
    report = {
        "schema_version": "1.0",
        "contract_version": "effect-visual-qa-v1",
        "status": "blocked" if collision_blockers else "evidence_ready",
        "project_id": effect_plan["project_id"],
        "edit_plan_version": effect_plan["edit_plan_version"],
        "edit_plan_sha256": edit_sha256,
        "effect_plan_sha256": effect_plan_sha256,
        "effect_payload_sha256": payload_sha256,
        "render_manifest_sha256": _sha256_file(render_manifest_path),
        "base_media": {
            "path": _project_relative(project, base_media),
            "size_bytes": base_media.stat().st_size,
            "sha256": base_media_sha256,
        },
        "effects": qa_rows,
        "human_review": {"status": "pending"},
        "conclusion": "已生成视觉帧和布局证据，效果适配性仍需人工检查。",
    }
    if protected_bindings:
        report["protected_region_bindings"] = protected_bindings
        report["collision_summary"] = {
            "sample_count": collision_sample_count,
            "finding_count": len(all_collisions),
            "blocking_count": collision_blockers,
            "warning_count": collision_warnings,
        }
    _write_report(output / "visual-qa.json", report)
    return report
