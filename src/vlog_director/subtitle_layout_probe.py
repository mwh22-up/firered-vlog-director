from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .ffmpeg import FILTER_NAME, FFmpegError, filter_path, find_ffmpeg


LAYOUT_QA_SCHEMA_VERSION = "1.0"
LAYOUT_PROBE_VERSION = "libass-rgb24-bbox-v1"
MEASUREMENT_METHOD = "ffmpeg-libass-rgb24-control-difference-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FONT_EXTENSIONS = {".otf", ".ttc", ".ttf"}
_FONTSELECT = re.compile(
    r"fontselect:\s*\((?P<requested>.*?),\s*-?\d+,\s*-?\d+\)\s*->\s*(?P<resolved>.+)$",
    re.IGNORECASE,
)
_FONT_SIZE_OVERRIDE = re.compile(r"^\{\\fs(?P<size>[1-9][0-9]*)\}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _portable_resolved_face(value: str) -> str:
    value = value.strip()
    if not value:
        return "unknown"
    parts = [part.strip() for part in value.split(",")]
    sanitized: list[str] = []
    for part in parts:
        if "/" in part or "\\" in part:
            part = re.split(r"[/\\]", part)[-1]
        sanitized.append(part)
    return ", ".join(sanitized)


def _normalized_font_name(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def font_directory_identity(directory: Path | None) -> dict[str, Any]:
    """Return a portable content identity for the font files visible to libass."""

    if directory is None:
        return {"present": False, "sha256": None, "file_count": 0, "files": []}
    resolved = Path(directory).resolve()
    if not resolved.is_dir():
        return {"present": False, "sha256": None, "file_count": 0, "files": []}
    files: list[dict[str, Any]] = []
    for path in sorted(
        (
            item
            for item in resolved.rglob("*")
            if item.is_file() and item.suffix.casefold() in _FONT_EXTENSIONS
        ),
        key=lambda item: item.relative_to(resolved).as_posix().casefold(),
    ):
        files.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "present": True,
        "sha256": _sha256_bytes(_canonical_bytes(files)),
        "file_count": len(files),
        "files": files,
    }


@lru_cache(maxsize=8)
def _inspect_ffmpeg_identity_cached(
    resolved_executable: str,
    executable_size: int,
    executable_mtime_ns: int,
) -> dict[str, Any]:
    del executable_mtime_ns
    executable_path = Path(resolved_executable)
    version = subprocess.run(
        [resolved_executable, "-hide_banner", "-version"],
        check=False,
        capture_output=True,
    )
    if version.returncode != 0:
        raise FFmpegError("Unable to inspect the FFmpeg version.")
    version_output = version.stdout.decode("utf-8", "replace")
    version_lines = version_output.splitlines()
    version_line = version_lines[0].strip() if version_lines else ""
    configuration_line = next(
        (line.strip() for line in version_lines if line.startswith("configuration:")),
        "",
    )
    filters = subprocess.run(
        [resolved_executable, "-hide_banner", "-filters"],
        check=False,
        capture_output=True,
    )
    if filters.returncode != 0:
        raise FFmpegError("Unable to inspect FFmpeg filters.")
    filters_output = filters.stdout.decode("utf-8", "replace")
    available = set(FILTER_NAME.findall(filters_output))
    return {
        "executable_name": executable_path.name,
        "executable_size_bytes": executable_size,
        "executable_sha256": _sha256_file(executable_path),
        "version_line": version_line,
        "configuration_sha256": _sha256_bytes(configuration_line.encode("utf-8")),
        "filters_sha256": _sha256_bytes(filters_output.encode("utf-8")),
        "subtitles_filter_available": "subtitles" in available,
        "libass_enabled": "--enable-libass" in configuration_line
        or "subtitles" in available,
    }


def inspect_ffmpeg_identity(executable: str = "ffmpeg") -> dict[str, Any]:
    resolved = Path(find_ffmpeg(executable)).resolve()
    stat = resolved.stat()
    return dict(
        _inspect_ffmpeg_identity_cached(
            str(resolved),
            stat.st_size,
            stat.st_mtime_ns,
        )
    )


def build_layout_cache_key(
    *,
    text: str,
    style: dict[str, Any],
    canvas: dict[str, int],
    font_directory: dict[str, Any],
    ffmpeg: dict[str, Any],
    probe_version: str = LAYOUT_PROBE_VERSION,
    ass_sha256: str | None = None,
) -> str:
    """Build a deterministic key for actual rendered layout, never path metadata."""

    payload: dict[str, Any] = {
        "probe_version": probe_version,
        "text": text,
        "style": style,
        "canvas": canvas,
        "font_directory": font_directory,
        "ffmpeg": ffmpeg,
    }
    if ass_sha256 is not None:
        payload["ass_sha256"] = ass_sha256
    return _sha256_bytes(_canonical_bytes(payload))


def _positive_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _finite_number(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number")
    return result


def _validate_sha256(value: str | None, field: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _safe_area(
    width: int,
    height: int,
    style: dict[str, Any],
) -> dict[str, int]:
    safe_margin_percent = _finite_number(
        style.get("safe_margin_percent", 8.0),
        "style.safe_margin_percent",
    )
    if not 0 <= safe_margin_percent <= 20:
        raise ValueError("style.safe_margin_percent must be between 0 and 20")
    margin_v = style.get("margin_v", 72)
    if not isinstance(margin_v, int) or isinstance(margin_v, bool) or margin_v < 0:
        raise ValueError("style.margin_v must be a non-negative integer")
    horizontal = round(width * safe_margin_percent / 100.0)
    vertical = max(margin_v, round(height * safe_margin_percent / 100.0))
    if width - 2 * horizontal <= 0 or height - 2 * vertical <= 0:
        raise ValueError("subtitle safe area leaves no usable canvas")
    return {
        "x": horizontal,
        "y": vertical,
        "width": width - 2 * horizontal,
        "height": height - 2 * vertical,
    }


def _subtitle_filter(ass_path: Path, fonts_directory: Path | None) -> str:
    result = f"subtitles=filename='{filter_path(ass_path)}'"
    if fonts_directory is not None and fonts_directory.is_dir():
        result += f":fontsdir='{filter_path(fonts_directory)}'"
    return result


def _run_rgb_frame(
    executable: str,
    *,
    width: int,
    height: int,
    video_filter: str,
    loglevel: str,
) -> tuple[bytes, str]:
    completed = subprocess.run(
        [
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            loglevel,
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x19A65B:s={width}x{height}:r=25:d=0.04",
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            "-an",
            "-sn",
            "-threads",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise FFmpegError(
            "FFmpeg could not render a subtitle layout probe frame "
            f"(exit code {completed.returncode})."
        )
    expected = width * height * 3
    if len(completed.stdout) != expected:
        raise FFmpegError(
            f"FFmpeg returned {len(completed.stdout)} frame bytes; expected {expected}."
        )
    return completed.stdout, completed.stderr.decode("utf-8", "replace")


def _measure_bbox(
    control: bytes,
    rendered: bytes,
    width: int,
    height: int,
) -> tuple[dict[str, int] | None, int]:
    if len(control) != len(rendered) or len(rendered) != width * height * 3:
        raise ValueError("control and rendered frames must have identical RGB geometry")
    minimum_x = width
    minimum_y = height
    maximum_x = -1
    maximum_y = -1
    pixel_count = 0
    control_view = memoryview(control)
    rendered_view = memoryview(rendered)
    for offset in range(0, len(rendered), 3):
        if (
            abs(rendered_view[offset] - control_view[offset]) <= 2
            and abs(rendered_view[offset + 1] - control_view[offset + 1]) <= 2
            and abs(rendered_view[offset + 2] - control_view[offset + 2]) <= 2
        ):
            continue
        pixel = offset // 3
        y, x = divmod(pixel, width)
        minimum_x = min(minimum_x, x)
        minimum_y = min(minimum_y, y)
        maximum_x = max(maximum_x, x)
        maximum_y = max(maximum_y, y)
        pixel_count += 1
    if maximum_x < 0:
        return None, 0
    return (
        {
            "x": minimum_x,
            "y": minimum_y,
            "width": maximum_x - minimum_x + 1,
            "height": maximum_y - minimum_y + 1,
        },
        pixel_count,
    )


def _inside(inner: dict[str, int], outer: dict[str, int]) -> bool:
    return (
        inner["x"] >= outer["x"]
        and inner["y"] >= outer["y"]
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"]
    )


def _font_resolution(log: str, requested_font: str) -> dict[str, Any]:
    resolved_faces: list[str] = []
    selected_requests: list[str] = []
    for line in log.splitlines():
        match = _FONTSELECT.search(line.strip())
        if match is None:
            continue
        selected_requests.append(match.group("requested").strip())
        resolved_faces.append(_portable_resolved_face(match.group("resolved")))
    resolved_faces = list(dict.fromkeys(resolved_faces))
    missing_glyph_observed = any(
        "glyph" in line.casefold()
        and ("not found" in line.casefold() or "selecting one more font" in line.casefold())
        for line in log.splitlines()
    )
    requested_normalized = _normalized_font_name(requested_font)
    face_matches = any(
        requested_normalized
        and (
            requested_normalized in _normalized_font_name(face)
            or _normalized_font_name(face) in requested_normalized
        )
        for face in resolved_faces
    )
    fallback_detected = bool(resolved_faces) and not face_matches
    fallback_detected = fallback_detected or missing_glyph_observed
    status = (
        "unknown"
        if not resolved_faces
        else "fallback"
        if fallback_detected
        else "resolved"
    )
    return {
        "requested_font": requested_font,
        "status": status,
        "resolved_faces": resolved_faces,
        "fallback_detected": fallback_detected,
        "missing_glyph_observed": missing_glyph_observed,
        "log_sha256": _sha256_bytes(log.encode("utf-8")),
    }


def _effective_font_sizes(ass_text: str, default_size: int) -> list[int]:
    sizes: list[int] = []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue: 1,"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        match = _FONT_SIZE_OVERRIDE.match(fields[-1])
        sizes.append(int(match.group("size")) if match else default_size)
    return sizes


def _effective_ass_layouts(
    ass_text: str,
    default_size: int,
) -> list[dict[str, int]]:
    layouts: list[dict[str, int]] = []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue: 1,"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            continue
        text = fields[-1]
        match = _FONT_SIZE_OVERRIDE.match(text)
        layouts.append(
            {
                "font_size": int(match.group("size")) if match else default_size,
                "line_count": text.count("\\N") + 1,
            }
        )
    return layouts


_CACHE_DOCUMENT_FIELDS = frozenset(
    {"cache_version", "probe_version", "measurement_method", "cache_key", "measurement"}
)
_CACHE_MEASUREMENT_FIELDS = frozenset(
    {
        "measured_bbox",
        "measured_pixel_count",
        "clipped",
        "inside_safe_area",
        "real_layout_verified",
        "measurement_method",
        "font_resolution",
    }
)
_FONT_RESOLUTION_FIELDS = frozenset(
    {
        "requested_font",
        "status",
        "resolved_faces",
        "fallback_detected",
        "missing_glyph_observed",
        "log_sha256",
    }
)


def _validated_cached_measurement(
    value: Any,
    *,
    width: int,
    height: int,
    safe_area: dict[str, int],
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != _CACHE_MEASUREMENT_FIELDS:
        return None
    if value.get("measurement_method") != MEASUREMENT_METHOD:
        return None
    pixel_count = value.get("measured_pixel_count")
    if (
        not isinstance(pixel_count, int)
        or isinstance(pixel_count, bool)
        or not 0 <= pixel_count <= width * height
    ):
        return None
    bbox = value.get("measured_bbox")
    if bbox is None:
        if (
            pixel_count != 0
            or value.get("clipped") is not None
            or value.get("inside_safe_area") is not None
            or value.get("real_layout_verified") is not False
        ):
            return None
        sanitized_bbox = None
    else:
        if not isinstance(bbox, dict) or set(bbox) != {"x", "y", "width", "height"}:
            return None
        if any(
            not isinstance(bbox.get(field), int) or isinstance(bbox.get(field), bool)
            for field in ("x", "y", "width", "height")
        ):
            return None
        if (
            bbox["x"] < 0
            or bbox["y"] < 0
            or bbox["width"] <= 0
            or bbox["height"] <= 0
            or bbox["x"] + bbox["width"] > width
            or bbox["y"] + bbox["height"] > height
            or pixel_count <= 0
            or pixel_count > bbox["width"] * bbox["height"]
        ):
            return None
        expected_clipped = (
            bbox["x"] == 0
            or bbox["y"] == 0
            or bbox["x"] + bbox["width"] == width
            or bbox["y"] + bbox["height"] == height
        )
        expected_inside = _inside(bbox, safe_area)
        expected_verified = not expected_clipped and expected_inside
        if (
            value.get("clipped") is not expected_clipped
            or value.get("inside_safe_area") is not expected_inside
            or value.get("real_layout_verified") is not expected_verified
        ):
            return None
        sanitized_bbox = dict(bbox)

    font = value.get("font_resolution")
    if not isinstance(font, dict) or set(font) != _FONT_RESOLUTION_FIELDS:
        return None
    if (
        not isinstance(font.get("requested_font"), str)
        or not font["requested_font"].strip()
        or font.get("status") not in {"unknown", "resolved", "fallback"}
        or not isinstance(font.get("resolved_faces"), list)
        or any(not isinstance(face, str) or not face for face in font["resolved_faces"])
        or not isinstance(font.get("fallback_detected"), bool)
        or not isinstance(font.get("missing_glyph_observed"), bool)
        or not isinstance(font.get("log_sha256"), str)
        or not _SHA256.fullmatch(font["log_sha256"])
    ):
        return None
    if (
        (font["status"] == "unknown" and font["resolved_faces"])
        or (font["status"] == "fallback") is not font["fallback_detected"]
        or (font["missing_glyph_observed"] and not font["fallback_detected"])
    ):
        return None
    return {
        "measured_bbox": sanitized_bbox,
        "measured_pixel_count": pixel_count,
        "clipped": value["clipped"],
        "inside_safe_area": value["inside_safe_area"],
        "real_layout_verified": value["real_layout_verified"],
        "measurement_method": MEASUREMENT_METHOD,
        "font_resolution": {
            **font,
            "resolved_faces": list(font["resolved_faces"]),
        },
    }


def _load_cache(
    path: Path,
    cache_key: str,
    *,
    width: int,
    height: int,
    safe_area: dict[str, int],
) -> dict[str, Any] | None:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(cached, dict)
        or set(cached) != _CACHE_DOCUMENT_FIELDS
        or cached.get("cache_version") != "1.0"
        or cached.get("cache_key") != cache_key
        or cached.get("probe_version") != LAYOUT_PROBE_VERSION
        or cached.get("measurement_method") != MEASUREMENT_METHOD
    ):
        return None
    return _validated_cached_measurement(
        cached.get("measurement"),
        width=width,
        height=height,
        safe_area=safe_area,
    )


def _write_cache(path: Path, cache_key: str, measurement: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "cache_version": "1.0",
        "probe_version": LAYOUT_PROBE_VERSION,
        "measurement_method": MEASUREMENT_METHOD,
        "cache_key": cache_key,
        "measurement": measurement,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _cue_base(
    cue: dict[str, Any],
    *,
    style: dict[str, Any],
    style_binding: dict[str, Any],
    safe_area: dict[str, int],
    canvas: dict[str, int],
    font_identity: dict[str, Any],
    ffmpeg_identity: dict[str, Any],
    ass_sha256: str,
    effective_font_size: int,
) -> dict[str, Any]:
    cue_id = cue.get("cue_id")
    if not isinstance(cue_id, str) or not cue_id.strip():
        raise ValueError("every subtitle cue requires a stable non-empty cue_id")
    text = cue.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"subtitle cue {cue_id} requires non-empty text")
    start = _finite_number(cue.get("start_sec"), f"{cue_id}.start_sec")
    end = _finite_number(cue.get("end_sec"), f"{cue_id}.end_sec")
    if start < 0 or end <= start:
        raise ValueError(f"subtitle cue {cue_id} has invalid timing")
    position = str(cue.get("position", style.get("position", "bottom_center")))
    if position not in {"bottom_center", "top_center"}:
        raise ValueError(f"subtitle cue {cue_id} has unsupported position")
    effective_style = dict(style)
    effective_style["position"] = position
    effective_style_binding = dict(style_binding)
    effective_style_binding["position"] = position
    json.dumps(effective_style, allow_nan=False)
    json.dumps(effective_style_binding, allow_nan=False)
    cache_key = build_layout_cache_key(
        text=text,
        style=effective_style,
        canvas=canvas,
        font_directory=font_identity,
        ffmpeg=ffmpeg_identity,
        ass_sha256=ass_sha256,
    )
    return {
        "cue_id": cue_id,
        "text_sha256": _sha256_bytes(text.encode("utf-8")),
        "style_sha256": _sha256_bytes(_canonical_bytes(effective_style_binding)),
        "ass_sha256": ass_sha256,
        "cache_key": cache_key,
        "cache_hit": False,
        "sample_time_sec": round(start + (end - start) / 2.0, 6),
        "position": position,
        "line_count": text.replace("\r\n", "\n").replace("\r", "\n").count("\n") + 1,
        "line_count_source": "heuristic_input_fallback",
        "effective_font_size": effective_font_size,
        "safe_area": dict(safe_area),
        "measured_bbox": None,
        "measured_pixel_count": 0,
        "clipped": None,
        "inside_safe_area": None,
        "real_layout_verified": False,
        "measurement_method": "heuristic-only-unmeasured",
        "font_resolution": {
            "requested_font": str(style.get("font_name", "Microsoft YaHei")),
            "status": "unknown",
            "resolved_faces": [],
            "fallback_detected": False,
            "missing_glyph_observed": False,
            "log_sha256": "0" * 64,
        },
        "warning_codes": [],
        "blocker_codes": [],
    }


def probe_subtitle_layout(
    *,
    ass_path: Path,
    cues: list[dict[str, Any]],
    style: dict[str, Any],
    style_binding: dict[str, Any] | None = None,
    canvas_width: int,
    canvas_height: int,
    executable: str = "ffmpeg",
    mode: str = "preview",
    project_id: str,
    subtitle_source_sha256: str,
    realized_timeline_sha256: str,
    readability_qa_sha256: str,
    readability_policy_sha256: str,
    readability_policy_version: str,
    fonts_directory: Path | None = None,
    enhancement_plan_sha256: str | None = None,
    subtitle_source_path: str | None = None,
    cache_directory: Path | None = None,
) -> dict[str, Any]:
    """Measure subtitle pixels from the exact ASS file using real FFmpeg/libass output."""

    if mode not in {"preview", "release"}:
        raise ValueError("mode must be preview or release")
    width = _positive_integer(canvas_width, "canvas_width")
    height = _positive_integer(canvas_height, "canvas_height")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id must be non-empty")
    if not isinstance(readability_policy_version, str) or not readability_policy_version.strip():
        raise ValueError("readability_policy_version must be non-empty")
    _validate_sha256(subtitle_source_sha256, "subtitle_source_sha256")
    _validate_sha256(realized_timeline_sha256, "realized_timeline_sha256")
    _validate_sha256(readability_qa_sha256, "readability_qa_sha256")
    _validate_sha256(readability_policy_sha256, "readability_policy_sha256")
    _validate_sha256(
        enhancement_plan_sha256,
        "enhancement_plan_sha256",
        optional=True,
    )
    ass_path = Path(ass_path).resolve()
    if not ass_path.is_file():
        raise FileNotFoundError(ass_path)
    ass_bytes = ass_path.read_bytes()
    if ass_bytes.startswith(b"\xef\xbb\xbf"):
        raise ValueError("ASS input must be UTF-8 without a BOM")
    ass_text = ass_bytes.decode("utf-8")
    ass_sha256 = _sha256_bytes(ass_bytes)
    bound_style = dict(style if style_binding is None else style_binding)
    if any(Path(value).is_absolute() for value in bound_style.values() if isinstance(value, str)):
        raise ValueError("style_binding must not contain absolute paths")
    json.dumps(bound_style, ensure_ascii=False, allow_nan=False)
    canvas = {"width": width, "height": height}
    safe_area = _safe_area(width, height, style)
    font_identity = font_directory_identity(fonts_directory)
    warning_codes: list[str] = []
    blocker_codes: list[str] = []

    try:
        ffmpeg_identity = inspect_ffmpeg_identity(executable)
    except (OSError, FFmpegError, ValueError):
        ffmpeg_identity = None
        capability_code = "real_layout_probe_unavailable"
    else:
        capability_code = (
            "subtitles_filter_unavailable"
            if not ffmpeg_identity["subtitles_filter_available"]
            else None
        )
    unavailable = capability_code is not None
    if unavailable:
        if mode == "preview":
            warning_codes.append(capability_code)
        else:
            blocker_codes.extend(
                [capability_code, "real_layout_probe_required"]
                if capability_code != "real_layout_probe_required"
                else [capability_code]
            )
    if fonts_directory is not None and not font_identity["present"]:
        code = "font_directory_unavailable"
        (warning_codes if mode == "preview" else blocker_codes).append(code)

    cache_identity = ffmpeg_identity or {
        "executable_sha256": "0" * 64,
        "version_line": "unavailable",
        "filters_sha256": "0" * 64,
    }
    default_font_size = _positive_integer(style.get("font_size", 64), "style.font_size")
    effective_layouts = _effective_ass_layouts(ass_text, default_font_size)
    ass_layout_count_matches = len(effective_layouts) == len(cues)
    if not ass_layout_count_matches:
        effective_layouts = [
            {
                "font_size": default_font_size,
                "line_count": str(cue.get("text", "")).replace("\r\n", "\n").replace("\r", "\n").count("\n") + 1,
            }
            for cue in cues
        ]
    cue_ids: set[str] = set()
    results: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("subtitle cues must be objects")
        result = _cue_base(
            cue,
            style=style,
            safe_area=safe_area,
            style_binding=bound_style,
            canvas=canvas,
            font_identity=font_identity,
            ffmpeg_identity=cache_identity,
            ass_sha256=ass_sha256,
            effective_font_size=effective_layouts[index]["font_size"],
        )
        result["line_count"] = effective_layouts[index]["line_count"]
        result["line_count_source"] = (
            "ass_dialogue_explicit_breaks"
            if ass_layout_count_matches
            else "heuristic_input_fallback"
        )
        if not ass_layout_count_matches:
            result[
                "warning_codes" if mode == "preview" else "blocker_codes"
            ].append("ass_cue_count_mismatch")
        if result["cue_id"] in cue_ids:
            raise ValueError("subtitle cue IDs must be unique")
        cue_ids.add(result["cue_id"])
        if unavailable:
            result["warning_codes" if mode == "preview" else "blocker_codes"].append(
                capability_code
            )
        results.append(result)

    if not unavailable:
        resolved_ffmpeg = find_ffmpeg(executable)
        control, _ = _run_rgb_frame(
            resolved_ffmpeg,
            width=width,
            height=height,
            video_filter="format=rgb24",
            loglevel="error",
        )
        for result in results:
            cache_path = (
                Path(cache_directory).resolve() / f"{result['cache_key']}.json"
                if cache_directory is not None
                else None
            )
            measurement = (
                _load_cache(
                    cache_path,
                    result["cache_key"],
                    width=width,
                    height=height,
                    safe_area=safe_area,
                )
                if mode == "preview"
                and cache_path is not None
                and cache_path.is_file()
                else None
            )
            if measurement is not None:
                result.update(measurement)
                result["cache_hit"] = True
            else:
                subtitle_filter = _subtitle_filter(ass_path, fonts_directory)
                video_filter = (
                    f"setpts=PTS+{result['sample_time_sec']:.6f}/TB,"
                    f"{subtitle_filter},format=rgb24"
                )
                try:
                    rendered, log = _run_rgb_frame(
                        resolved_ffmpeg,
                        width=width,
                        height=height,
                        video_filter=video_filter,
                        loglevel="verbose",
                    )
                except FFmpegError:
                    result["blocker_codes"].append("libass_render_failed")
                    continue
                bbox, pixel_count = _measure_bbox(control, rendered, width, height)
                font_resolution = _font_resolution(
                    log,
                    str(style.get("font_name", "Microsoft YaHei")),
                )
                clipped = (
                    None
                    if bbox is None
                    else bbox["x"] == 0
                    or bbox["y"] == 0
                    or bbox["x"] + bbox["width"] == width
                    or bbox["y"] + bbox["height"] == height
                )
                inside_safe_area = None if bbox is None else _inside(bbox, safe_area)
                measurement = {
                    "measured_bbox": bbox,
                    "measured_pixel_count": pixel_count,
                    "clipped": clipped,
                    "inside_safe_area": inside_safe_area,
                    "real_layout_verified": bool(
                        bbox is not None and not clipped and inside_safe_area
                    ),
                    "measurement_method": MEASUREMENT_METHOD,
                    "font_resolution": font_resolution,
                }
                result.update(measurement)
                if cache_path is not None:
                    _write_cache(cache_path, result["cache_key"], measurement)

            if result["measured_bbox"] is None:
                result["blocker_codes"].append("subtitle_pixels_missing")
            if result["clipped"]:
                result["blocker_codes"].append("subtitle_canvas_clipped")
            if result["inside_safe_area"] is False:
                result["blocker_codes"].append("subtitle_outside_safe_area")
            font_resolution = result["font_resolution"]
            if font_resolution["status"] == "unknown":
                target = result["warning_codes"] if mode == "preview" else result["blocker_codes"]
                target.append("font_resolution_unverified")
            if font_resolution["fallback_detected"]:
                target = result["warning_codes"] if mode == "preview" else result["blocker_codes"]
                target.append("font_fallback_unverified")

    warning_codes.extend(
        code for result in results for code in result["warning_codes"]
    )
    blocker_codes.extend(
        code for result in results for code in result["blocker_codes"]
    )
    warning_codes = sorted(set(warning_codes))
    blocker_codes = sorted(set(blocker_codes))
    bindings: dict[str, Any] = {
        "subtitle_source_sha256": subtitle_source_sha256,
        "realized_timeline_sha256": realized_timeline_sha256,
        "readability_qa_sha256": readability_qa_sha256,
        "readability_policy_sha256": readability_policy_sha256,
        "ass_sha256": ass_sha256,
        "readability_policy_version": readability_policy_version,
    }
    if enhancement_plan_sha256 is not None:
        bindings["enhancement_plan_sha256"] = enhancement_plan_sha256
    if subtitle_source_path is not None:
        if Path(subtitle_source_path).is_absolute() or ".." in Path(subtitle_source_path).parts:
            raise ValueError("subtitle_source_path must be a confined relative path")
        bindings["subtitle_source_path"] = Path(subtitle_source_path).as_posix()
    status = "blocked" if blocker_codes else "warning" if warning_codes else "passed"
    real_count = sum(result["real_layout_verified"] for result in results)
    return {
        "schema_version": LAYOUT_QA_SCHEMA_VERSION,
        "document_type": "subtitle_layout_qa",
        "probe_version": LAYOUT_PROBE_VERSION,
        "status": status,
        "mode": mode,
        "probe_mode": "heuristic" if unavailable else "real_libass",
        "project_id": project_id,
        "bindings": bindings,
        "ffmpeg_identity": ffmpeg_identity,
        "font_directory_identity": font_identity,
        "canvas": canvas,
        "capabilities": {
            "subtitles_filter_available": bool(
                ffmpeg_identity and ffmpeg_identity["subtitles_filter_available"]
            ),
            "libass_enabled": bool(ffmpeg_identity and ffmpeg_identity["libass_enabled"]),
            "real_frame_measurement": not unavailable,
            "ocr_performed": False,
        },
        "summary": {
            "cue_count": len(results),
            "real_layout_verified_count": real_count,
            "cache_hit_count": sum(result["cache_hit"] for result in results),
            "blocker_count": sum(len(result["blocker_codes"]) for result in results)
            + len([code for code in blocker_codes if not any(code in result["blocker_codes"] for result in results)]),
            "warning_count": sum(len(result["warning_codes"]) for result in results)
            + len([code for code in warning_codes if not any(code in result["warning_codes"] for result in results)]),
        },
        "cues": results,
        "warning_codes": warning_codes,
        "blocker_codes": blocker_codes,
        "limitations": ["已生成视觉帧和布局证据，文字准确性仍需人工听校。"],
    }
