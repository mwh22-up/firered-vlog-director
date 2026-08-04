from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .ffmpeg import find_ffmpeg, probe_media, run_command
from .subtitle_layout_probe import inspect_ffmpeg_identity


BLACK_START = re.compile(r"black_start:([0-9.]+)")
BLACK_END = re.compile(r"black_end:([0-9.]+)\s+black_duration:([0-9.]+)")
FREEZE_START = re.compile(r"freeze_start:\s*([0-9.]+)")
FREEZE_END = re.compile(r"freeze_end:\s*([0-9.]+)\s*\|?\s*freeze_duration:\s*([0-9.]+)")
TEXT_ACCURACY_STATEMENT = "已生成视觉帧和布局证据，文字准确性仍需人工听校。"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("visual QA input must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("visual QA input must be a JSON object")
    return document


def _confined_file(project: Path, path: Path, root: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to((project / root).resolve())
    except ValueError as error:
        raise ValueError(f"visual QA binding must stay under {root}") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _output_directory(project: Path, output: Path) -> Path:
    allowed = (project / "work" / "qa" / "release-visual").resolve()
    resolved = output.resolve()
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError("release visual QA must stay under work/qa/release-visual") from error
    if resolved == allowed or len(relative.parts) != 1:
        raise ValueError("release visual QA output must be one unique child directory")
    if resolved.exists():
        raise FileExistsError(resolved)
    return resolved


def _intervals(output: str, start_pattern: re.Pattern[str], end_pattern: re.Pattern[str]) -> list[dict[str, float]]:
    starts = [float(value) for value in start_pattern.findall(output)]
    ends = [(float(end), float(duration)) for end, duration in end_pattern.findall(output)]
    return [
        {"start_sec": round(start, 6), "end_sec": round(end, 6), "duration_sec": round(duration, 6)}
        for start, (end, duration) in zip(starts, ends)
    ]


def qa_release_visual(
    *,
    project: Path,
    media_path: Path,
    enhancement_plan_path: Path,
    output_directory: Path,
    realized_timeline_path: Path | None = None,
    directed_base_contract_path: Path | None = None,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    project = project.resolve()
    marker = _load_json(project / ".vlog-project.json")
    plan_path = _confined_file(project, enhancement_plan_path, "work/enhancement")
    timeline_path = _confined_file(project, realized_timeline_path, "work/qa") if realized_timeline_path else None
    contract_path = _confined_file(project, directed_base_contract_path, "work/qa") if directed_base_contract_path else None
    media = media_path.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    output = _output_directory(project, output_directory)
    ffmpeg = find_ffmpeg(executable)
    probe = probe_media(ffmpeg, media)
    duration = float(probe["duration_sec"])
    command = [
        ffmpeg, "-hide_banner", "-i", str(media),
        "-vf", "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=-50dB:d=1.5",
        "-an", "-f", "null", os.devnull,
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("release visual QA FFmpeg analysis failed")
    diagnostic = (completed.stderr or "") + "\n" + (completed.stdout or "")
    black = _intervals(diagnostic, BLACK_START, BLACK_END)
    freeze = _intervals(diagnostic, FREEZE_START, FREEZE_END)
    issues: list[dict[str, str]] = []
    for interval in black:
        internal = interval["start_sec"] > 0.25 and interval["end_sec"] < duration - 0.25
        severity = "error" if internal and interval["duration_sec"] >= 1.0 else "warning"
        issues.append({"severity": severity, "code": "internal_black_frame" if internal else "edge_black_frame", "message": f"Detected {interval['duration_sec']:.3f}s black interval."})
    for interval in freeze:
        severity = "error" if interval["duration_sec"] >= 3.0 else "warning"
        issues.append({"severity": severity, "code": "long_freeze_frame" if severity == "error" else "freeze_frame", "message": f"Detected {interval['duration_sec']:.3f}s frozen interval."})
    output.mkdir(parents=True)
    samples = [("opening", min(0.1, duration / 4)), ("middle", duration / 2), ("closing", max(0.0, duration - 0.1))]
    frames: list[dict[str, Any]] = []
    for role, time_sec in samples:
        frame = output / f"{role}.png"
        run_command([ffmpeg, "-n", "-hide_banner", "-loglevel", "error", "-ss", f"{time_sec:.6f}", "-i", str(media), "-frames:v", "1", str(frame)])
        if not frame.is_file() or frame.stat().st_size <= 0:
            raise RuntimeError(f"release visual QA frame missing: {role}")
        frames.append({"role": role, "time_sec": round(time_sec, 6), "path": frame.relative_to(project).as_posix(), "sha256": _sha256_file(frame)})
    bindings: dict[str, Any] = {
        "media": {"name": media.name, "sha256": _sha256_file(media), "size_bytes": media.stat().st_size, "duration_sec": round(duration, 6), "width": int(probe["width"]), "height": int(probe["height"])},
        "enhancement_plan": {"path": plan_path.relative_to(project).as_posix(), "sha256": _sha256_file(plan_path)},
        "ffmpeg_identity": inspect_ffmpeg_identity(ffmpeg),
    }
    if timeline_path:
        bindings["realized_timeline"] = {"path": timeline_path.relative_to(project).as_posix(), "sha256": _sha256_file(timeline_path)}
    if contract_path:
        bindings["directed_base_contract"] = {"path": contract_path.relative_to(project).as_posix(), "sha256": _sha256_file(contract_path)}
    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    warning_count = sum(issue["severity"] == "warning" for issue in issues)
    report = {
        "schema_version": "1.0",
        "contract_version": "release-visual-qa-v1",
        "status": "blocked" if blocking_count else "warning" if warning_count else "passed",
        "project_id": str(marker.get("project_id", "")),
        "bindings": bindings,
        "policy": {"black_min_duration_sec": 0.5, "freeze_min_duration_sec": 1.5, "internal_black_blocker_sec": 1.0, "freeze_blocker_sec": 3.0},
        "observations": {"black_intervals": black, "freeze_intervals": freeze},
        "frames": frames,
        "blocking_count": blocking_count,
        "warning_count": warning_count,
        "issues": issues,
        "ocr": {"status": "not_run", "text_accuracy_verified": False},
        "human_review": {"status": "pending"},
        "text_accuracy_statement": TEXT_ACCURACY_STATEMENT,
    }
    schema = json.loads((Path(__file__).with_name("schemas") / "release-visual-qa.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(report))
    if errors:
        raise ValueError("release visual QA schema invalid: " + "; ".join(f"{error.json_path}: {error.message}" for error in errors))
    (output / "visual-qa.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return report
