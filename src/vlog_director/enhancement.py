from __future__ import annotations

from typing import Any

from .timeline import flatten_edit_plan, timeline_duration

RENDER_STAGES = [
    "stabilize_and_reframe",
    "assemble_continuity",
    "normalize_dialogue",
    "mix_music_with_ducking",
    "compose_illustration_motion",
    "burn_subtitles",
    "final_encode",
]


def build_enhancement_plan(edit_plan: dict[str, Any]) -> dict[str, Any]:
    timeline = flatten_edit_plan(edit_plan)
    treatments = []
    for segment in timeline:
        treatments.append(
            {
                "segment_id": segment["segment_id"],
                "stabilization": {
                    "mode": "auto",
                    "strength": 0.35,
                    "max_crop_percent": 8.0,
                },
                "continuity": {
                    "transition": "hard_cut",
                    "duration_sec": 0.0,
                    "match_action": False,
                },
                "audio": {
                    "preserve_original": segment["keep_original_audio"],
                    "normalize_dialogue": segment["keep_original_audio"],
                },
            }
        )

    return {
        "schema_version": "1.0",
        "project_id": edit_plan["project_id"],
        "version": 1,
        "edit_plan_version": edit_plan["version"],
        "timeline_duration_sec": round(timeline_duration(edit_plan), 4),
        "render_stages": RENDER_STAGES,
        "video_treatments": treatments,
        "music": {
            "status": "planned",
            "tracks": [],
            "ducking": {
                "enabled": True,
                "dialogue_gain_db": -22.0,
                "attack_ms": 120,
                "release_ms": 450,
            },
        },
        "subtitles": {
            "status": "planned",
            "language": "zh-CN",
            "source": "work/transcripts/subtitles.json",
            "cues": [],
            "style": {
                "max_lines": 2,
                "safe_margin_percent": 8.0,
                "position": "bottom_center",
            },
        },
        "illustration_motion": {
            "status": "planned",
            "items": [],
            "subtitle_safe_zone": True,
        },
    }


def _issue(
    severity: str,
    code: str,
    subject_id: str,
    message: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "subject_id": subject_id,
        "message": message,
    }


def _range_is_valid(start: float, end: float, duration: float) -> bool:
    return 0 <= start < end <= duration


def validate_enhancement_plan(
    edit_plan: dict[str, Any],
    enhancement_plan: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    timeline = flatten_edit_plan(edit_plan)
    segment_ids = {segment["segment_id"] for segment in timeline}
    duration = timeline_duration(edit_plan)

    if enhancement_plan.get("project_id") != edit_plan.get("project_id"):
        issues.append(
            _issue("error", "project_mismatch", "enhancement_plan", "Project IDs differ.")
        )
    if enhancement_plan.get("edit_plan_version") != edit_plan.get("version"):
        issues.append(
            _issue(
                "error",
                "edit_plan_version_mismatch",
                "enhancement_plan",
                "Enhancement plan targets a different edit plan version.",
            )
        )
    if enhancement_plan.get("render_stages") != RENDER_STAGES:
        issues.append(
            _issue(
                "error",
                "invalid_render_order",
                "render_stages",
                "Render stages must preserve the required processing order.",
            )
        )

    treatment_ids: list[str] = []
    for treatment in enhancement_plan.get("video_treatments", []):
        segment_id = treatment["segment_id"]
        treatment_ids.append(segment_id)
        if segment_id not in segment_ids:
            issues.append(
                _issue(
                    "error",
                    "unknown_segment_treatment",
                    segment_id,
                    "Video treatment references an unknown segment.",
                )
            )
        stabilization = treatment.get("stabilization", {})
        if float(stabilization.get("max_crop_percent", 0)) > 15:
            issues.append(
                _issue(
                    "error",
                    "stabilization_crop_too_large",
                    segment_id,
                    "Stabilization may crop at most 15% of the frame.",
                )
            )
        audio = treatment.get("audio", {})
        source_segment = next(
            (segment for segment in timeline if segment["segment_id"] == segment_id),
            None,
        )
        if (
            source_segment
            and source_segment["keep_original_audio"]
            and not audio.get("preserve_original", False)
        ):
            issues.append(
                _issue(
                    "error",
                    "original_audio_removed",
                    segment_id,
                    "A segment marked to keep original audio cannot be muted by enhancement.",
                )
            )

    if set(treatment_ids) != segment_ids or len(treatment_ids) != len(segment_ids):
        issues.append(
            _issue(
                "error",
                "incomplete_video_treatments",
                "video_treatments",
                "Every edit segment must have exactly one video treatment.",
            )
        )

    music = enhancement_plan.get("music", {})
    if music.get("status") == "ready":
        if not music.get("tracks"):
            issues.append(
                _issue("error", "music_track_missing", "music", "Ready music needs a track.")
            )
        if not music.get("ducking", {}).get("enabled", False):
            issues.append(
                _issue(
                    "error",
                    "music_ducking_disabled",
                    "music",
                    "Dialogue-aware music ducking is required.",
                )
            )

    for cue_index, cue in enumerate(enhancement_plan.get("subtitles", {}).get("cues", [])):
        if not _range_is_valid(
            float(cue["start_sec"]), float(cue["end_sec"]), duration
        ):
            issues.append(
                _issue(
                    "error",
                    "subtitle_out_of_timeline",
                    f"subtitle-{cue_index + 1}",
                    "Subtitle cue must stay inside the output timeline.",
                )
            )

    for item in enhancement_plan.get("illustration_motion", {}).get("items", []):
        if not _range_is_valid(
            float(item["start_sec"]), float(item["end_sec"]), duration
        ):
            issues.append(
                _issue(
                    "error",
                    "overlay_out_of_timeline",
                    item["id"],
                    "Illustration or motion overlay must stay inside the output timeline.",
                )
            )
        if item.get("anchor") == "bottom_center":
            issues.append(
                _issue(
                    "warning",
                    "overlay_subtitle_conflict",
                    item["id"],
                    "Bottom-center overlays may conflict with subtitles.",
                )
            )

    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": "1.0",
        "status": "blocked" if blocking_count else "passed",
        "blocking_count": blocking_count,
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "timeline_duration_sec": round(duration, 4),
        "issues": issues,
    }
