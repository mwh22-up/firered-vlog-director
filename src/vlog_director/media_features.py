from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .ffmpeg import FFmpegError, filter_path, find_ffmpeg, run_command


def probe_media(media_path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise FileNotFoundError("FFprobe executable was not found")
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=index,codec_type,width,height,r_frame_rate",
            "-of",
            "json",
            str(media_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise FFmpegError(completed.stderr.strip() or "FFprobe failed")
    payload = json.loads(completed.stdout)
    return {
        "duration_sec": round(float(payload["format"]["duration"]), 3),
        "size_bytes": int(payload["format"].get("size", 0)),
        "streams": payload.get("streams", []),
    }


def detect_scene_times(
    media_path: Path,
    work_directory: Path,
    *,
    threshold: float = 0.22,
) -> list[float]:
    work_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = work_directory / "scene-metadata.txt"
    scene_filter = (
        f"select='gt(scene,{threshold})',"
        f"metadata=print:file='{filter_path(metadata_path)}'"
    )
    run_command(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(media_path),
            "-vf",
            scene_filter,
            "-an",
            "-f",
            "null",
            os.devnull,
        ]
    )
    if not metadata_path.exists():
        return []
    pattern = re.compile(r"pts_time:([0-9.]+)")
    times = []
    for line in metadata_path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            times.append(float(match.group(1)))
    return sorted(set(times))


def sample_visual_features(
    media_path: Path,
    *,
    fps: float = 2.0,
    width: int = 96,
    height: int = 54,
) -> list[dict[str, Any]]:
    command = [
        find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vf",
        (
            f"fps={fps},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            "format=gray"
        ),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if process.stdout is None:
        raise FFmpegError("Unable to read FFmpeg visual output")

    frame_size = width * height
    samples: list[dict[str, Any]] = []
    previous: np.ndarray[Any, Any] | None = None
    frame_index = 0
    while True:
        raw = process.stdout.read(frame_size)
        if len(raw) < frame_size:
            break
        frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width))
        normalized = frame.astype(np.float32) / 255.0
        horizontal = np.abs(np.diff(normalized, axis=1)).mean()
        vertical = np.abs(np.diff(normalized, axis=0)).mean()
        motion = (
            float(np.abs(normalized - previous).mean())
            if previous is not None
            else 0.0
        )
        samples.append(
            {
                "time_sec": round(frame_index / fps, 3),
                "brightness": round(float(normalized.mean()), 5),
                "contrast": round(float(normalized.std()), 5),
                "sharpness": round(float(horizontal + vertical), 5),
                "motion": round(motion, 5),
                "visual_hash": _visual_hash(frame),
            }
        )
        previous = normalized
        frame_index += 1

    return_code = process.wait()
    if return_code != 0:
        raise FFmpegError(f"Visual feature extraction failed: {return_code}")
    return samples


def sample_audio_features(
    media_path: Path,
    *,
    sample_rate: int = 16000,
    window_sec: float = 0.5,
) -> list[dict[str, Any]]:
    command = [
        find_ffmpeg(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if process.stdout is None:
        raise FFmpegError("Unable to read FFmpeg audio output")

    samples_per_window = max(1, int(sample_rate * window_sec))
    bytes_per_window = samples_per_window * 2
    hann = np.hanning(samples_per_window).astype(np.float32)
    frequencies = np.fft.rfftfreq(samples_per_window, 1.0 / sample_rate)
    features: list[dict[str, Any]] = []
    window_index = 0

    while True:
        raw = process.stdout.read(bytes_per_window)
        if not raw:
            break
        pcm = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if pcm.size < samples_per_window:
            pcm = np.pad(pcm, (0, samples_per_window - pcm.size))
        rms = float(np.sqrt(np.mean(np.square(pcm))))
        peak = float(np.max(np.abs(pcm)))
        zero_crossing = float(np.mean(np.diff(np.signbit(pcm)) != 0))
        spectrum = np.abs(np.fft.rfft(pcm * hann))
        spectrum_sum = float(spectrum.sum())
        centroid = (
            float(np.dot(frequencies, spectrum) / spectrum_sum)
            if spectrum_sum > 0
            else 0.0
        )
        positive = spectrum[spectrum > 1e-9]
        flatness = (
            float(math.exp(np.log(positive).mean()) / positive.mean())
            if positive.size
            else 0.0
        )
        features.append(
            {
                "time_sec": round(window_index * window_sec, 3),
                "rms": round(rms, 6),
                "peak": round(peak, 6),
                "zero_crossing": round(zero_crossing, 6),
                "spectral_centroid_hz": round(centroid, 2),
                "spectral_flatness": round(flatness, 6),
            }
        )
        window_index += 1

    return_code = process.wait()
    if return_code != 0:
        raise FFmpegError(f"Audio feature extraction failed: {return_code}")
    return features


def _visual_hash(frame: np.ndarray[Any, Any]) -> str:
    height, width = frame.shape
    cropped_height = height - (height % 9)
    cropped_width = width - (width % 16)
    cropped = frame[:cropped_height, :cropped_width]
    blocks = cropped.reshape(
        9,
        cropped_height // 9,
        16,
        cropped_width // 16,
    ).mean(axis=(1, 3))
    bits = blocks >= np.median(blocks)
    value = 0
    for bit in bits.flat:
        value = (value << 1) | int(bit)
    return f"{value:036x}"
