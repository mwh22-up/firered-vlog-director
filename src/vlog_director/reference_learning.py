from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

from .asr import load_transcript, transcribe_media
from .event_analysis import group_shots_into_events
from .media_features import (
    detect_scene_times,
    probe_media,
    sample_audio_features,
    sample_visual_features,
)
from .shot_analysis import build_shots, summarize_patterns


def analyze_reference(
    media_path: Path,
    *,
    source_id: str,
    source_url: str,
    work_directory: Path,
    transcript_path: Path | None = None,
    asr_provider: str = "auto",
    asr_model: str = "base",
    language: str | None = "zh",
    scene_threshold: float = 0.22,
    visual_fps: float = 2.0,
    audio_window_sec: float = 0.5,
) -> dict[str, Any]:
    media = probe_media(media_path)
    transcript = (
        load_transcript(transcript_path)
        if transcript_path
        else transcribe_media(
            media_path,
            provider=asr_provider,
            model_name=asr_model,
            language=language,
        )
    )
    speech_segments = speech_intervals(transcript)
    scene_times = detect_scene_times(
        media_path,
        work_directory,
        threshold=scene_threshold,
    )
    visual_samples = sample_visual_features(media_path, fps=visual_fps)
    audio_samples = sample_audio_features(
        media_path,
        window_sec=audio_window_sec,
    )
    audio_segments = build_audio_segments(
        audio_samples,
        speech_segments,
        audio_window_sec,
    )
    shots = build_shots(
        scene_times,
        media["duration_sec"],
        visual_samples,
        audio_samples,
        {"segments": speech_segments},
    )
    events = group_shots_into_events(shots)
    return {
        "schema_version": "1.0",
        "source": {
            "source_id": source_id,
            "url": source_url,
            "media_path": str(media_path.resolve()),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "scene_threshold": scene_threshold,
            "visual_fps": visual_fps,
            "audio_window_sec": audio_window_sec,
            "asr_provider": asr_provider,
            "asr_model": asr_model,
            "language": language,
        },
        "media": media_summary(media, shots, audio_samples, audio_segments),
        "transcription": transcript,
        "audio_segments": audio_segments,
        "shots": shots,
        "events": events,
        "learning_summary": summarize_patterns(shots, events),
    }


