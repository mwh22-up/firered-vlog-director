from __future__ import annotations

import math
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
    "max_chars_per_line": 18,
    "background_opacity_percent": 42.0,
    "background_padding": 8,
}

DEFAULT_VISUAL_TREATMENT = {
    "exposure_ev": 0.0,
    "brightness": 0.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "gamma": 1.0,
    "white_balance": {
        "red_shift": 0.0,
        "green_shift": 0.0,
        "blue_shift": 0.0,
    },
    "denoise": {"mode": "off"},
    "sharpen": {"mode": "off"},
    "reframe": {"mode": "off"},
    "speed": 1.0,
}

REALIZED_TIMELINE_TOLERANCE_SEC = 0.0001

SECTION_STATUSES = {"planned", "ready", "disabled"}
MUSIC_SECTION_STATUSES = SECTION_STATUSES | {"audition"}
SUBTITLE_SECTION_STATUSES = SECTION_STATUSES | {"review"}
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
                    "mode": "off",
                    "strength": 0.0,
                    "max_crop_percent": 0.0,
                },
                "continuity": {
                    "transition": "hard_cut",
                    "duration_sec": 0.0,
                    "match_action": False,
                },
                "audio": {
                    "preserve_original": segment["keep_original_audio"],
                    "normalize_dialogue": segment["keep_original_audio"],
                    "gain_db": 0.0,
                    "mute": not segment["keep_original_audio"],
                },
                "visual": deepcopy(DEFAULT_VISUAL_TREATMENT),
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
            "status": "disabled",
            "tracks": [],
            "ducking": {**DEFAULT_MUSIC_DUCKING, "enabled": False},
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


def find_non_finite_number_paths(
    value: Any,
    path: str = "$",
) -> list[str]:
    """Return JSON-style paths whose numeric values cannot reach FFmpeg safely."""
    if isinstance(value, bool):
        return []
    if isinstance(value, float):
        return [] if math.isfinite(value) else [path]
    if isinstance(value, dict):
        paths: list[str] = []
        for key, item in value.items():
            paths.extend(find_non_finite_number_paths(item, f"{path}.{key}"))
        return paths
    if isinstance(value, list):
        paths = []
        for index, item in enumerate(value):
            paths.extend(find_non_finite_number_paths(item, f"{path}[{index}]"))
        return paths
    return []


