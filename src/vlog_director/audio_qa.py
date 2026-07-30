from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ffmpeg import find_ffmpeg

INTEGRATED_LOUDNESS = re.compile(r"^\s*I:\s*(-?inf|-?\d+(?:\.\d+)?)\s+LUFS", re.MULTILINE)
TRUE_PEAK = re.compile(r"^\s*Peak:\s*(-?inf|-?\d+(?:\.\d+)?)\s+dBFS", re.MULTILINE)
SILENCE_START = re.compile(r"silence_start:\s*(\d+(?:\.\d+)?)")
SILENCE_END = re.compile(
    r"silence_end:\s*(\d+(?:\.\d+)?)\s*\|\s*silence_duration:\s*(\d+(?:\.\d+)?)"
)
MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s+dB")
MAX_VOLUME = re.compile(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s+dB")


def _number(value: str) -> float | None:
    return None if value.lower() in {"inf", "-inf"} else float(value)


def parse_ebur128(output: str) -> dict[str, float | None]:
    loudness = INTEGRATED_LOUDNESS.findall(output)
    peak = TRUE_PEAK.findall(output)
    return {
        "integrated_lufs": _number(loudness[-1]) if loudness else None,
        "true_peak_dbfs": _number(peak[-1]) if peak else None,
    }


def parse_silences(output: str) -> list[dict[str, float]]:
    starts = [float(value) for value in SILENCE_START.findall(output)]
    ends = [(float(end), float(duration)) for end, duration in SILENCE_END.findall(output)]
    intervals: list[dict[str, float]] = []
    for index, (end, duration) in enumerate(ends):
        start = starts[index] if index < len(starts) else max(0.0, end - duration)
        intervals.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "duration_sec": round(duration, 3),
            }
        )
    return intervals


def parse_volume(output: str) -> dict[str, float | None]:
    mean = MEAN_VOLUME.findall(output)
    maximum = MAX_VOLUME.findall(output)
    return {
        "mean_db": _number(mean[-1]) if mean else None,
        "max_db": _number(maximum[-1]) if maximum else None,
    }


def _run_ffmpeg(executable: str, arguments: list[str]) -> str:
    completed = subprocess.run(
        [find_ffmpeg(executable), "-hide_banner", "-nostats", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = completed.stderr + "\n" + completed.stdout
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"FFmpeg exited with {completed.returncode}")
    return output


def _boundary_volume(
    media: Path,
    boundary_sec: float,
    executable: str,
    window_sec: float = 0.18,
) -> dict[str, Any]:
    result: dict[str, Any] = {"boundary_sec": round(boundary_sec, 3)}
    for side, start in (
        ("before", max(0.0, boundary_sec - window_sec)),
        ("after", max(0.0, boundary_sec)),
    ):
        output = _run_ffmpeg(
            executable,
            [
                "-ss",
                f"{start:.3f}",
                "-i",
                str(media),
                "-t",
                f"{window_sec:.3f}",
                "-map",
                "0:a:0",
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
        )
        result[side] = parse_volume(output)
    before = result["before"]["mean_db"]
    after = result["after"]["mean_db"]
    result["mean_jump_db"] = (
        round(abs(after - before), 3) if before is not None and after is not None else None
    )
    return result


def analyze_music_mix(
    media: Path,
    enhancement_plan: dict[str, Any],
    *,
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    if not media.is_file():
        raise FileNotFoundError(media)
    issues: list[dict[str, Any]] = []

    loudness_output = _run_ffmpeg(
        executable,
        [
            "-i",
            str(media),
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
    )
    levels = parse_ebur128(loudness_output)
    integrated = levels["integrated_lufs"]
    true_peak = levels["true_peak_dbfs"]
    if integrated is None:
        issues.append({"severity": "error", "code": "loudness_unavailable"})
    elif not -18.0 <= integrated <= -14.0:
        issues.append(
            {
                "severity": "error",
                "code": "integrated_loudness_out_of_range",
                "actual_lufs": integrated,
                "required_lufs": [-18.0, -14.0],
            }
        )
    if true_peak is None:
        issues.append({"severity": "error", "code": "true_peak_unavailable"})
    elif true_peak > -1.0:
        issues.append(
            {
                "severity": "error",
                "code": "true_peak_too_high",
                "actual_dbfs": true_peak,
                "maximum_dbfs": -1.0,
            }
        )

    silence_output = _run_ffmpeg(
        executable,
        [
            "-i",
            str(media),
            "-map",
            "0:a:0",
            "-af",
            "silencedetect=n=-50dB:d=2.0",
            "-f",
            "null",
            "-",
        ],
    )
    silences = parse_silences(silence_output)
    for interval in silences:
        issues.append(
            {
                "severity": "warning",
                "code": "extended_silence_review",
                **interval,
                "message": "Review whether this silence is intentional or a missing audio segment.",
            }
        )

    music = enhancement_plan.get("music", {})
    boundary_checks: list[dict[str, Any]] = []
    seen: set[float] = set()
    for track in music.get("tracks", []):
        for boundary in (float(track["start_sec"]), float(track["end_sec"])):
            if boundary <= 0 or boundary in seen:
                continue
            seen.add(boundary)
            check = _boundary_volume(media, boundary, executable)
            boundary_checks.append(check)
            if check["mean_jump_db"] is not None and check["mean_jump_db"] > 12.0:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "possible_music_boundary_jump",
                        "boundary_sec": check["boundary_sec"],
                        "mean_jump_db": check["mean_jump_db"],
                        "message": "Audition this music entry or exit for a possible level jump.",
                    }
                )

    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": "1.0",
        "status": "blocked" if blocking_count else "passed",
        "media": str(media.resolve()),
        "levels": levels,
        "target": {"integrated_lufs": -16.0, "true_peak_max_dbfs": -1.0},
        "silence_intervals": silences,
        "music_boundary_checks": boundary_checks,
        "blocking_count": blocking_count,
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "issues": issues,
        "created_at": datetime.now(UTC).isoformat(),
    }


def write_music_mix_qa(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
