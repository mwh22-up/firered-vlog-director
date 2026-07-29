from __future__ import annotations

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


def write_ass_subtitles(
    cues: list[dict[str, Any]],
    output: Path,
    title: str = "Vlog subtitles",
    font_name: str = "Microsoft YaHei",
    font_size: int = 48,
    margin_v: int = 80,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in sorted(cues, key=lambda item: (float(item["start_sec"]), float(item["end_sec"]))):
        events.append(
            "Dialogue: 0,"
            f"{_ass_time(float(cue['start_sec']))},"
            f"{_ass_time(float(cue['end_sec']))},"
            "Default,,0,0,0,,"
            f"{_escape_ass_text(str(cue['text']))}"
        )
    output.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return output
