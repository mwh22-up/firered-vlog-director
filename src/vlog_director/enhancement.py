from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema_validation import enhancement_schema_errors
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

DEFAULT_MUSIC_DUCKING = {
    "enabled": True,
    "threshold": 0.125,
    "ratio": 8.0,
    "attack_ms": 20,
    "release_ms": 250,
}

DEFAULT_SUBTITLE_STYLE = {
    "max_lines": 2,
    "safe_margin_percent": 8.0,
    "position": "bottom_center",
    "font_name": "Microsoft YaHei",
    "font_size": 64,
    "margin_v": 72,
    "outline": 4,
    "shadow": 1,
    "bold": True,
}

SECTION_STATUSES = {"planned", "ready", "disabled"}
LEGACY_MUSIC_STATUSES = {
    "reference_pending",
    "reference_ready",
    "no_music_suggestion",
}
LEGACY_MUSIC_FIELDS = {
    "mode",
    "non_blocking",
    "recommendations",
    "usage",
    "reference_evidence",
    "timeline_duration_sec",
    "suggested_coverage_ratio",
    "dialogue_evidence",
    "dialogue_intervals",
}


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
            "ducking": dict(DEFAULT_MUSIC_DUCKING),
        },
        "subtitles": {
            "status": "planned",
            "language": "zh-CN",
            "source": "work/transcripts/subtitles.json",
            "cues": [],
            "coverage": {"status": "pending"},
            "style": dict(DEFAULT_SUBTITLE_STYLE),
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


def normalize_enhancement_plan(
    enhancement_plan: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Normalize known pre-contract 1.0 music fields without hiding new errors."""
    normalized = deepcopy(enhancement_plan)
    music = normalized.get("music")
    migrations: list[str] = []
    if not isinstance(music, dict):
        return normalized, migrations

    legacy_advisory = (
        music.get("status") in LEGACY_MUSIC_STATUSES
        or any(field in music for field in LEGACY_MUSIC_FIELDS)
    )
    if legacy_advisory:
        tracks = music.get("tracks", [])
        music["status"] = (
            "ready"
            if tracks
            else "disabled"
            if music.get("status") == "no_music_suggestion"
            else "planned"
        )
        for field in LEGACY_MUSIC_FIELDS:
            music.pop(field, None)
        migrations.append("legacy_music_advisory")

    ducking = music.get("ducking")
    legacy_ducking = isinstance(ducking, dict) and (
        "dialogue_gain_db" in ducking
        or (
            legacy_advisory
            and any(key not in ducking for key in DEFAULT_MUSIC_DUCKING)
        )
    )
    if legacy_advisory and not isinstance(ducking, dict):
        ducking = {}
        legacy_ducking = True
    if legacy_ducking:
        compatible = {
            key: value
            for key, value in ducking.items()
            if key in DEFAULT_MUSIC_DUCKING
        }
        migrated_ducking = dict(DEFAULT_MUSIC_DUCKING) | compatible
        migrated_ducking["attack_ms"] = min(
            2000,
            max(1, int(migrated_ducking["attack_ms"])),
        )
        migrated_ducking["release_ms"] = min(
            9000,
            max(1, int(migrated_ducking["release_ms"])),
        )
        music["ducking"] = migrated_ducking
        migrations.append("legacy_music_ducking")

    return normalized, migrations


def _validation_result(
    issues: list[dict[str, str]],
    duration: float,
) -> dict[str, Any]:
    blocking_count = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": "1.0",
        "status": "blocked" if blocking_count else "passed",
        "blocking_count": blocking_count,
        "warning_count": sum(issue["severity"] == "warning" for issue in issues),
        "timeline_duration_sec": round(duration, 4),
        "issues": issues,
    }


def validate_enhancement_plan(
    edit_plan: dict[str, Any],
    enhancement_plan: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    timeline = flatten_edit_plan(edit_plan)
    segment_ids = {segment["segment_id"] for segment in timeline}
    duration = timeline_duration(edit_plan)
    enhancement_plan, migrations = normalize_enhancement_plan(enhancement_plan)
    if migrations:
        issues.append(
            _issue(
                "warning",
                "legacy_enhancement_plan_migrated",
                "music",
                "Known legacy music fields were normalized: "
                + ", ".join(migrations),
            )
        )

    schema_errors = enhancement_schema_errors(enhancement_plan)
    if schema_errors:
        for error in schema_errors:
            issues.append(
                _issue(
                    "error",
                    "enhancement_schema_invalid",
                    str(error.json_path),
                    error.message,
                )
            )
        if any(error.validator in {"required", "type"} for error in schema_errors):
            return _validation_result(issues, duration)

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
    if abs(float(enhancement_plan.get("timeline_duration_sec", -1.0)) - duration) > 0.001:
        issues.append(
            _issue(
                "error",
                "timeline_duration_mismatch",
                "enhancement_plan",
                "Enhancement plan duration must match the edit plan timeline.",
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
    if music.get("status") not in SECTION_STATUSES:
        issues.append(
            _issue(
                "error",
                "invalid_music_status",
                "music",
                "Music status must be planned, ready, or disabled.",
            )
        )
    music_tracks = music.get("tracks", [])
    if music_tracks and music.get("status") != "ready":
        issues.append(
            _issue(
                "error",
                "music_not_release_ready",
                "music",
                "Music tracks may render only when the music section is ready.",
            )
        )
    track_ids: list[str] = []
    for track_index, track in enumerate(music_tracks, start=1):
        track_id = str(track.get("id") or f"music-{track_index}")
        track_ids.append(track_id)
        start_sec = float(track.get("start_sec", -1.0))
        end_sec = float(track.get("end_sec", -1.0))
        if not _range_is_valid(start_sec, end_sec, duration):
            issues.append(
                _issue(
                    "error",
                    "music_track_out_of_timeline",
                    track_id,
                    "Music track must stay inside the output timeline.",
                )
            )
        track_duration = max(0.0, end_sec - start_sec)
        fade_in = float(track.get("fade_in_sec", 0.0))
        fade_out = float(track.get("fade_out_sec", 0.0))
        if fade_in < 0 or fade_out < 0 or fade_in + fade_out > track_duration:
            issues.append(
                _issue(
                    "error",
                    "invalid_music_fades",
                    track_id,
                    "Music fades must be non-negative and fit inside the track interval.",
                )
            )
    if len(track_ids) != len(set(track_ids)):
        issues.append(
            _issue(
                "error",
                "duplicate_music_track_id",
                "music",
                "Music track IDs must be unique.",
            )
        )

    subtitle_section = enhancement_plan.get("subtitles", {})
    if subtitle_section.get("status") not in SECTION_STATUSES:
        issues.append(
            _issue(
                "error",
                "invalid_subtitle_status",
                "subtitles",
                "Subtitle status must be planned, ready, or disabled.",
            )
        )
    subtitle_cues = subtitle_section.get("cues", [])
    if subtitle_cues and subtitle_section.get("status") != "ready":
        issues.append(
            _issue(
                "error",
                "subtitles_not_release_ready",
                "subtitles",
                "Subtitle cues may render only after semantic and source-coverage review.",
            )
        )

    if subtitle_section.get("status") == "ready":
        style = subtitle_section.get("style", {})
        if int(style.get("font_size", 0)) < 60:
            issues.append(
                _issue(
                    "error",
                    "subtitle_font_too_small",
                    "subtitles",
                    "1080p subtitles require font_size >= 60.",
                )
            )
        if int(style.get("outline", 0)) < 3:
            issues.append(
                _issue(
                    "error",
                    "subtitle_outline_too_thin",
                    "subtitles",
                    "Readable subtitles require outline >= 3.",
                )
            )
        if subtitle_section.get("coverage", {}).get("status") != "verified":
            issues.append(
                _issue(
                    "error",
                    "subtitle_coverage_unverified",
                    "subtitles",
                    "Dialogue coverage must be verified before release.",
                )
            )
        for cue_index, cue in enumerate(subtitle_cues, start=1):
            if cue.get("review_status") != "verified":
                issues.append(
                    _issue(
                        "error",
                        "subtitle_cue_unverified",
                        f"subtitle-{cue_index}",
                        "Every subtitle cue must be checked against source audio.",
                    )
                )

    for cue_index, cue in enumerate(subtitle_cues):
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

    illustration_section = enhancement_plan.get("illustration_motion", {})
    if illustration_section.get("status") not in SECTION_STATUSES:
        issues.append(
            _issue(
                "error",
                "invalid_illustration_motion_status",
                "illustration_motion",
                "Illustration and motion status must be planned, ready, or disabled.",
            )
        )
    illustration_items = illustration_section.get("items", [])
    if illustration_items and illustration_section.get("status") != "ready":
        issues.append(
            _issue(
                "error",
                "illustration_motion_not_release_ready",
                "illustration_motion",
                "Illustration and motion items may render only when their section is ready.",
            )
        )
    for item in illustration_items:
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

    return _validation_result(issues, duration)
