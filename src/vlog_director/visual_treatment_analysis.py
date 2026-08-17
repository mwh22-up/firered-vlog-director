from __future__ import annotations

import hashlib
import io
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .enhancement import normalize_realized_timeline
from .ffmpeg import find_ffmpeg, probe_media
from .visual_treatments import validate_visual_treatment_analysis


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
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _confined(path: Path, root: Path, label: str, *, allow_root: bool = False) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {allowed}") from error
    if not allow_root and (resolved == allowed or not relative.parts):
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
    first_line = (completed.stdout or completed.stderr).splitlines()[0].strip()
    if not first_line:
        raise RuntimeError("FFmpeg identity is empty")
    return resolved, first_line


def _extract_rgb_frame(executable: str, media: Path, time_sec: float) -> Any:
    try:
        import numpy as np
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "visual analysis requires the analysis/test extras (numpy and Pillow)"
        ) from error
    completed = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{time_sec:.6f}",
            "-i",
            str(media),
            "-frames:v",
            "1",
            "-vf",
            "scale='min(480,iw)':-2",
            "-c:v",
            "png",
            "-f",
            "image2pipe",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"unable to extract analysis frame at {time_sec:.3f}s: {detail}")
    image = Image.open(io.BytesIO(completed.stdout)).convert("RGB")
    return np.asarray(image, dtype=np.float32) / 255.0


def _frame_metrics(frames: list[Any]) -> dict[str, Any]:
    import numpy as np

    combined = np.concatenate([frame.reshape(-1, 3) for frame in frames], axis=0)
    luma_frames = [
        frame[..., 0] * 0.2126 + frame[..., 1] * 0.7152 + frame[..., 2] * 0.0722
        for frame in frames
    ]
    luma = np.concatenate([frame.reshape(-1) for frame in luma_frames])
    saturation = combined.max(axis=1) - combined.min(axis=1)
    gradients: list[float] = []
    residuals: list[float] = []
    for frame in luma_frames:
        horizontal = np.abs(np.diff(frame, axis=1)).mean()
        vertical = np.abs(np.diff(frame, axis=0)).mean()
        gradients.append(float(horizontal + vertical))
        center = frame[1:-1, 1:-1]
        smooth = (
            frame[:-2, 1:-1]
            + frame[2:, 1:-1]
            + frame[1:-1, :-2]
            + frame[1:-1, 2:]
        ) / 4.0
        residuals.append(float(np.abs(center - smooth).mean()))
    motion = 0.0
    if len(luma_frames) > 1:
        motion = float(
            np.mean(
                [
                    np.abs(current - previous).mean()
                    for previous, current in zip(luma_frames, luma_frames[1:])
                ]
            )
        )
    return {
        "luma_mean": round(float(luma.mean()), 6),
        "luma_p05": round(float(np.percentile(luma, 5)), 6),
        "luma_p50": round(float(np.percentile(luma, 50)), 6),
        "luma_p95": round(float(np.percentile(luma, 95)), 6),
        "clipped_black_ratio": round(float((luma <= 0.015).mean()), 6),
        "clipped_white_ratio": round(float((luma >= 0.985).mean()), 6),
        "contrast_std": round(float(luma.std()), 6),
        "saturation_mean": round(float(saturation.mean()), 6),
        "rgb_means": {
            "red": round(float(combined[:, 0].mean()), 6),
            "green": round(float(combined[:, 1].mean()), 6),
            "blue": round(float(combined[:, 2].mean()), 6),
        },
        "sharpness": round(float(np.mean(gradients)), 6),
        "motion": round(motion, 6),
        "temporal_noise": round(float(np.mean(residuals)), 6),
    }


def _region_coverage(
    regions: list[Mapping[str, Any]],
    start_sec: float,
    end_sec: float,
) -> bool:
    return any(
        float(row.get("start_sec", -1)) < end_sec
        and float(row.get("end_sec", -1)) > start_sec
        for row in regions
    )


