from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .ffmpeg import filter_path
from .subtitles import write_ass_subtitles


SUBTITLE_RENDER_CONTRACT_VERSION = "1.0"


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number, not bool")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer, not bool")
    return value


@dataclass(frozen=True)
class SubtitleRenderContract:
    contract_version: str
    canvas_width: int
    canvas_height: int
    font_name: str
    font_size: int
    minimum_font_size: int
    margin_v: int
    outline: int
    shadow: int
    bold: bool
    position: str
    max_lines: int
    safe_margin_percent: float
    max_chars_per_line: int
    background_opacity_percent: float
    background_padding: int
    fonts_directory: str | None

    def payload(self) -> dict[str, Any]:
        """Return the portable effective style used by ASS and layout QA."""
        return {
            "font_name": self.font_name,
            "font_size": self.font_size,
            "minimum_font_size": self.minimum_font_size,
            "margin_v": self.margin_v,
            "outline": self.outline,
            "shadow": self.shadow,
            "bold": self.bold,
            "position": self.position,
            "max_lines": self.max_lines,
            "safe_margin_percent": self.safe_margin_percent,
            "max_chars_per_line": self.max_chars_per_line,
            "background_opacity_percent": self.background_opacity_percent,
            "background_padding": self.background_padding,
        }


def build_subtitle_render_contract(
    project: Path,
    style: Mapping[str, Any],
    *,
    canvas_width: int,
    canvas_height: int,
) -> SubtitleRenderContract:
    width = _integer(canvas_width, "canvas_width")
    height = _integer(canvas_height, "canvas_height")
    if width <= 0 or height <= 0:
        raise ValueError("subtitle canvas dimensions must be positive")

    reference_font_size = _integer(style.get("font_size", 64), "font_size")
    reference_margin = _integer(style.get("margin_v", 72), "margin_v")
    reference_outline = _integer(style.get("outline", 4), "outline")
    reference_shadow = _integer(style.get("shadow", 1), "shadow")
    reference_padding = _integer(
        style.get("background_padding", 8), "background_padding"
    )
    max_lines = _integer(style.get("max_lines", 2), "max_lines")
    max_chars = _integer(
        style.get("max_chars_per_line", 18), "max_chars_per_line"
    )
    bold = style.get("bold", True)
    if not isinstance(bold, bool):
        raise ValueError("bold must be boolean")
    if any(
        value < 0
        for value in (
            reference_margin,
            reference_outline,
            reference_shadow,
            reference_padding,
        )
    ):
        raise ValueError("subtitle dimensions must be non-negative")
    if reference_font_size <= 0 or max_chars <= 0 or max_lines not in {1, 2}:
        raise ValueError("subtitle font, line, and character limits are invalid")

    safe_margin = _finite_number(
        style.get("safe_margin_percent", 8.0), "safe_margin_percent"
    )
    background_opacity = _finite_number(
        style.get("background_opacity_percent", 42.0),
        "background_opacity_percent",
    )
    if not 0 <= safe_margin <= 20:
        raise ValueError("safe_margin_percent must be between 0 and 20")
    if not 0 <= background_opacity <= 100:
        raise ValueError("background_opacity_percent must be between 0 and 100")

    font_name = str(style.get("font_name", "Microsoft YaHei")).strip()
    if not font_name or any(character in font_name for character in ",\r\n"):
        raise ValueError("font_name must be a non-empty ASS-safe value")
    position = str(style.get("position", "bottom_center"))
    if position not in {"bottom_center", "top_center"}:
        raise ValueError("position must be bottom_center or top_center")

    reference_scale = min(width / 1920.0, height / 1080.0)
    fonts = Path(project).resolve() / "assets" / "fonts"
    return SubtitleRenderContract(
        contract_version=SUBTITLE_RENDER_CONTRACT_VERSION,
        canvas_width=width,
        canvas_height=height,
        font_name=font_name,
        font_size=max(1, round(reference_font_size * reference_scale)),
        minimum_font_size=max(1, round(60 * reference_scale)),
        margin_v=max(0, round(reference_margin * reference_scale)),
        outline=max(0, round(reference_outline * reference_scale)),
        shadow=max(0, round(reference_shadow * reference_scale)),
        bold=bold,
        position=position,
        max_lines=max_lines,
        safe_margin_percent=safe_margin,
        max_chars_per_line=max_chars,
        background_opacity_percent=background_opacity,
        background_padding=max(0, round(reference_padding * reference_scale)),
        fonts_directory=str(fonts) if fonts.is_dir() else None,
    )


def write_contract_ass(
    cues: list[dict[str, Any]],
    contract: SubtitleRenderContract,
    output: Path,
    *,
    writer: Any = write_ass_subtitles,
) -> Path:
    return writer(
        cues,
        output,
        font_name=contract.font_name,
        font_size=contract.font_size,
        margin_v=contract.margin_v,
        outline=contract.outline,
        shadow=contract.shadow,
        bold=contract.bold,
        position=contract.position,
        max_lines=contract.max_lines,
        safe_margin_percent=contract.safe_margin_percent,
        canvas_width=contract.canvas_width,
        canvas_height=contract.canvas_height,
        max_chars_per_line=contract.max_chars_per_line,
        minimum_font_size=contract.minimum_font_size,
        background_opacity_percent=contract.background_opacity_percent,
        background_padding=contract.background_padding,
    )


def subtitle_filter_expression(
    ass_path: Path,
    contract: SubtitleRenderContract,
) -> str:
    expression = f"subtitles=filename='{filter_path(ass_path)}'"
    if contract.fonts_directory is not None:
        expression += f":fontsdir='{filter_path(Path(contract.fonts_directory))}'"
    return expression
