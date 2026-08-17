from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .enhancement import visual_treatments_active
from .enhancement_assets import subtitle_ready_evidence_contract_issues
from .ffmpeg import find_ffmpeg

INPUT_STREAM = re.compile(r"^\s*Stream #0:\d+(?:\[[^\]]+\])?(?:\([^)]*\))?:\s*(Video|Audio):", re.MULTILINE)
DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
FRAME_RATE = re.compile(r"(?:^|,\s)(\d+(?:\.\d+)?)\s+fps(?:,|\s)")


def release_readiness_issues(enhancement_plan: dict[str, Any]) -> list[dict[str, str]]:
    """Return release-only blockers for optional enhancement sections."""
    issues: list[dict[str, str]] = []
    for section_name, items_name in (
        ("music", "tracks"),
        ("subtitles", "cues"),
        ("illustration_motion", "items"),
    ):
        section = enhancement_plan.get(section_name, {})
        status = section.get("status")
        items = section.get(items_name)
        if status == "planned":
            issues.append(
                {
                    "severity": "error",
                    "code": "release_section_planned",
                    "subject_id": section_name,
                    "message": f"Release requires {section_name} to be ready or disabled.",
                }
            )
        elif status == "ready" and (not isinstance(items, list) or not items):
            issues.append(
                {
                    "severity": "error",
                    "code": "release_ready_section_empty",
                    "subject_id": section_name,
                    "message": f"Release cannot mark {section_name} ready without {items_name}.",
                }
            )
        elif status != "disabled" and status != "ready":
            issues.append(
                {
                    "severity": "error",
                    "code": "release_section_not_ready",
                    "subject_id": section_name,
                    "message": f"Release requires an explicit ready or disabled {section_name} section.",
                }
            )
    subtitles = enhancement_plan.get("subtitles", {})
    if isinstance(subtitles, dict) and subtitles.get("status") == "ready":
        evidence = subtitles.get("evidence")
        if evidence is None:
            issues.append(
                {
                    "severity": "error",
                    "code": "release_subtitle_evidence_legacy",
                    "subject_id": "subtitles.evidence",
                    "message": "Release blocks legacy ready subtitles without the current evidence contract.",
                }
            )
        else:
            contract_issues = subtitle_ready_evidence_contract_issues(evidence)
            if contract_issues:
                issues.append(
                    {
                        "severity": "error",
                        "code": "release_subtitle_evidence_invalid",
                        "subject_id": "subtitles.evidence",
                        "message": "Release subtitle evidence contract is incomplete or invalid: "
                        + "; ".join(contract_issues),
                    }
                )
    if visual_treatments_active(enhancement_plan) and not isinstance(
        enhancement_plan.get("visual_treatment_evidence"),
        dict,
    ):
        issues.append(
            {
                "severity": "error",
                "code": "release_visual_treatment_evidence_required",
                "subject_id": "visual_treatment_evidence",
                "message": "Release pixel treatments require SHA-bound preview, visual QA, human review, and approval evidence.",
            }
        )
    illustration = enhancement_plan.get("illustration_motion", {})
    if isinstance(illustration, dict) and illustration.get("status") == "ready":
        items = illustration.get("items", [])
        if any(
            isinstance(item, dict) and item.get("type") != "hyperframes"
            for item in items
        ):
            issues.append(
                {
                    "severity": "error",
                    "code": "release_static_overlay_preview_only",
                    "subject_id": "illustration_motion.items",
                    "message": "Legacy static overlays are preview-only; release narrative overlays must use the SHA-approved effect pipeline.",
                }
            )
        if any(
            isinstance(item, dict) and item.get("type") == "hyperframes"
            for item in items
        ) and not isinstance(illustration.get("effect_evidence"), dict):
            issues.append(
                {
                    "severity": "error",
                    "code": "release_effect_evidence_required",
                    "subject_id": "illustration_motion.effect_evidence",
                    "message": "HyperFrames release overlays require the complete effect approval evidence contract.",
                }
            )
    return issues


