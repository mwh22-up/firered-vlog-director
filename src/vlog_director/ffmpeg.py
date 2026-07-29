from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class FFmpegError(RuntimeError):
    pass


def find_ffmpeg(executable: str = "ffmpeg") -> str:
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
    missing = sorted(filter_name for filter_name in required if filter_name not in completed.stdout)
    if missing:
        raise FFmpegError("FFmpeg is missing required filters: " + ", ".join(missing))


def filter_path(path: Path) -> str:
    normalized = path.resolve().as_posix()
    return normalized.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