def media_summary(
    media: dict[str, Any],
    shots: list[dict[str, Any]],
    audio_samples: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    durations = sorted(shot["duration_sec"] for shot in shots)
    silent = [
        sample
        for sample in audio_samples
        if sample["rms"] < 0.012
    ]
    opening = [
        shot
        for shot in shots
        if shot["start_sec"] < 15
    ]
    return {
        **media,
        "shot_count": len(shots),
        "median_shot_duration_sec": round(median(durations), 3),
        "p75_shot_duration_sec": round(percentile(durations, 0.75), 3),
        "shots_under_1_sec": sum(value < 1 for value in durations),
        "shots_over_5_sec": sum(value > 5 for value in durations),
        "silent_ratio": round(len(silent) / max(1, len(audio_samples)), 4),
        "audio_kind_ratios": audio_kind_ratios(
            audio_segments,
            media["duration_sec"],
        ),
        "opening_15_sec": {
            "shot_count": len(opening),
            "average_shot_duration_sec": round(
                mean(shot["duration_sec"] for shot in opening),
                3,
            )
            if opening
            else 0,
        },
    }


def build_audio_segments(
    samples: list[dict[str, Any]],
    speech_segments: list[dict[str, Any]],
    window_sec: float,
) -> list[dict[str, Any]]:
    classified = []
    for sample in samples:
        start_sec = float(sample["time_sec"])
        end_sec = start_sec + window_sec
        if any(
            max(
                0.0,
                min(end_sec, float(segment["end_sec"]))
                - max(start_sec, float(segment["start_sec"])),
            )
            > window_sec * 0.25
            for segment in speech_segments
        ):
            kind = "speech"
        elif sample["rms"] < 0.012:
            kind = "silence"
        elif (
            sample["spectral_flatness"] < 0.2
            and sample["spectral_centroid_hz"] < 4000
        ):
            kind = "music_likely"
        else:
            kind = "ambient_likely"
        classified.append({**sample, "kind": kind})

    classified = smooth_audio_kinds(classified)
    segments = []
    current = []
    for sample in classified:
        if current and sample["kind"] != current[-1]["kind"]:
            segments.append(audio_segment_summary(current, window_sec))
            current = []
        current.append(sample)
    if current:
        segments.append(audio_segment_summary(current, window_sec))
    return segments


def smooth_audio_kinds(
    samples: list[dict[str, Any]],
    *,
    radius: int = 2,
) -> list[dict[str, Any]]:
    smoothed = [dict(sample) for sample in samples]
    for index, sample in enumerate(samples):
        if sample["kind"] in {"speech", "silence"}:
            continue
        neighbors = samples[
            max(0, index - radius) : min(len(samples), index + radius + 1)
        ]
        music_votes = sum(
            neighbor["kind"] == "music_likely"
            for neighbor in neighbors
        )
        ambient_votes = sum(
            neighbor["kind"] == "ambient_likely"
            for neighbor in neighbors
        )
        smoothed[index]["kind"] = (
            "music_likely"
            if music_votes > ambient_votes
            else "ambient_likely"
        )
    return smoothed


def audio_segment_summary(
    samples: list[dict[str, Any]],
    window_sec: float,
) -> dict[str, Any]:
    return {
        "start_sec": samples[0]["time_sec"],
        "end_sec": round(samples[-1]["time_sec"] + window_sec, 3),
        "kind": samples[0]["kind"],
        "average_rms": round(mean(item["rms"] for item in samples), 6),
        "peak": round(max(item["peak"] for item in samples), 6),
    }


def audio_kind_ratios(
    segments: list[dict[str, Any]],
    duration_sec: float,
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for segment in segments:
        totals[segment["kind"]] = totals.get(segment["kind"], 0.0) + (
            segment["end_sec"] - segment["start_sec"]
        )
    return {
        kind: round(value / max(duration_sec, 0.001), 4)
        for kind, value in sorted(totals.items())
    }


def speech_intervals(
    transcript: dict[str, Any],
    *,
    merge_gap_sec: float = 0.6,
) -> list[dict[str, float]]:
    words = [
        {
            "start_sec": float(word["start_sec"]),
            "end_sec": float(word["end_sec"]),
        }
        for word in transcript.get("words", [])
        if word.get("start_sec") is not None
        and word.get("end_sec") is not None
    ]
    source = words or [
        {
            "start_sec": float(segment["start_sec"]),
            "end_sec": float(segment["end_sec"]),
        }
        for segment in transcript.get("segments", [])
    ]
    if not source:
        return []
    merged = [source[0]]
    for interval in source[1:]:
        previous = merged[-1]
        if interval["start_sec"] - previous["end_sec"] <= merge_gap_sec:
            previous["end_sec"] = max(
                previous["end_sec"],
                interval["end_sec"],
            )
        else:
            merged.append(interval)
    return merged


def write_analysis(analysis: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_portable_analysis(
    analysis: dict[str, Any],
    output_path: Path,
) -> None:
    portable = deepcopy(analysis)
    portable["source"].pop("media_path", None)
    transcript = portable["transcription"]
    portable["transcription"] = {
        "status": transcript["status"],
        "provider": transcript["provider"],
        "model": transcript.get("model"),
        "language": transcript.get("language"),
        "language_probability": transcript.get("language_probability"),
        "duration_sec": transcript.get("duration_sec"),
        "segment_count": len(transcript.get("segments", [])),
        "word_count": len(transcript.get("words", [])),
        "segments": [],
        "words": [],
        "portable_redaction": "完整逐字稿仅保存在本地分析目录。"
    }
    write_analysis(portable, output_path)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(len(values) * fraction)))
    return values[index]
