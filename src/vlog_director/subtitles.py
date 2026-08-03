from __future__ import annotations

import math
import unicodedata
from pathlib import Path
from typing import Any


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\n", r"\N")
    )


def _validate_ass_field(value: str, field: str) -> str:
    if not value or any(character in value for character in ",\r\n"):
        raise ValueError(f"{field} must be a non-empty ASS-safe value")
    return value


def _text_width_units(text: str) -> float:
    width = 0.0
    for character in text:
        if character.isspace():
            width += 0.35
        elif unicodedata.east_asian_width(character) in {"F", "W"}:
            width += 1.0
        else:
            width += 0.58
    return width


def _preferred_break(text: str, line_capacity_units: float) -> int:
    punctuation_candidates = [
        index + 1
        for index, character in enumerate(text[:-1])
        if character in "，。！？；：、,.!?;: "
    ]
    all_candidates = range(1, len(text))
    balanced = min(
        all_candidates,
        key=lambda index: (
            abs(
                _text_width_units(text[:index])
                - _text_width_units(text[index:])
            ),
            index,
        ),
    )
    feasible_punctuation = [
        index
        for index in punctuation_candidates
        if max(
            _text_width_units(text[:index]),
            _text_width_units(text[index:]),
        )
        <= line_capacity_units
    ]
    if not feasible_punctuation:
        return balanced
    return min(feasible_punctuation, key=lambda index: (abs(index - balanced), index))


def _layout_text(
    text: str,
    max_lines: int,
    line_capacity_units: float,
    available_width: float,
    available_height: float,
    font_size: int,
    minimum_font_size: int,
    outline: int,
    background_padding: int,
) -> tuple[str, int]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("subtitle text must not be empty")

    explicit_lines = [line.strip() for line in normalized.split("\n")]
    if any(not line for line in explicit_lines):
        raise ValueError("subtitle text must not contain empty lines")
    if len(explicit_lines) > max_lines:
        raise ValueError(f"subtitle exceeds max_lines={max_lines}")

    lines = explicit_lines
    if (
        len(lines) == 1
        and _text_width_units(lines[0]) > line_capacity_units
        and max_lines > 1
    ):
        break_at = _preferred_break(lines[0], line_capacity_units)
        lines = [lines[0][:break_at].strip(), lines[0][break_at:].strip()]

    longest_line = max(_text_width_units(line) for line in lines)
    fitted_size = font_size
    required_width = longest_line * font_size + 2 * (outline + background_padding)
    if required_width > available_width:
        fitted_size = math.floor(
            (available_width - 2 * (outline + background_padding)) / longest_line
        )
        if fitted_size < minimum_font_size:
            raise ValueError(
                "subtitle cannot fit inside the configured safe area without "
                f"shrinking below minimum_font_size={minimum_font_size}"
            )
    required_height = len(lines) * fitted_size * 1.25 + 2 * (
        outline + background_padding
    )
    if required_height > available_height:
        raise ValueError("subtitle lines do not fit inside the vertical safe area")
    return "\n".join(lines), fitted_size


def _ass_back_colour(opacity_percent: float) -> str:
    alpha = round(255 * (1.0 - opacity_percent / 100.0))
    return f"&H{alpha:02X}101010"


