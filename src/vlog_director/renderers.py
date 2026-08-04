from __future__ import annotations

import json
import hashlib
import math
import tempfile
from pathlib import Path
from typing import Any

from .enhancement import (
    DEFAULT_MUSIC_DUCKING,
    REALIZED_TIMELINE_TOLERANCE_SEC,
    find_non_finite_number_paths,
    treatments_require_realized_timeline,
)
from .enhancement_assets import validate_enhancement_assets
from .ffmpeg import filter_path, find_ffmpeg, probe_media, require_filters, run_command
from .overlays import (
    SUPPORTED_OVERLAY_ANIMATIONS,
    build_hyperframes_overlay_filters,
    build_overlay_filters,
)
from .subtitle_render_contract import (
    build_subtitle_render_contract,
    subtitle_filter_expression,
    write_contract_ass,
)
from .subtitles import write_ass_subtitles

TERMINAL_PAD_FRAMES = 1
VIDEO_PRESETS = {
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _gain_to_linear(gain_db: float) -> float:
    return math.pow(10.0, gain_db / 20.0)


def _resolve_project_asset(project: Path, source: str) -> Path:
    relative = Path(source)
    if relative.is_absolute():
        raise ValueError("enhancement assets must use project-relative paths")
    assets_root = (project / "assets").resolve()
    resolved = (project / relative).resolve()
    try:
        resolved.relative_to(assets_root)
    except ValueError as error:
        raise ValueError("enhancement assets must stay inside project/assets") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _resolve_overlay_asset(project: Path, item: dict[str, Any]) -> Path:
    if item.get("type") != "hyperframes":
        return _resolve_project_asset(project, str(item["source"]))
    relative = Path(str(item["source"]))
    if relative.is_absolute():
        raise ValueError("HyperFrames assets must use project-relative paths")
    allowed_root = (project / "work" / "effects").resolve()
    resolved = (project / relative).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as error:
        raise ValueError("HyperFrames assets must stay inside project/work/effects") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    if _sha256_file(resolved) != item.get("source_sha256"):
        raise ValueError("HyperFrames asset SHA-256 does not match the approved effect")
    return resolved


def _music_filter_chain(index: int, track: dict[str, Any], label: str) -> str:
    start = float(track["start_sec"])
    end = float(track["end_sec"])
    duration = end - start
    if duration <= 0:
        raise ValueError("music track end_sec must be greater than start_sec")
    fade_in = min(duration, max(0.0, float(track.get("fade_in_sec", 0.0))))
    fade_out = min(
        max(0.0, duration - fade_in),
        max(0.0, float(track.get("fade_out_sec", 0.0))),
    )
    delay_ms = round(start * 1000)
    gain = _gain_to_linear(float(track["gain_db"]))
    filters = [
        f"[{index}:a]atrim=0:{duration:.3f}",
        "asetpts=PTS-STARTPTS",
        f"volume={gain:.8f}",
    ]
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        filters.append(
            f"afade=t=out:st={duration - fade_out:.3f}:d={fade_out:.3f}"
        )
    filters.append(f"adelay={delay_ms}|{delay_ms}[{label}]")
    return ",".join(filters)


def _anchor_expression(anchor: str) -> tuple[str, str]:
    anchors = {
        "top_left": ("40", "40"),
        "top_right": ("W-w-40", "40"),
        "center": ("(W-w)/2", "(H-h)/2"),
        "bottom_left": ("40", "H-h-40"),
        "bottom_right": ("W-w-40", "H-h-40"),
        "bottom_center": ("(W-w)/2", "H-h-40"),
    }
    return anchors[anchor]


def _unknown_keys(
    value: dict[str, Any],
    allowed: set[str],
    subject: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{subject} contains unsupported fields: {', '.join(unknown)}")


def _ensure_runtime_treatments_supported(
    treatments: list[dict[str, Any]],
) -> bool:
    normalization_modes: set[bool] = set()
    for treatment in treatments:
        segment_id = str(treatment.get("segment_id", "video_treatment"))
        _unknown_keys(
            treatment,
            {"segment_id", "stabilization", "continuity", "audio", "visual"},
            segment_id,
        )
        stabilization = treatment.get("stabilization", {})
        _unknown_keys(
            stabilization,
            {"mode", "strength", "max_crop_percent"},
            f"{segment_id}.stabilization",
        )
        if stabilization.get("mode", "off") != "off":
            raise ValueError(
                f"{segment_id} requests unsupported stabilization mode "
                f"{stabilization.get('mode')!r}"
            )
        if (
            float(stabilization.get("strength", 0.0)) != 0.0
            or float(stabilization.get("max_crop_percent", 0.0)) != 0.0
        ):
            raise ValueError(f"{segment_id} disables stabilization but retains parameters")

        continuity = treatment.get("continuity", {})
        _unknown_keys(
            continuity,
            {"transition", "duration_sec", "match_action"},
            f"{segment_id}.continuity",
        )
        if (
            continuity.get("transition", "hard_cut") != "hard_cut"
            or float(continuity.get("duration_sec", 0.0)) != 0.0
            or bool(continuity.get("match_action", False))
        ):
            raise ValueError(f"{segment_id} requests an unsupported continuity treatment")

        audio = treatment.get("audio", {})
        _unknown_keys(
            audio,
            {"preserve_original", "normalize_dialogue", "gain_db", "mute"},
            f"{segment_id}.audio",
        )
        preserve_original = bool(audio.get("preserve_original", True))
        mute = bool(audio.get("mute", False))
        gain_db = float(audio.get("gain_db", 0.0))
        if preserve_original and mute:
            raise ValueError(f"{segment_id} cannot preserve and mute original audio")
        if (mute or not preserve_original) and gain_db != 0.0:
            raise ValueError(f"{segment_id} cannot apply gain to muted audio")
        if preserve_original and not mute:
            normalization_modes.add(bool(audio.get("normalize_dialogue", False)))

        visual = treatment.get("visual", {})
        _unknown_keys(
            visual,
            {
                "exposure_ev",
                "brightness",
                "contrast",
                "saturation",
                "gamma",
                "white_balance",
                "denoise",
                "sharpen",
                "reframe",
                "speed",
            },
            f"{segment_id}.visual",
        )
        if float(visual.get("speed", 1.0)) != 1.0:
            raise ValueError(f"{segment_id} requests unsupported segment speed")
        white_balance = visual.get("white_balance", {})
        _unknown_keys(
            white_balance,
            {"red_shift", "green_shift", "blue_shift"},
            f"{segment_id}.visual.white_balance",
        )
        denoise = visual.get("denoise", {})
        _unknown_keys(
            denoise,
            {
                "mode",
                "luma_spatial",
                "chroma_spatial",
                "luma_temporal",
                "chroma_temporal",
            },
            f"{segment_id}.visual.denoise",
        )
        if denoise.get("mode", "off") == "off" and set(denoise) - {"mode"}:
            raise ValueError(f"{segment_id} has unused hqdn3d parameters while disabled")
        if denoise.get("mode", "off") not in {"off", "hqdn3d"}:
            raise ValueError(f"{segment_id} requests unsupported denoise mode")
        sharpen = visual.get("sharpen", {})
        _unknown_keys(
            sharpen,
            {"mode", "amount"},
            f"{segment_id}.visual.sharpen",
        )
        if sharpen.get("mode", "off") == "off" and set(sharpen) - {"mode"}:
            raise ValueError(f"{segment_id} has unused unsharp parameters while disabled")
        if sharpen.get("mode", "off") not in {"off", "unsharp"}:
            raise ValueError(f"{segment_id} requests unsupported sharpen mode")
        reframe = visual.get("reframe", {})
        _unknown_keys(
            reframe,
            {"mode", "width_percent", "height_percent", "x_percent", "y_percent"},
            f"{segment_id}.visual.reframe",
        )
        if reframe.get("mode", "off") == "off" and set(reframe) - {"mode"}:
            raise ValueError(f"{segment_id} has unused crop parameters while disabled")
        if reframe.get("mode", "off") not in {"off", "crop"}:
            raise ValueError(f"{segment_id} requests unsupported reframe mode")
        if (
            reframe.get("mode", "off") == "crop"
            and abs(
                float(reframe.get("width_percent", 100.0))
                - float(reframe.get("height_percent", 100.0))
            )
            > 0.001
        ):
            raise ValueError(f"{segment_id} crop must preserve the source aspect ratio")
    if len(normalization_modes) > 1:
        raise ValueError("audible treatments cannot mix normalize_dialogue modes")
    return normalization_modes == {True}


def _validate_runtime_timeline(
    treatments: list[dict[str, Any]],
    realized_timeline: dict[str, Any],
) -> None:
    segments = realized_timeline.get("segments")
    if not isinstance(segments, list) or len(segments) != len(treatments):
        raise ValueError("realized timeline must cover every video treatment exactly once")
    treatment_ids = [str(item.get("segment_id", "")) for item in treatments]
    timeline_ids = [str(item.get("segment_id", "")) for item in segments]
    if treatment_ids != timeline_ids or len(set(timeline_ids)) != len(timeline_ids):
        raise ValueError("realized timeline segment IDs and order must match treatments")
    previous_end: float | None = None
    for segment in segments:
        start = float(segment["start_sec"])
        end = float(segment["end_sec"])
        if start < 0 or end <= start:
            raise ValueError("realized timeline has an invalid segment boundary")
        if previous_end is None:
            if abs(start) > REALIZED_TIMELINE_TOLERANCE_SEC:
                raise ValueError("realized timeline must start at zero")
        elif abs(start - previous_end) > REALIZED_TIMELINE_TOLERANCE_SEC:
            raise ValueError("realized timeline boundaries must be contiguous")
        previous_end = end
    duration = float(realized_timeline["duration_sec"])
    if previous_end is None or abs(previous_end - duration) > REALIZED_TIMELINE_TOLERANCE_SEC:
        raise ValueError("realized timeline duration must match its final boundary")


def _visual_filter_chain(
    treatment: dict[str, Any],
    width: int,
    height: int,
) -> tuple[list[str], set[str]]:
    visual = treatment.get("visual", {})
    filters: list[str] = []
    required: set[str] = set()
    exposure = float(visual.get("exposure_ev", 0.0))
    if exposure != 0.0:
        filters.append(f"exposure=exposure={exposure:.4f}:black=0")
        required.add("exposure")
    brightness = float(visual.get("brightness", 0.0))
    contrast = float(visual.get("contrast", 1.0))
    saturation = float(visual.get("saturation", 1.0))
    gamma = float(visual.get("gamma", 1.0))
    if (brightness, contrast, saturation, gamma) != (0.0, 1.0, 1.0, 1.0):
        filters.append(
            "eq="
            f"brightness={brightness:.4f}:contrast={contrast:.4f}:"
            f"saturation={saturation:.4f}:gamma={gamma:.4f}"
        )
        required.add("eq")
    white_balance = visual.get("white_balance", {})
    red = float(white_balance.get("red_shift", 0.0))
    green = float(white_balance.get("green_shift", 0.0))
    blue = float(white_balance.get("blue_shift", 0.0))
    if (red, green, blue) != (0.0, 0.0, 0.0):
        filters.append(
            "colorbalance="
            f"rs={red:.4f}:gs={green:.4f}:bs={blue:.4f}:"
            f"rm={red:.4f}:gm={green:.4f}:bm={blue:.4f}:"
            f"rh={red:.4f}:gh={green:.4f}:bh={blue:.4f}:pl=1"
        )
        required.add("colorbalance")
    denoise = visual.get("denoise", {})
    if denoise.get("mode", "off") == "hqdn3d":
        filters.append(
            "hqdn3d="
            f"{float(denoise.get('luma_spatial', 1.5)):.4f}:"
            f"{float(denoise.get('chroma_spatial', 1.0)):.4f}:"
            f"{float(denoise.get('luma_temporal', 3.0)):.4f}:"
            f"{float(denoise.get('chroma_temporal', 2.0)):.4f}"
        )
        required.add("hqdn3d")
    sharpen = visual.get("sharpen", {})
    if sharpen.get("mode", "off") == "unsharp":
        amount = float(sharpen.get("amount", 0.4))
        filters.append(f"unsharp=5:5:{amount:.4f}:5:5:0.0")
        required.add("unsharp")
    reframe = visual.get("reframe", {})
    if reframe.get("mode", "off") == "crop":
        width_ratio = float(reframe.get("width_percent", 100.0)) / 100.0
        height_ratio = float(reframe.get("height_percent", 100.0)) / 100.0
        x_ratio = float(reframe.get("x_percent", 50.0)) / 100.0
        y_ratio = float(reframe.get("y_percent", 50.0)) / 100.0
        filters.extend(
            [
                (
                    f"crop=w=trunc(iw*{width_ratio:.6f}/2)*2:"
                    f"h=trunc(ih*{height_ratio:.6f}/2)*2:"
                    f"x=(iw-ow)*{x_ratio:.6f}:y=(ih-oh)*{y_ratio:.6f}"
                ),
                f"scale={width}:{height}:flags=lanczos",
                "setsar=1",
            ]
        )
        required.update({"crop", "scale", "setsar"})
    return filters, required


def _treatment_filter_graph(
    treatments: list[dict[str, Any]],
    realized_timeline: dict[str, Any],
    width: int,
    height: int,
    video_start_sec: float = 0.0,
    audio_start_sec: float = 0.0,
) -> tuple[list[str], str, str, bool, set[str]]:
    normalize_dialogue = _ensure_runtime_treatments_supported(treatments)
    _validate_runtime_timeline(treatments, realized_timeline)
    segments = realized_timeline["segments"]
    count = len(segments)
    stream_origin = min(video_start_sec, audio_start_sec)
    video_offset = video_start_sec - stream_origin
    audio_offset = audio_start_sec - stream_origin
    filters: list[str] = []
    required = {"trim", "atrim", "setpts", "asetpts", "tpad", "apad", "concat"}
    if count > 1:
        video_sources = [f"treatment_vsrc_{index}" for index in range(1, count + 1)]
        audio_sources = [f"treatment_asrc_{index}" for index in range(1, count + 1)]
        filters.append(
            f"[0:v]split={count}" + "".join(f"[{label}]" for label in video_sources)
        )
        filters.append(
            f"[0:a]asplit={count}" + "".join(f"[{label}]" for label in audio_sources)
        )
        required.update({"split", "asplit"})
    else:
        video_sources = ["0:v"]
        audio_sources = ["0:a"]

    concat_inputs: list[str] = []
    for index, (treatment, segment) in enumerate(zip(treatments, segments), start=1):
        start = float(segment["start_sec"])
        end = float(segment["end_sec"])
        duration = end - start
        video_trim_start = start + video_start_sec
        video_trim_end = end + video_start_sec
        audio_trim_start = start + audio_start_sec
        audio_trim_end = end + audio_start_sec
        video_label = f"treatment_video_{index}"
        audio_label = f"treatment_audio_{index}"
        visual_filters, visual_required = _visual_filter_chain(treatment, width, height)
        required.update(visual_required)
        video_chain = [
            (
                f"[{video_sources[index - 1]}]"
                f"trim=start={video_trim_start:.6f}:end={video_trim_end:.6f}"
            ),
            "setpts=PTS-STARTPTS",
            *visual_filters,
            f"tpad=stop_mode=clone:stop={TERMINAL_PAD_FRAMES}",
            f"trim=end={duration:.6f}",
        ]
        filters.append(",".join(video_chain) + f"[{video_label}]")

        audio = treatment.get("audio", {})
        muted = bool(audio.get("mute", False)) or not bool(
            audio.get("preserve_original", True)
        )
        gain_db = float(audio.get("gain_db", 0.0))
        audio_chain = [
            (
                f"[{audio_sources[index - 1]}]"
                f"atrim=start={audio_trim_start:.6f}:end={audio_trim_end:.6f}"
            ),
            "asetpts=PTS-STARTPTS",
        ]
        if muted:
            audio_chain.append("volume=0")
            required.add("volume")
        elif gain_db != 0.0:
            audio_chain.append(f"volume={gain_db:.4f}dB")
            required.add("volume")
        audio_chain.extend(
            [
                f"apad=pad_dur={duration:.6f}",
                f"atrim=end={duration:.6f}",
            ]
        )
        filters.append(",".join(audio_chain) + f"[{audio_label}]")
        concat_inputs.extend((f"[{video_label}]", f"[{audio_label}]"))

    filters.append(
        "".join(concat_inputs)
        + f"concat=n={count}:v=1:a=1[video_concat][audio_concat]"
    )
    filters.append(
        f"[video_concat]setpts=PTS+{video_offset:.6f}/TB,"
        f"tpad=stop_mode=clone:stop={TERMINAL_PAD_FRAMES},"
        f"trim=end={float(realized_timeline['duration_sec']):.6f}[video_treated]"
    )
    filters.append(
        f"[audio_concat]asetpts=PTS+{audio_offset:.6f}/TB,"
        f"apad=pad_dur={float(realized_timeline['duration_sec']):.6f},"
        f"atrim=end={float(realized_timeline['duration_sec']):.6f}[audio_treated]"
    )
    return filters, "video_treated", "audio_treated", normalize_dialogue, required


def stabilize_video(
    input_path: Path,
    output_path: Path,
    work_directory: Path,
    strength: float = 0.35,
    max_crop_percent: float = 8.0,
    executable: str = "ffmpeg",
) -> Path:
    if not 0 <= strength <= 1:
        raise ValueError("stabilization strength must be between 0 and 1")
    if not 0 <= max_crop_percent <= 15:
        raise ValueError("max_crop_percent must be between 0 and 15")
    if not input_path.is_file():
        raise FileNotFoundError(input_path)

    ffmpeg = find_ffmpeg(executable)
    require_filters(ffmpeg, {"vidstabdetect", "vidstabtransform"})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_directory.mkdir(parents=True, exist_ok=True)
    transforms = work_directory / f"{output_path.stem}.trf"
    shakiness = max(1, min(10, round(1 + strength * 9)))
    smoothing = max(5, round(5 + strength * 25))

    run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vf",
            f"format=yuv420p,vidstabdetect=shakiness={shakiness}:accuracy=15:result='{filter_path(transforms)}'",
            "-an",
            "-f",
            "null",
            "NUL",
        ]
    )
    run_command(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-vf",
            (
                f"vidstabtransform=input='{filter_path(transforms)}':"
                f"smoothing={smoothing}:optzoom=1:zoom={max_crop_percent},unsharp=5:5:0.6:3:3:0.3"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(output_path),
        ]
    )
    return output_path


