from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from .ffmpeg import filter_path, find_ffmpeg, require_filters, run_command
from .subtitles import write_ass_subtitles


def _gain_to_linear(gain_db: float) -> float:
    return math.pow(10.0, gain_db / 20.0)


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
) -> Path:
    if not base_video.is_file():
        raise FileNotFoundError(base_video)
    ffmpeg = find_ffmpeg(executable)
    required_filters = {"loudnorm"}
    music_tracks = enhancement_plan.get("music", {}).get("tracks", [])
    overlay_items = enhancement_plan.get("illustration_motion", {}).get("items", [])
    subtitle_cues = enhancement_plan.get("subtitles", {}).get("cues", [])
    if music_tracks:
        required_filters.add("sidechaincompress")
    if overlay_items:
        required_filters.add("overlay")
    if subtitle_cues:
        required_filters.add("subtitles")
    require_filters(ffmpeg, required_filters)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(base_video)]
    input_index = 1
    overlay_inputs: list[tuple[int, dict[str, Any]]] = []
    for item in overlay_items:
        source = (project / item["source"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        command.extend(["-loop", "1", "-i", str(source)])
        overlay_inputs.append((input_index, item))
        input_index += 1

    music_inputs: list[tuple[int, dict[str, Any]]] = []
    for track in music_tracks:
        source = (project / track["source"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        command.extend(["-stream_loop", "-1", "-i", str(source)])
        music_inputs.append((input_index, track))
        input_index += 1

    filters: list[str] = []
    video_label = "0:v"
    for sequence, (index, item) in enumerate(overlay_inputs, start=1):
        scaled = f"overlay_scaled_{sequence}"
        next_video = f"video_overlay_{sequence}"
        scale_percent = float(item.get("scale_percent", 22.0)) / 100.0
        x_expression, y_expression = _anchor_expression(item["anchor"])
        filters.append(f"[{index}:v]scale=iw*{scale_percent}:ih*{scale_percent}[{scaled}]")
        filters.append(
            f"[{video_label}][{scaled}]overlay=x={x_expression}:y={y_expression}:"
            f"enable='between(t,{float(item['start_sec'])},{float(item['end_sec'])})'"
            f"[{next_video}]"
        )
        video_label = next_video

    subtitle_file: Path | None = None
    if subtitle_cues:
        subtitle_file = output_path.with_suffix(".ass")
        write_ass_subtitles(subtitle_cues, subtitle_file)
        next_video = "video_subtitled"
        fonts_directory = project / "assets" / "fonts"
        subtitle_filter = f"subtitles=filename='{filter_path(subtitle_file)}'"
        if fonts_directory.is_dir():
            subtitle_filter += f":fontsdir='{filter_path(fonts_directory)}'"
        filters.append(f"[{video_label}]{subtitle_filter}[{next_video}]")
        video_label = next_video

    audio_label = "audio_final"
    filters.append(
        "[0:a]loudnorm=I=-16:LRA=11:TP=-1.5,aresample=48000[dialogue_normalized]"
    )
    if music_inputs:
        filters.append("[dialogue_normalized]asplit=2[dialogue_sc][dialogue_mix]")
        music_labels = []
        for sequence, (index, track) in enumerate(music_inputs, start=1):
            label = f"music_{sequence}"
            start = float(track["start_sec"])
            end = float(track["end_sec"])
            duration = end - start
            delay_ms = round(start * 1000)
            gain = _gain_to_linear(float(track["gain_db"]))
            filters.append(
                f"[{index}:a]atrim=0:{duration},asetpts=PTS-STARTPTS,"
                f"volume={gain},adelay={delay_ms}|{delay_ms}[{label}]"
            )
            music_labels.append(f"[{label}]")
        filters.append(
            "".join(music_labels)
            + f"amix=inputs={len(music_labels)}:normalize=0:duration=longest[music_bed]"
        )
        ducking = enhancement_plan["music"]["ducking"]
        filters.append(
            "[music_bed][dialogue_sc]sidechaincompress="
            f"threshold=0.04:ratio=8:attack={int(ducking['attack_ms'])}:"
            f"release={int(ducking['release_ms'])}[ducked_music]"
        )
        filters.append("[dialogue_mix][ducked_music]amix=inputs=2:normalize=0:duration=first[audio_final]")
    else:
        filters.append("[dialogue_normalized]anull[audio_final]")

    filter_script = output_path.with_suffix(".filters.txt")
    filter_script.write_text(";\n".join(filters) + "\n", encoding="utf-8")
    command.extend(
        [
            "-filter_complex_script",
            str(filter_script),
            "-map",
            f"[{video_label}]" if video_label != "0:v" else "0:v",
            "-map",
            f"[{audio_label}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    run_command(command)
    return output_path


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)