def _duration_seconds(value: re.Match[str]) -> float:
    hours, minutes, seconds = value.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _expected_duration(
    enhancement_plan: dict[str, Any],
    realized_timeline: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    if realized_timeline is not None:
        duration = realized_timeline.get("duration_sec")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            return float(duration), "realized_timeline"
    duration = enhancement_plan.get("timeline_duration_sec")
    if isinstance(duration, (int, float)) and not isinstance(duration, bool):
        return float(duration), "enhancement_plan"
    return None, None


def verify_rendered_media(
    media: Path,
    enhancement_plan: dict[str, Any],
    *,
    realized_timeline: dict[str, Any] | None,
    executable: str = "ffmpeg",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Probe a render and fully decode its required streams with one FFmpeg binary."""
    resolved_media = media.resolve()
    ffmpeg = find_ffmpeg(executable)
    evidence: dict[str, Any] = {
        "media": str(resolved_media),
        "ffmpeg_executable": ffmpeg,
        "probe": {"status": "not_run"},
        "full_decode": {"status": "not_run", "command": ["-xerror", "-map", "0:v:0", "-map", "0:a:0"]},
    }
    issues: list[dict[str, Any]] = []
    if not resolved_media.is_file():
        issues.append(
            {
                "severity": "error",
                "code": "render_output_missing",
                "subject_id": str(resolved_media),
                "message": "Rendered output is missing before release verification.",
            }
        )
        evidence["probe"] = {"status": "blocked", "reason": "output_missing"}
        return evidence, issues

    probe = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(resolved_media),
            "-map",
            "0:v?",
            "-map",
            "0:a?",
            "-c",
            "copy",
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
    output = probe.stderr + "\n" + probe.stdout
    if probe.returncode != 0:
        issues.append(
            {
                "severity": "error",
                "code": "render_media_probe_failed",
                "subject_id": str(resolved_media),
                "message": "FFmpeg could not inspect the rendered output.",
            }
        )
        evidence["probe"] = {"status": "failed", "exit_code": probe.returncode}
        return evidence, issues

    input_header = output.split("Output #0", 1)[0]
    streams = INPUT_STREAM.findall(input_header)
    video_stream_count = streams.count("Video")
    audio_stream_count = streams.count("Audio")
    duration_match = DURATION.search(input_header)
    duration_sec = _duration_seconds(duration_match) if duration_match else None
    frame_rate_match = FRAME_RATE.search(input_header)
    frame_rate = float(frame_rate_match.group(1)) if frame_rate_match else None
    tolerance_sec = max(0.1, 2.0 / frame_rate) if frame_rate else 0.1
    expected_duration_sec, expected_duration_source = _expected_duration(
        enhancement_plan,
        realized_timeline,
    )
    evidence["probe"] = {
        "status": "passed",
        "video_stream_count": video_stream_count,
        "audio_stream_count": audio_stream_count,
        "duration_sec": duration_sec,
        "frame_rate": frame_rate,
        "duration_tolerance_sec": tolerance_sec,
        "expected_duration_sec": expected_duration_sec,
        "expected_duration_source": expected_duration_source,
    }
    if video_stream_count != 1 or audio_stream_count != 1:
        issues.append(
            {
                "severity": "error",
                "code": "render_stream_layout_invalid",
                "subject_id": str(resolved_media),
                "message": "Rendered output must contain exactly one video and one audio stream.",
            }
        )
    if duration_sec is None or expected_duration_sec is None:
        issues.append(
            {
                "severity": "error",
                "code": "render_duration_unavailable",
                "subject_id": str(resolved_media),
                "message": "Rendered output and expected timeline duration must be available.",
            }
        )
    elif abs(duration_sec - expected_duration_sec) > tolerance_sec:
        issues.append(
            {
                "severity": "error",
                "code": "render_duration_out_of_tolerance",
                "subject_id": str(resolved_media),
                "message": "Rendered output duration differs from the expected timeline beyond two frames.",
            }
        )
    if issues:
        evidence["full_decode"] = {"status": "blocked", "reason": "probe_requirements_failed"}
        return evidence, issues

    decode = subprocess.run(
        [ffmpeg, "-hide_banner", "-xerror", "-v", "error", "-i", str(resolved_media), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", os.devnull],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    evidence["full_decode"] = {
        "status": "passed" if decode.returncode == 0 else "failed",
        "exit_code": decode.returncode,
        "command": ["-xerror", "-map", "0:v:0", "-map", "0:a:0"],
    }
    if decode.returncode != 0:
        issues.append(
            {
                "severity": "error",
                "code": "render_full_decode_failed",
                "subject_id": str(resolved_media),
                "message": "FFmpeg -xerror could not fully decode the mapped video and audio streams.",
            }
        )
    return evidence, issues