def render_enhanced_video(
    project: Path,
    base_video: Path,
    enhancement_plan: dict[str, Any],
    output_path: Path,
    executable: str = "ffmpeg",
    realized_timeline: dict[str, Any] | None = None,
    video_preset: str = "medium",
    video_crf: int = 18,
) -> Path:
    if not base_video.is_file():
        raise FileNotFoundError(base_video)
    asset_issues = validate_enhancement_assets(project, enhancement_plan)
    asset_errors = [issue for issue in asset_issues if issue.get("severity") == "error"]
    if asset_errors:
        raise ValueError(
            "enhancement asset validation failed: "
            + json.dumps(asset_errors, ensure_ascii=False)
        )
    effect_section = enhancement_plan.get("illustration_motion", {})
    hyperframes_items = [
        item
        for item in effect_section.get("items", [])
        if isinstance(item, dict) and item.get("type") == "hyperframes"
    ]
    if hyperframes_items:
        expected_base_sha256 = effect_section.get("effect_evidence", {}).get(
            "base_media_sha256"
        )
        if _sha256_file(base_video) != expected_base_sha256:
            raise ValueError(
                "HyperFrames effects were approved against a different base media SHA-256"
            )
    non_finite_paths = find_non_finite_number_paths(enhancement_plan)
    if realized_timeline is not None:
        non_finite_paths.extend(
            find_non_finite_number_paths(realized_timeline, "$.realized_timeline")
        )
    if non_finite_paths:
        raise ValueError(
            "enhancement inputs contain non-finite numbers: "
            + ", ".join(non_finite_paths)
        )
    if video_preset not in VIDEO_PRESETS:
        raise ValueError(f"unsupported libx264 preset: {video_preset}")
    if not 0 <= video_crf <= 51:
        raise ValueError("video_crf must be between 0 and 51")
    ffmpeg = find_ffmpeg(executable)
    treatments = enhancement_plan.get("video_treatments", [])
    normalize_dialogue = True
    filters: list[str] = []
    video_label = "0:v"
    dialogue_source = "0:a"
    required_filters: set[str] = set()
    if treatments:
        normalize_dialogue = _ensure_runtime_treatments_supported(treatments)
    media: dict[str, Any] | None = None
    if realized_timeline is not None:
        expected_size = realized_timeline.get("base_size_bytes")
        expected_sha256 = realized_timeline.get("base_sha256")
        if treatments and (expected_size is None or expected_sha256 is None):
            raise ValueError(
                "per-segment rendering requires base_size_bytes and base_sha256"
            )
        if expected_size is not None and base_video.stat().st_size != int(expected_size):
            raise ValueError("realized timeline base media size does not match input")
        if (
            expected_sha256 is not None
            and _sha256_file(base_video) != str(expected_sha256).lower()
        ):
            raise ValueError("realized timeline base media SHA-256 does not match input")
        media = probe_media(ffmpeg, base_video)
        if not media["has_video"] or not media["has_audio"]:
            raise ValueError("base video must contain both video and audio streams")
        realized_duration = float(realized_timeline["duration_sec"])
        if abs(float(media["duration_sec"]) - realized_duration) > 0.15:
            raise ValueError(
                "realized timeline duration does not match the encoded base video"
            )
        (
            treatment_filters,
            video_label,
            dialogue_source,
            normalize_dialogue,
            treatment_required,
        ) = _treatment_filter_graph(
            treatments,
            realized_timeline,
            int(media["width"]),
            int(media["height"]),
            float(media["video_start_sec"]),
            float(media["audio_start_sec"]),
        )
        filters.extend(treatment_filters)
        required_filters.update(treatment_required)
    elif treatments_require_realized_timeline(enhancement_plan):
        raise ValueError("per-segment treatments require a realized timeline")

    if normalize_dialogue:
        required_filters.update({"loudnorm", "aresample"})
    else:
        required_filters.add("anull")
    music = enhancement_plan.get("music", {})
    music_tracks = music.get("tracks", [])
    if music_tracks and music.get("status") not in {"audition", "ready"}:
        raise ValueError("music tracks require music status 'audition' or 'ready'")
    ducking = music.get("ducking", {})
    ducking_enabled = bool(ducking.get("enabled", True))
    illustration_section = enhancement_plan.get("illustration_motion", {})
    overlay_items = illustration_section.get("items", [])
    if overlay_items and illustration_section.get("status") != "ready":
        raise ValueError("overlay items require illustration_motion status 'ready'")
    subtitle_section = enhancement_plan.get("subtitles", {})
    subtitle_cues = subtitle_section.get("cues", [])
    subtitle_status = subtitle_section.get("status")
    if subtitle_cues and subtitle_status not in {"review", "ready"}:
        raise ValueError("subtitle cues require subtitles status 'review' or 'ready'")
    if (
        subtitle_cues
        and subtitle_status == "ready"
        and subtitle_section.get("coverage", {}).get("status") != "verified"
    ):
        raise ValueError("ready subtitle cues require verified coverage")
    if subtitle_cues and subtitle_status == "ready" and any(
        cue.get("review_status") != "verified" for cue in subtitle_cues
    ):
        raise ValueError("ready subtitle cues require verified review_status")
    if (
        subtitle_cues
        and subtitle_status == "review"
        and subtitle_section.get("coverage", {}).get("status")
        not in {"pending", "verified"}
    ):
        raise ValueError("review subtitle cues require pending or verified coverage")
    if subtitle_cues and subtitle_status == "review" and any(
        cue.get("review_status") not in {"review_required", "verified"}
        for cue in subtitle_cues
    ):
        raise ValueError(
            "review subtitle cues require review_required or verified review_status"
        )
    overlay_ids = [str(item.get("id", "")) for item in overlay_items]
    if len(overlay_ids) != len(set(overlay_ids)):
        raise ValueError("overlay item IDs must be unique")
    supported_overlay_types = {
        "illustration",
        "sticker",
        "callout",
        "map",
        "title_card",
        "hyperframes",
    }
    if any(str(item.get("type", "")) not in supported_overlay_types for item in overlay_items):
        raise ValueError("overlay item type is unsupported")
    if illustration_section.get("subtitle_safe_zone") and subtitle_cues:
        default_position = str(
            subtitle_section.get("style", {}).get("position", "bottom_center")
        )
        subtitle_positions = {
            str(cue.get("position", default_position)) for cue in subtitle_cues
        }
        for item in overlay_items:
            anchor = str(item.get("anchor", ""))
            if (
                anchor.startswith("bottom_")
                and "bottom_center" in subtitle_positions
            ) or (
                anchor.startswith("top_") and "top_center" in subtitle_positions
            ):
                raise ValueError(
                    "overlay anchor violates the reserved subtitle safe zone"
                )
    if music_tracks:
        required_filters.update(
            {
                "atrim",
                "asetpts",
                "volume",
                "adelay",
                "amix",
                "loudnorm",
                "aresample",
            }
        )
        if any(
            float(track.get("fade_in_sec", 0.0)) > 0
            or float(track.get("fade_out_sec", 0.0)) > 0
            for track in music_tracks
        ):
            required_filters.add("afade")
    if music_tracks and ducking_enabled:
        required_filters.update({"sidechaincompress", "asplit"})
    if not music_tracks:
        required_filters.add("anull")
    if overlay_items:
        required_filters.update({"overlay", "scale", "format", "setpts"})
        for item in overlay_items:
            animation = str(item.get("animation", "none"))
            if animation not in SUPPORTED_OVERLAY_ANIMATIONS:
                raise ValueError(f"unsupported overlay animation: {animation}")
            if animation == "fade":
                required_filters.add("fade")
    if subtitle_cues:
        required_filters.add("subtitles")
    required_filters.update({"setsar", "format", "alimiter"})
    require_filters(ffmpeg, required_filters)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(base_video)]
    input_index = 1
    overlay_inputs: list[tuple[int, dict[str, Any]]] = []
    for item in overlay_items:
        source = _resolve_overlay_asset(project, item)
        if item.get("type") == "hyperframes":
            command.extend(["-i", str(source)])
        else:
            command.extend(["-loop", "1", "-framerate", "30", "-i", str(source)])
        overlay_inputs.append((input_index, item))
        input_index += 1

    music_inputs: list[tuple[int, dict[str, Any]]] = []
    for track in music_tracks:
        source = _resolve_project_asset(project, str(track["source"]))
        command.extend(["-stream_loop", "-1", "-i", str(source)])
        music_inputs.append((input_index, track))
        input_index += 1

    for sequence, (index, item) in enumerate(overlay_inputs, start=1):
        if media is None:
            media = probe_media(ffmpeg, base_video)
        if item.get("type") == "hyperframes":
            overlay_filters, next_video, overlay_required = (
                build_hyperframes_overlay_filters(
                    index,
                    sequence,
                    video_label,
                    item,
                )
            )
        else:
            overlay_filters, next_video, overlay_required = build_overlay_filters(
                index,
                sequence,
                video_label,
                item,
                int(media["width"]),
            )
        filters.extend(overlay_filters)
        required_filters.update(overlay_required)
        video_label = next_video

    if normalize_dialogue:
        filters.append(
            f"[{dialogue_source}]loudnorm=I=-16:LRA=11:TP=-1.5,"
            "aresample=48000[dialogue_normalized]"
        )
    else:
        filters.append(f"[{dialogue_source}]anull[dialogue_normalized]")
    if music_inputs:
        if ducking_enabled:
            filters.append("[dialogue_normalized]asplit=2[dialogue_sc][dialogue_mix]")
        music_labels = []
        for sequence, (index, track) in enumerate(music_inputs, start=1):
            label = f"music_{sequence}"
            filters.append(_music_filter_chain(index, track, label))
            music_labels.append(f"[{label}]")
        filters.append(
            "".join(music_labels)
            + f"amix=inputs={len(music_labels)}:normalize=0:duration=longest[music_bed]"
        )
        if ducking_enabled:
            filters.append(
                "[music_bed][dialogue_sc]sidechaincompress="
                f"threshold={float(ducking.get('threshold', DEFAULT_MUSIC_DUCKING['threshold']))}:"
                f"ratio={float(ducking.get('ratio', DEFAULT_MUSIC_DUCKING['ratio']))}:"
                f"attack={int(ducking.get('attack_ms', DEFAULT_MUSIC_DUCKING['attack_ms']))}:"
                f"release={int(ducking.get('release_ms', DEFAULT_MUSIC_DUCKING['release_ms']))}"
                "[ducked_music]"
            )
            filters.append(
                "[dialogue_mix][ducked_music]"
                "amix=inputs=2:normalize=0:duration=first[audio_pre_master]"
            )
        else:
            filters.append(
                "[dialogue_normalized][music_bed]"
                "amix=inputs=2:normalize=0:duration=first[audio_pre_master]"
            )
        filters.append(
            "[audio_pre_master]loudnorm=I=-16:LRA=11:TP=-1.5,"
            "aresample=48000[audio_mixed]"
        )
    else:
        filters.append("[dialogue_normalized]anull[audio_mixed]")
    filters.append(
        "[audio_mixed]alimiter=limit=0.841395:attack=5:release=50:"
        "level=false:latency=true[audio_final]"
    )

    with tempfile.TemporaryDirectory(prefix="firered-enhancement-") as temporary:
        if subtitle_cues:
            if media is None:
                media = probe_media(ffmpeg, base_video)
            subtitle_file = Path(temporary) / "subtitles.ass"
            subtitle_style = subtitle_section.get("style", {})
            width = int(media["width"])
            height = int(media["height"])
            subtitle_contract = build_subtitle_render_contract(
                project,
                subtitle_style,
                canvas_width=width,
                canvas_height=height,
            )
            write_contract_ass(
                subtitle_cues,
                subtitle_contract,
                subtitle_file,
                writer=write_ass_subtitles,
            )
            next_video = "video_subtitled"
            subtitle_filter = subtitle_filter_expression(
                subtitle_file,
                subtitle_contract,
            )
            filters.append(f"[{video_label}]{subtitle_filter}[{next_video}]")
            video_label = next_video

        filters.append(
            f"[{video_label}]setsar=1,format=yuvj420p[video_final]"
        )
        filter_script = Path(temporary) / "enhancement.filters.txt"
        filter_script.write_text(";\n".join(filters) + "\n", encoding="utf-8")
        command.extend(
            [
                "-filter_complex_script",
                str(filter_script),
                "-map",
                "[video_final]",
                "-map",
                "[audio_final]",
                "-c:v",
                "libx264",
                "-preset",
                video_preset,
                "-crf",
                str(video_crf),
                "-pix_fmt",
                "yuvj420p",
                "-color_range",
                "pc",
                "-colorspace",
                "bt709",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ]
        )
        if realized_timeline is not None:
            command.extend(["-t", f"{float(realized_timeline['duration_sec']):.6f}"])
        else:
            command.append("-shortest")
        command.append(str(output_path))
        run_command(command)
    return output_path


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)
