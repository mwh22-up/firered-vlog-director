from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class FFmpegError(RuntimeError):
    pass


FILTER_NAME = re.compile(r"^\s*[TSC.]{2,3}\s+([A-Za-z0-9_]+)\s", re.MULTILINE)
MEDIA_DURATION = re.compile(
    r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
)
VIDEO_STREAM = re.compile(r"^\s*Stream #.*Video:.*$", re.MULTILINE)
AUDIO_STREAM = re.compile(r"^\s*Stream #.*Audio:.*$", re.MULTILINE)
VIDEO_SIZE = re.compile(r"(?<![0-9])([1-9][0-9]{1,4})x([1-9][0-9]{1,4})(?![0-9])")
VIDEO_FIRST_PTS = re.compile(
    r"Parsed_showinfo.*?\bn:\s*0\b.*?\bpts_time:([-+0-9.eE]+)",
)
AUDIO_FIRST_PTS = re.compile(
    r"Parsed_ashowinfo.*?\bn:0\b.*?\bpts_time:([-+0-9.eE]+)",
)


def find_ffmpeg(executable: str = "ffmpeg") -> str:
    configured_home = os.environ.get("VLOG_FFMPEG_HOME")
    if configured_home and Path(executable).name == executable:
        filename = executable if Path(executable).suffix else f"{executable}.exe"
        configured = Path(configured_home) / filename
        if configured.is_file():
            return str(configured.resolve())
    resolved = shutil.which(executable)
    if resolved is None:
        raise FileNotFoundError(f"FFmpeg executable was not found: {executable}")
    return resolved


def run_command(command: Sequence[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise FFmpegError(f"Command failed with exit code {completed.returncode}: {detail}")


def require_filters(executable: str, required: set[str]) -> None:
    completed = subprocess.run(
        [find_ffmpeg(executable), "-hide_banner", "-filters"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise FFmpegError("Unable to inspect FFmpeg filters.")
    available = set(FILTER_NAME.findall(completed.stdout))
    missing = sorted(required - available)
    if missing:
        raise FFmpegError("FFmpeg is missing required filters: " + ", ".join(missing))


def probe_media(executable: str, media: Path) -> dict[str, object]:
    """Inspect basic media geometry without requiring a separate ffprobe binary."""
    completed = subprocess.run(
        [
            find_ffmpeg(executable),
            "-hide_banner",
            "-i",
            str(media),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-frames:v",
            "1",
            "-frames:a",
            "1",
            "-vf",
            "showinfo",
            "-af",
            "ashowinfo",
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
    output = completed.stderr + "\n" + completed.stdout
    if completed.returncode != 0:
        raise FFmpegError(output.strip() or "Unable to inspect media.")
    duration_match = MEDIA_DURATION.search(output)
    video_match = VIDEO_STREAM.search(output)
    audio_match = AUDIO_STREAM.search(output)
    size_match = VIDEO_SIZE.search(video_match.group(0)) if video_match else None
    video_pts_match = VIDEO_FIRST_PTS.search(output)
    audio_pts_match = AUDIO_FIRST_PTS.search(output)
    if (
        duration_match is None
        or size_match is None
        or video_pts_match is None
        or audio_pts_match is None
    ):
        raise FFmpegError("Unable to determine media duration, geometry, or stream starts.")
    hours, minutes, seconds = duration_match.groups()
    return {
        "duration_sec": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        "width": int(size_match.group(1)),
        "height": int(size_match.group(2)),
        "has_video": video_match is not None,
        "has_audio": audio_match is not None,
        "video_start_sec": float(video_pts_match.group(1)),
        "audio_start_sec": float(audio_pts_match.group(1)),
    }


def filter_path(path: Path) -> str:
    normalized = path.resolve().as_posix()
    return normalized.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