def analyze_visual_segments(
    project: Path,
    base_video: Path,
    edit_plan_path: Path,
    realized_timeline_path: Path,
    output_path: Path,
    *,
    executable: str = "ffmpeg",
    protected_regions_path: Path | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    base_video = _base_media(project, base_video)
    edit_plan_path = _confined(edit_plan_path, project / "work" / "plans", "edit plan")
    realized_timeline_path = _confined(
        realized_timeline_path,
        project / "work" / "qa",
        "realized timeline",
    )
    output_path = _confined(
        output_path,
        project / "work" / "analysis" / "visual",
        "visual analysis output",
    )
    if output_path.exists():
        raise FileExistsError(output_path)
    edit_plan = _load_json(edit_plan_path, "edit plan")
    realized_document = _load_json(realized_timeline_path, "realized timeline")
    realized = normalize_realized_timeline(
        edit_plan,
        realized_document,
        edit_plan_sha256=_sha256_file(edit_plan_path),
    )
    rows = realized.get("segments")
    if not isinstance(rows, list) or not rows:
        raise ValueError("realized timeline requires non-empty segments")
    ffmpeg, identity = _ffmpeg_identity(executable)
    media_probe = probe_media(ffmpeg, base_video)
    base_sha = _sha256_file(base_video)
    if realized.get("base_sha256") not in {None, base_sha}:
        raise ValueError("realized timeline base SHA-256 changed")
    if realized.get("base_size_bytes") not in {None, base_video.stat().st_size}:
        raise ValueError("realized timeline base size changed")

    regions: list[Mapping[str, Any]] = []
    regions_binding: dict[str, str] | None = None
    if protected_regions_path is not None:
        protected_regions_path = _confined(
            protected_regions_path,
            project / "work" / "qa",
            "protected regions",
        )
        region_document = _load_json(protected_regions_path, "protected regions")
        schema_path = Path(__file__).with_name("schemas") / "visual-protected-regions.schema.json"
        region_schema = _load_json(schema_path, "visual protected regions schema")
        if list(Draft202012Validator(region_schema).iter_errors(region_document)):
            raise ValueError("visual protected regions schema invalid")
        if region_document.get("base_media_sha256") != base_sha:
            raise ValueError("protected regions base media SHA-256 changed")
        if region_document.get("provider", {}).get("input_media_sha256") != base_sha:
            raise ValueError("protected region provider input SHA-256 changed")
        if region_document.get("canvas") != {
            "width": int(media_probe["width"]),
            "height": int(media_probe["height"]),
        }:
            raise ValueError("protected regions canvas differs from base media")
        raw_regions = region_document.get("regions")
        if not isinstance(raw_regions, list):
            raise ValueError("protected regions require a regions array")
        regions = [row for row in raw_regions if isinstance(row, Mapping)]
        regions_binding = {
            "path": protected_regions_path.relative_to(project).as_posix(),
            "sha256": _sha256_file(protected_regions_path),
        }

    segment_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("realized timeline segment must be an object")
        segment_id = str(row.get("segment_id", ""))
        start = float(row["start_sec"])
        end = float(row["end_sec"])
        if not segment_id or end <= start:
            raise ValueError("realized timeline segment is invalid")
        duration = end - start
        samples = [
            round(start + duration * ratio, 6)
            for ratio in (0.2, 0.5, 0.8)
        ]
        frames = [_extract_rgb_frame(ffmpeg, base_video, value) for value in samples]
        has_regions = _region_coverage(regions, start, end)
        warnings = [] if has_regions else ["protected_regions_unavailable"]
        segment_rows.append(
            {
                "segment_id": segment_id,
                "start_sec": round(start, 6),
                "end_sec": round(end, 6),
                "sample_times_sec": samples,
                "metrics": _frame_metrics(frames),
                "protected_regions_available": has_regions,
                "warning_codes": warnings,
            }
        )
    analysis: dict[str, Any] = {
        "schema_version": "1.0",
        "analysis_version": "visual-segment-analysis-v1",
        "project_id": str(edit_plan["project_id"]),
        "edit_plan_version": int(edit_plan["version"]),
        "edit_plan_sha256": _canonical_sha256(edit_plan),
        "realized_timeline_sha256": _sha256_file(realized_timeline_path),
        "base_media": {
            "path": base_video.relative_to(project).as_posix(),
            "sha256": base_sha,
            "size_bytes": base_video.stat().st_size,
        },
        "ffmpeg_identity": identity,
        "segments": segment_rows,
    }
    if regions_binding is not None:
        analysis["protected_regions"] = regions_binding
    validation = validate_visual_treatment_analysis(edit_plan, analysis)
    if validation["status"] != "passed":
        raise ValueError(json.dumps(validation["issues"], ensure_ascii=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return analysis


__all__ = ["analyze_visual_segments"]