def write_ass_subtitles(
    cues: list[dict[str, Any]],
    output: Path,
    title: str = "Vlog subtitles",
    font_name: str = "Microsoft YaHei",
    font_size: int = 64,
    margin_v: int = 72,
    outline: int = 4,
    shadow: int = 1,
    bold: bool = True,
    position: str = "bottom_center",
    max_lines: int = 2,
    safe_margin_percent: float = 8.0,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    max_chars_per_line: int = 18,
    minimum_font_size: int = 60,
    background_opacity_percent: float = 42.0,
    background_padding: int = 8,
) -> Path:
    if position not in {"bottom_center", "top_center"}:
        raise ValueError("subtitle position must be bottom_center or top_center")
    if max_lines not in {1, 2}:
        raise ValueError("subtitle max_lines must be 1 or 2")
    if not 0 <= safe_margin_percent <= 20:
        raise ValueError("subtitle safe_margin_percent must be between 0 and 20")
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("subtitle canvas dimensions must be positive")
    if max_chars_per_line <= 0 or minimum_font_size <= 0:
        raise ValueError("subtitle layout sizes must be positive")
    if not 0 <= background_opacity_percent <= 100:
        raise ValueError("subtitle background opacity must be between 0 and 100")
    if outline < 0 or shadow < 0 or background_padding < 0:
        raise ValueError("subtitle border dimensions must be non-negative")

    title = _validate_ass_field(title, "title")
    font_name = _validate_ass_field(font_name, "font_name")
    horizontal_margin = round(canvas_width * safe_margin_percent / 100.0)
    vertical_margin = max(margin_v, round(canvas_height * safe_margin_percent / 100.0))
    available_width = canvas_width - 2 * horizontal_margin
    available_height = canvas_height - 2 * vertical_margin
    line_capacity_units = min(
        float(max_chars_per_line),
        (available_width - 2 * (outline + background_padding)) / font_size,
    )
    if line_capacity_units <= 0 or available_height <= 0:
        raise ValueError("subtitle safe area leaves no usable canvas")
    back_colour = _ass_back_colour(background_opacity_percent)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {canvas_width}
PlayResY: {canvas_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BottomBox,{font_name},{font_size},&HFF101010,&HFF101010,{back_colour},{back_colour},{-1 if bold else 0},0,0,0,100,100,0,0,3,{background_padding},0,2,{horizontal_margin},{horizontal_margin},{vertical_margin},1
Style: TopBox,{font_name},{font_size},&HFF101010,&HFF101010,{back_colour},{back_colour},{-1 if bold else 0},0,0,0,100,100,0,0,3,{background_padding},0,8,{horizontal_margin},{horizontal_margin},{vertical_margin},1
Style: Bottom,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00101010,&HFF101010,{-1 if bold else 0},0,0,0,100,100,0,0,1,{outline},{shadow},2,{horizontal_margin},{horizontal_margin},{vertical_margin},1
Style: Top,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00101010,&HFF101010,{-1 if bold else 0},0,0,0,100,100,0,0,1,{outline},{shadow},8,{horizontal_margin},{horizontal_margin},{vertical_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in sorted(cues, key=lambda item: (float(item["start_sec"]), float(item["end_sec"]))):
        start = float(cue["start_sec"])
        end = float(cue["end_sec"])
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError("subtitle cue end_sec must be greater than start_sec")
        start_centiseconds = max(0, round(start * 100))
        end_centiseconds = max(0, round(end * 100))
        if end_centiseconds <= start_centiseconds:
            raise ValueError("subtitle cue rounds to zero duration in ASS timing")
        cue_position = str(cue.get("position", position))
        if cue_position not in {"bottom_center", "top_center"}:
            raise ValueError("subtitle cue position must be bottom_center or top_center")
        laid_out, fitted_size = _layout_text(
            str(cue["text"]),
            max_lines,
            line_capacity_units,
            available_width,
            available_height,
            font_size,
            minimum_font_size,
            outline,
            background_padding,
        )
        style_name = "Top" if cue_position == "top_center" else "Bottom"
        size_override = f"{{\\fs{fitted_size}}}" if fitted_size != font_size else ""
        event_prefix = (
            f"{_ass_time(start)},{_ass_time(end)},"
        )
        escaped_text = f"{size_override}{_escape_ass_text(laid_out)}"
        if background_opacity_percent > 0:
            events.append(
                f"Dialogue: 0,{event_prefix}{style_name}Box,,0,0,0,,{escaped_text}"
            )
        events.append(
            f"Dialogue: 1,{event_prefix}{style_name},,0,0,0,,{escaped_text}"
        )
    with output.open("w", encoding="utf-8", newline="\n") as subtitle_file:
        subtitle_file.write(header + "\n".join(events) + "\n")
    return output