def normalize_realized_timeline(
    edit_plan: dict[str, Any],
    document: dict[str, Any] | list[dict[str, Any]],
    *,
    edit_plan_sha256: str | None = None,
) -> dict[str, Any]:
    """Convert a render report or portable timeline into renderer boundaries."""
    planned = flatten_edit_plan(edit_plan)
    if isinstance(document, list):
        measurements = document
        declared_duration = None
    elif isinstance(document, dict):
        if document.get("project_id", edit_plan.get("project_id")) != edit_plan.get(
            "project_id"
        ):
            raise ValueError("realized timeline project_id does not match the edit plan")
        if document.get("version", edit_plan.get("version")) != edit_plan.get("version"):
            raise ValueError("realized timeline version does not match the edit plan")
        if (
            edit_plan_sha256 is not None
            and document.get("plan_sha256") is not None
            and document["plan_sha256"] != edit_plan_sha256
        ):
            raise ValueError("realized timeline plan_sha256 does not match the edit plan")
        measurements = document.get("segments")
        if measurements is None:
            measurements = document.get("segment_measurements")
        declared_duration = document.get(
            "actual_duration_sec",
            document.get("duration_sec"),
        )
    else:
        raise ValueError("realized timeline must be an object or array")
    if not isinstance(measurements, list):
        raise ValueError("realized timeline has no segment measurements")

    expected_positions: list[tuple[str, int, str]] = []
    for chapter_index, chapter in enumerate(edit_plan.get("chapters", []), start=1):
        chapter_id = str(chapter.get("id", f"ch{chapter_index:02d}"))
        for segment_index, segment in enumerate(chapter.get("segments", []), start=1):
            expected_positions.append((chapter_id, segment_index, str(segment["source"])))

    report_boundaries: list[float] | None = None
    if isinstance(document, dict) and document.get("cut_boundaries") is not None:
        cuts = document["cut_boundaries"]
        if not isinstance(cuts, list) or len(cuts) != max(0, len(planned) - 1):
            raise ValueError("realized timeline cut boundary count does not match the edit plan")
        if declared_duration is None:
            raise ValueError("render report with cut boundaries requires actual_duration_sec")
        report_boundaries = [0.0]
        for index, cut in enumerate(cuts):
            if not isinstance(cut, dict) or "actual_time_sec" not in cut:
                raise ValueError(f"cut boundary {index + 1} has no actual_time_sec")
            actual_time = float(cut["actual_time_sec"])
            left_source = expected_positions[index][2].replace("\\", "/").lower()
            right_source = expected_positions[index + 1][2].replace("\\", "/").lower()
            if str(cut.get("left_source", left_source)).replace("\\", "/").lower() != left_source:
                raise ValueError(f"cut boundary {index + 1} left source does not match")
            if str(cut.get("right_source", right_source)).replace("\\", "/").lower() != right_source:
                raise ValueError(f"cut boundary {index + 1} right source does not match")
            report_boundaries.append(actual_time)
        report_boundaries.append(float(declared_duration))

    segments: list[dict[str, Any]] = []
    for index, measurement in enumerate(measurements):
        if not isinstance(measurement, dict):
            raise ValueError(f"realized timeline segment {index + 1} must be an object")
        expected_id = planned[index]["segment_id"] if index < len(planned) else None
        if index < len(expected_positions):
            chapter_id, segment_index, source = expected_positions[index]
            if str(measurement.get("chapter_id", chapter_id)) != chapter_id:
                raise ValueError(f"realized timeline segment {index + 1} chapter does not match")
            if int(measurement.get("segment_index", segment_index)) != segment_index:
                raise ValueError(f"realized timeline segment {index + 1} index does not match")
            measured_source = str(measurement.get("source", source)).replace("\\", "/").lower()
            if measured_source != source.replace("\\", "/").lower():
                raise ValueError(f"realized timeline segment {index + 1} source does not match")
        segment_id = measurement.get("segment_id", expected_id)
        if report_boundaries is not None and index + 1 < len(report_boundaries):
            start = report_boundaries[index]
            end = report_boundaries[index + 1]
            measured_start = measurement.get("actual_start_sec")
            measured_end = measurement.get("actual_end_sec")
            if measured_start is not None and abs(float(measured_start) - start) > 0.0001:
                raise ValueError(f"realized timeline segment {index + 1} start disagrees with cuts")
            if measured_end is not None and abs(float(measured_end) - end) > 0.0001:
                raise ValueError(f"realized timeline segment {index + 1} end disagrees with cuts")
        else:
            start = measurement.get(
                "start_sec",
                measurement.get("actual_start_sec"),
            )
            end = measurement.get(
                "end_sec",
                measurement.get("actual_end_sec"),
            )
        if segment_id is None or start is None or end is None:
            raise ValueError(
                f"realized timeline segment {index + 1} requires segment_id/start/end"
            )
        segments.append(
            {
                "segment_id": str(segment_id),
                "start_sec": float(start),
                "end_sec": float(end),
            }
        )

    if declared_duration is None:
        declared_duration = segments[-1]["end_sec"] if segments else 0.0
    normalized = {
        "duration_sec": float(declared_duration),
        "segments": segments,
    }
    if isinstance(document, dict):
        output_identity = document.get("output_identity", {})
        base_size_bytes = document.get("base_size_bytes")
        if base_size_bytes is None and isinstance(output_identity, dict):
            base_size_bytes = output_identity.get("size_bytes")
        if base_size_bytes is not None:
            if (
                not isinstance(base_size_bytes, int)
                or isinstance(base_size_bytes, bool)
                or base_size_bytes <= 0
            ):
                raise ValueError(
                    "realized timeline base_size_bytes must be a positive JSON integer"
                )
            normalized["base_size_bytes"] = base_size_bytes
        base_sha256 = document.get("base_sha256")
        if base_sha256 is None and isinstance(output_identity, dict):
            base_sha256 = output_identity.get("sha256")
        if base_sha256 is not None:
            digest = str(base_sha256).lower()
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("realized timeline base_sha256 must be a SHA-256 hex digest")
            normalized["base_sha256"] = digest
    return normalized


def validate_realized_timeline(
    edit_plan: dict[str, Any],
    realized_timeline: dict[str, Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    expected = flatten_edit_plan(edit_plan)
    expected_ids = [segment["segment_id"] for segment in expected]
    segments = realized_timeline.get("segments", [])
    if not isinstance(segments, list):
        return [
            _issue(
                "error",
                "invalid_realized_timeline",
                "realized_timeline",
                "Realized timeline segments must be an array.",
            )
        ]
    if len(segments) != len(expected):
        issues.append(
            _issue(
                "error",
                "realized_timeline_segment_count_mismatch",
                "realized_timeline",
                "Realized timeline must contain exactly one boundary for every edit segment.",
            )
        )

    actual_ids = [str(segment.get("segment_id", "")) for segment in segments]
    if actual_ids != expected_ids:
        issues.append(
            _issue(
                "error",
                "realized_timeline_segment_order_mismatch",
                "realized_timeline",
                "Realized timeline segment IDs and order must match the edit plan.",
            )
        )

    previous_end: float | None = None
    for index, segment in enumerate(segments):
        segment_id = str(segment.get("segment_id") or f"segment-{index + 1}")
        try:
            start = float(segment["start_sec"])
            end = float(segment["end_sec"])
        except (KeyError, TypeError, ValueError):
            issues.append(
                _issue(
                    "error",
                    "invalid_realized_timeline_boundary",
                    segment_id,
                    "Every realized segment requires numeric start_sec and end_sec.",
                )
            )
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            issues.append(
                _issue(
                    "error",
                    "invalid_realized_timeline_boundary",
                    segment_id,
                    "Realized segment boundaries must satisfy 0 <= start_sec < end_sec.",
                )
            )
        if previous_end is None:
            if abs(start) > REALIZED_TIMELINE_TOLERANCE_SEC:
                issues.append(
                    _issue(
                        "error",
                        "realized_timeline_does_not_start_at_zero",
                        segment_id,
                        "Realized timeline must start at zero.",
                    )
                )
        elif abs(start - previous_end) > REALIZED_TIMELINE_TOLERANCE_SEC:
            issues.append(
                _issue(
                    "error",
                    "realized_timeline_not_contiguous",
                    segment_id,
                    "Realized segment boundaries must be contiguous.",
                )
            )
        previous_end = end

    try:
        duration = float(realized_timeline["duration_sec"])
    except (KeyError, TypeError, ValueError):
        issues.append(
            _issue(
                "error",
                "invalid_realized_timeline_duration",
                "realized_timeline",
                "Realized timeline requires a numeric duration_sec.",
            )
        )
    else:
        if not math.isfinite(duration) or duration <= 0 or (
            previous_end is not None
            and abs(duration - previous_end) > REALIZED_TIMELINE_TOLERANCE_SEC
        ):
            issues.append(
                _issue(
                    "error",
                    "realized_timeline_duration_mismatch",
                    "realized_timeline",
                    "Realized duration must match the final segment boundary.",
                )
            )
    return issues


def treatments_require_realized_timeline(
    enhancement_plan: dict[str, Any],
) -> bool:
    for treatment in enhancement_plan.get("video_treatments", []):
        stabilization = treatment.get("stabilization", {})
        continuity = treatment.get("continuity", {})
        audio = treatment.get("audio", {})
        visual = treatment.get("visual", {})
        if stabilization.get("mode", "off") != "off":
            return True
        if (
            continuity.get("transition", "hard_cut") != "hard_cut"
            or float(continuity.get("duration_sec", 0.0)) != 0.0
            or bool(continuity.get("match_action", False))
        ):
            return True
        if (
            not bool(audio.get("preserve_original", True))
            or bool(audio.get("mute", False))
            or float(audio.get("gain_db", 0.0)) != 0.0
        ):
            return True
        if visual:
            if any(
                float(visual.get(field, neutral)) != neutral
                for field, neutral in (
                    ("exposure_ev", 0.0),
                    ("brightness", 0.0),
                    ("contrast", 1.0),
                    ("saturation", 1.0),
                    ("gamma", 1.0),
                    ("speed", 1.0),
                )
            ):
                return True
            white_balance = visual.get("white_balance", {})
            if any(float(value) != 0.0 for value in white_balance.values()):
                return True
            if visual.get("denoise", {}).get("mode", "off") != "off":
                return True
            if visual.get("sharpen", {}).get("mode", "off") != "off":
                return True
            if visual.get("reframe", {}).get("mode", "off") != "off":
                return True
    return False


def visual_treatments_active(enhancement_plan: dict[str, Any]) -> bool:
    """Return whether any pixel-changing per-segment treatment is active."""
    for treatment in enhancement_plan.get("video_treatments", []):
        visual = treatment.get("visual", {})
        if any(
            float(visual.get(field, neutral)) != neutral
            for field, neutral in (
                ("exposure_ev", 0.0),
                ("brightness", 0.0),
                ("contrast", 1.0),
                ("saturation", 1.0),
                ("gamma", 1.0),
                ("speed", 1.0),
            )
        ):
            return True
        if any(
            float(value) != 0.0
            for value in visual.get("white_balance", {}).values()
        ):
            return True
        if any(
            visual.get(name, {}).get("mode", "off") != "off"
            for name in ("denoise", "sharpen", "reframe")
        ):
            return True
    return False


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
    *,
    realized_timeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    timeline = flatten_edit_plan(edit_plan)
    segment_ids = {segment["segment_id"] for segment in timeline}
    duration = timeline_duration(edit_plan)
    non_finite_paths = find_non_finite_number_paths(enhancement_plan)
    if realized_timeline is not None:
        non_finite_paths.extend(
            find_non_finite_number_paths(realized_timeline, "$.realized_timeline")
        )
    if non_finite_paths:
        for path in non_finite_paths:
            issues.append(
                _issue(
                    "error",
                    "non_finite_number",
                    path,
                    "Enhancement and realized-timeline numbers must be finite.",
                )
            )
        return _validation_result(issues, duration)
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
    audible_normalization_modes: set[bool] = set()
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
        if stabilization.get("mode", "off") != "off":
            issues.append(
                _issue(
                    "error",
                    "unsupported_stabilization_mode",
                    segment_id,
                    "Only stabilization mode 'off' is executable by the enhancement renderer.",
                )
            )
        elif (
            float(stabilization.get("strength", 0.0)) != 0.0
            or float(stabilization.get("max_crop_percent", 0.0)) != 0.0
        ):
            issues.append(
                _issue(
                    "error",
                    "inactive_stabilization_parameters",
                    segment_id,
                    "Stabilization mode 'off' requires zero strength and crop parameters.",
                )
            )
        if float(stabilization.get("max_crop_percent", 0)) > 15:
            issues.append(
                _issue(
                    "error",
                    "stabilization_crop_too_large",
                    segment_id,
                    "Stabilization may crop at most 15% of the frame.",
                )
            )

        continuity = treatment.get("continuity", {})
        if (
            continuity.get("transition", "hard_cut") != "hard_cut"
            or float(continuity.get("duration_sec", 0.0)) != 0.0
            or bool(continuity.get("match_action", False))
        ):
            issues.append(
                _issue(
                    "error",
                    "unsupported_continuity_treatment",
                    segment_id,
                    "Only a zero-duration hard cut without match_action is currently executable.",
                )
            )

        visual = treatment.get("visual", {})
        if float(visual.get("speed", 1.0)) != 1.0:
            issues.append(
                _issue(
                    "error",
                    "unsupported_segment_speed",
                    segment_id,
                    "Segment speed must remain 1.0 until downstream timing can be retimed safely.",
                )
            )
        for treatment_name, renderer_name in (
            ("denoise", "hqdn3d"),
            ("sharpen", "unsharp"),
            ("reframe", "crop"),
        ):
            visual_treatment = visual.get(treatment_name, {})
            if (
                visual_treatment.get("mode", "off") == "off"
                and set(visual_treatment) - {"mode"}
            ):
                issues.append(
                    _issue(
                        "error",
                        f"inactive_{treatment_name}_parameters",
                        segment_id,
                        f"{treatment_name.capitalize()} mode 'off' cannot retain "
                        f"unused {renderer_name} parameters.",
                    )
                )
        reframe = visual.get("reframe", {})
        if (
            reframe.get("mode", "off") == "crop"
            and abs(
                float(reframe.get("width_percent", 100.0))
                - float(reframe.get("height_percent", 100.0))
            )
            > 0.001
        ):
            issues.append(
                _issue(
                    "error",
                    "reframe_aspect_ratio_changed",
                    segment_id,
                    "Crop width_percent and height_percent must match to preserve aspect ratio.",
                )
            )

        audio = treatment.get("audio", {})
        preserve_original = bool(audio.get("preserve_original", False))
        mute = bool(audio.get("mute", False))
        gain_db = float(audio.get("gain_db", 0.0))
        normalize_dialogue = bool(audio.get("normalize_dialogue", False))
        source_segment = next(
            (segment for segment in timeline if segment["segment_id"] == segment_id),
            None,
        )
        if (
            source_segment
            and source_segment["keep_original_audio"]
            and not preserve_original
        ):
            issues.append(
                _issue(
                    "error",
                    "original_audio_removed",
                    segment_id,
                    "A segment marked to keep original audio cannot be muted by enhancement.",
                )
            )
        if preserve_original and mute:
            issues.append(
                _issue(
                    "error",
                    "conflicting_audio_treatment",
                    segment_id,
                    "A treatment cannot both preserve and mute original audio.",
                )
            )
        if (mute or not preserve_original) and gain_db != 0.0:
            issues.append(
                _issue(
                    "error",
                    "muted_audio_gain_ignored",
                    segment_id,
                    "Muted audio must use gain_db=0 so every field has executable meaning.",
                )
            )
        if not preserve_original and normalize_dialogue:
            issues.append(
                _issue(
                    "error",
                    "muted_audio_cannot_normalize",
                    segment_id,
                    "Removed original audio cannot request dialogue normalization.",
                )
            )
        if preserve_original and not mute:
            audible_normalization_modes.add(normalize_dialogue)

    if set(treatment_ids) != segment_ids or len(treatment_ids) != len(segment_ids):
        issues.append(
            _issue(
                "error",
                "incomplete_video_treatments",
                "video_treatments",
                "Every edit segment must have exactly one video treatment.",
            )
        )

    if len(audible_normalization_modes) > 1:
        issues.append(
            _issue(
                "error",
                "mixed_dialogue_normalization_unsupported",
                "video_treatments",
                "Audible segments must agree on normalize_dialogue for deterministic final mixing.",
            )
        )

    output_duration = duration
    if realized_timeline is not None:
        issues.extend(validate_realized_timeline(edit_plan, realized_timeline))
        if enhancement_plan.get("video_treatments"):
            base_size_bytes = realized_timeline.get("base_size_bytes")
            base_sha256 = str(realized_timeline.get("base_sha256", "")).lower()
            if (
                not isinstance(base_size_bytes, int)
                or isinstance(base_size_bytes, bool)
                or base_size_bytes <= 0
                or len(base_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in base_sha256
                )
            ):
                issues.append(
                    _issue(
                        "error",
                        "realized_timeline_base_identity_required",
                        "realized_timeline",
                        "Per-segment rendering requires a positive base media size and SHA-256 identity.",
                    )
                )
        try:
            realized_duration = float(realized_timeline["duration_sec"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if math.isfinite(realized_duration) and realized_duration > 0:
                output_duration = realized_duration
    elif treatments_require_realized_timeline(enhancement_plan):
        issues.append(
            _issue(
                "error",
                "realized_timeline_required",
                "video_treatments",
                "Executable per-segment treatments require actual encoded segment boundaries.",
            )
        )

    music = enhancement_plan.get("music", {})
    if music.get("status") not in MUSIC_SECTION_STATUSES:
        issues.append(
            _issue(
                "error",
                "invalid_music_status",
                "music",
                "Music status must be planned, audition, ready, or disabled.",
            )
        )
    music_tracks = music.get("tracks", [])
    if music_tracks and music.get("status") not in {"audition", "ready"}:
        issues.append(
            _issue(
                "error",
                "music_not_release_ready",
                "music",
                "Music tracks may render only when the music section is audition or ready.",
            )
        )
    track_ids: list[str] = []
    for track_index, track in enumerate(music_tracks, start=1):
        track_id = str(track.get("id") or f"music-{track_index}")
        track_ids.append(track_id)
        start_sec = float(track.get("start_sec", -1.0))
        end_sec = float(track.get("end_sec", -1.0))
        if not _range_is_valid(start_sec, end_sec, output_duration):
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
    subtitle_status = subtitle_section.get("status")
    if subtitle_status not in SUBTITLE_SECTION_STATUSES:
        issues.append(
            _issue(
                "error",
                "invalid_subtitle_status",
                "subtitles",
                "Subtitle status must be planned, review, ready, or disabled.",
            )
        )
    subtitle_cues = subtitle_section.get("cues", [])
    if subtitle_cues and subtitle_status not in {"review", "ready"}:
        issues.append(
            _issue(
                "error",
                "subtitles_not_release_ready",
                "subtitles",
                "Subtitle cues may render only when the subtitle section is review or ready.",
            )
        )

    if subtitle_status in {"review", "ready"}:
        if not subtitle_cues:
            issues.append(
                _issue(
                    "error",
                    (
                        "ready_subtitles_empty"
                        if subtitle_status == "ready"
                        else "review_subtitles_empty"
                    ),
                    "subtitles",
                    "A review or ready subtitle section must contain at least one cue.",
                )
            )
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

    if subtitle_status == "review":
        if subtitle_section.get("coverage", {}).get("status") not in {
            "pending",
            "verified",
        }:
            issues.append(
                _issue(
                    "error",
                    "subtitle_review_coverage_invalid",
                    "subtitles",
                    "Review subtitles require pending or verified coverage.",
                )
            )
        for cue_index, cue in enumerate(subtitle_cues, start=1):
            if cue.get("review_status") not in {"review_required", "verified"}:
                issues.append(
                    _issue(
                        "error",
                        "subtitle_review_cue_status_invalid",
                        f"subtitle-{cue_index}",
                        "Review subtitle cues must be review_required or verified.",
                    )
                )

    if subtitle_status == "ready":
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

    timed_subtitle_cues = []
    for cue_index, cue in enumerate(subtitle_cues):
        cue_start = float(cue["start_sec"])
        cue_end = float(cue["end_sec"])
        timed_subtitle_cues.append((cue_start, cue_end, cue_index))
        if not _range_is_valid(cue_start, cue_end, output_duration):
            issues.append(
                _issue(
                    "error",
                    "subtitle_out_of_timeline",
                    f"subtitle-{cue_index + 1}",
                    "Subtitle cue must stay inside the output timeline.",
                )
            )
    timed_subtitle_cues.sort(key=lambda item: (item[0], item[1], item[2]))
    for left, right in zip(timed_subtitle_cues, timed_subtitle_cues[1:]):
        if right[0] < left[1]:
            issues.append(
                _issue(
                    "error",
                    "subtitle_cue_overlap",
                    f"subtitle-{right[2] + 1}",
                    f"Subtitle cue overlaps subtitle-{left[2] + 1}.",
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
    subtitle_positions = {
        str(cue.get("position", subtitle_section.get("style", {}).get("position", "bottom_center")))
        for cue in subtitle_cues
    }
    overlay_ids: list[str] = []
    for item in illustration_items:
        overlay_ids.append(str(item.get("id", "")))
        start_sec = float(item["start_sec"])
        end_sec = float(item["end_sec"])
        if not _range_is_valid(
            start_sec, end_sec, output_duration
        ):
            issues.append(
                _issue(
                    "error",
                    "overlay_out_of_timeline",
                    item["id"],
                    "Illustration or motion overlay must stay inside the output timeline.",
                )
            )
        animation = item.get("animation", "none")
        animation_duration = item.get("animation_duration_sec")
        if animation == "none" and animation_duration is not None:
            issues.append(
                _issue(
                    "error",
                    "inactive_overlay_animation_duration",
                    item["id"],
                    "Overlay animation_duration_sec must be omitted when animation is none.",
                )
            )
        elif animation in {"fade", "slide"}:
            animation_duration_value = float(
                animation_duration
                if animation_duration is not None
                else min(0.35, max(0.0, end_sec - start_sec) / 3.0)
            )
            if (
                animation_duration_value < 0.1
                or animation_duration_value * 2 >= end_sec - start_sec
            ):
                issues.append(
                    _issue(
                        "error",
                        "invalid_overlay_animation_duration",
                        item["id"],
                        "Overlay animation must leave a visible hold interval.",
                    )
                )
        anchor = str(item.get("anchor", ""))
        conflicts_with_reserved_subtitle_zone = (
            (anchor.startswith("bottom_") and "bottom_center" in subtitle_positions)
            or (anchor.startswith("top_") and "top_center" in subtitle_positions)
        )
        if (
            illustration_section.get("subtitle_safe_zone")
            and subtitle_cues
            and conflicts_with_reserved_subtitle_zone
        ):
            issues.append(
                _issue(
                    "error",
                    "overlay_subtitle_safe_zone_violation",
                    item["id"],
                    "Overlay anchor occupies a vertical edge reserved by subtitles.",
                )
            )
        elif anchor == "bottom_center":
            issues.append(
                _issue(
                    "warning",
                    "overlay_subtitle_conflict",
                    item["id"],
                    "Bottom-center overlays may conflict with subtitles.",
                )
            )

    if len(overlay_ids) != len(set(overlay_ids)):
        issues.append(
            _issue(
                "error",
                "duplicate_overlay_id",
                "illustration_motion",
                "Illustration and motion item IDs must be unique.",
            )
        )

    return _validation_result(issues, duration)
