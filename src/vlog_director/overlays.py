from __future__ import annotations

import math
from typing import Any


SUPPORTED_OVERLAY_ANIMATIONS = {"none", "fade", "slide"}


def build_hyperframes_overlay_filters(
    input_index: int,
    sequence: int,
    base_label: str,
    item: dict[str, Any],
) -> tuple[list[str], str, set[str]]:
    """Place a full-canvas transparent HyperFrames clip on the approved timeline."""
    allowed_fields = {
        "id",
        "type",
        "source",
        "media_kind",
        "source_sha256",
        "effect_intent",
        "approval_sha256",
        "start_sec",
        "end_sec",
        "anchor",
        "animation",
        "scale_percent",
        "margin_percent",
    }
    unknown_fields = sorted(set(item) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            "HyperFrames overlay contains unsupported fields: "
            + ", ".join(unknown_fields)
        )
    if item.get("type") != "hyperframes" or item.get("media_kind") != "transparent_video":
        raise ValueError("HyperFrames overlay requires transparent_video media")
    if (
        item.get("anchor") != "center"
        or item.get("animation") != "none"
        or float(item.get("scale_percent", 100)) != 100
        or float(item.get("margin_percent", 0)) != 0
    ):
        raise ValueError("HyperFrames overlays must remain full-canvas and use their authored motion")
    start = float(item["start_sec"])
    end = float(item["end_sec"])
    if not all(math.isfinite(value) for value in (start, end)) or end <= start:
        raise ValueError("HyperFrames overlay timing is invalid")
    prepared_label = f"hyperframes_prepared_{sequence}"
    next_label = f"video_overlay_{sequence}"
    preparation = (
        f"[{input_index}:v]format=rgba,"
        f"setpts=PTS-STARTPTS+{start:.6f}/TB[{prepared_label}]"
    )
    composition = (
        f"[{base_label}][{prepared_label}]"
        "overlay=x=0:y=0:eof_action=pass:repeatlast=0:shortest=0:"
        f"enable='between(t,{start:.6f},{end:.6f})'[{next_label}]"
    )
    return [preparation, composition], next_label, {"format", "setpts", "overlay"}


def anchor_expression(
    anchor: str,
    margin_percent: float = 5.0,
) -> tuple[str, str]:
    if not 0 <= margin_percent <= 20:
        raise ValueError("overlay margin_percent must be between 0 and 20")
    margin = margin_percent / 100.0
    anchors = {
        "top_left": (f"W*{margin:.6f}", f"H*{margin:.6f}"),
        "top_right": (f"W-w-W*{margin:.6f}", f"H*{margin:.6f}"),
        "center": ("(W-w)/2", "(H-h)/2"),
        "bottom_left": (f"W*{margin:.6f}", f"H-h-H*{margin:.6f}"),
        "bottom_right": (
            f"W-w-W*{margin:.6f}",
            f"H-h-H*{margin:.6f}",
        ),
        "bottom_center": ("(W-w)/2", f"H-h-H*{margin:.6f}"),
    }
    try:
        return anchors[anchor]
    except KeyError as error:
        raise ValueError(f"unsupported overlay anchor: {anchor}") from error


def _slide_axis(
    anchor: str,
    target_x: str,
    target_y: str,
) -> tuple[str, str, str]:
    if anchor in {"top_left", "bottom_left"}:
        return "x", "-w", target_x
    if anchor in {"top_right", "bottom_right"}:
        return "x", "W", target_x
    return "y", "-h", target_y


def _slide_expression(
    offscreen: str,
    target: str,
    start: float,
    end: float,
    duration: float,
) -> str:
    enter_end = start + duration
    exit_start = end - duration
    return (
        f"if(lt(t,{enter_end:.3f}),"
        f"({offscreen})+(({target})-({offscreen}))*(t-{start:.3f})/{duration:.3f},"
        f"if(lt(t,{exit_start:.3f}),({target}),"
        f"({target})+(({offscreen})-({target}))*(t-{exit_start:.3f})/{duration:.3f}))"
    )


def build_overlay_filters(
    input_index: int,
    sequence: int,
    base_label: str,
    item: dict[str, Any],
    canvas_width: int,
) -> tuple[list[str], str, set[str]]:
    allowed_fields = {
        "id",
        "type",
        "source",
        "start_sec",
        "end_sec",
        "anchor",
        "animation",
        "animation_duration_sec",
        "scale_percent",
        "margin_percent",
    }
    unknown_fields = sorted(set(item) - allowed_fields)
    if unknown_fields:
        raise ValueError(
            "overlay contains unsupported fields: " + ", ".join(unknown_fields)
        )
    start = float(item["start_sec"])
    end = float(item["end_sec"])
    if not all(math.isfinite(value) for value in (start, end)) or end <= start:
        raise ValueError("overlay end_sec must be greater than start_sec")
    if canvas_width <= 0:
        raise ValueError("overlay canvas_width must be positive")

    animation = str(item.get("animation", "none"))
    if animation not in SUPPORTED_OVERLAY_ANIMATIONS:
        raise ValueError(f"unsupported overlay animation: {animation}")
    scale_percent = float(item.get("scale_percent", 36.0))
    if not 5 <= scale_percent <= 100:
        raise ValueError("overlay scale_percent must be between 5 and 100")
    margin_percent = float(item.get("margin_percent", 5.0))
    target_x, target_y = anchor_expression(str(item["anchor"]), margin_percent)

    requested_duration = item.get("animation_duration_sec")
    animation_duration = (
        float(requested_duration)
        if requested_duration is not None
        else min(0.35, (end - start) / 3.0)
    )
    if animation != "none" and (
        not math.isfinite(animation_duration)
        or animation_duration < 0.1
        or animation_duration * 2 >= end - start
    ):
        raise ValueError("overlay animation duration must leave a visible hold interval")

    prepared_label = f"overlay_prepared_{sequence}"
    next_label = f"video_overlay_{sequence}"
    target_width = max(2, round(canvas_width * scale_percent / 100.0))
    preparation = (
        f"[{input_index}:v]"
        f"scale=w={target_width}:h=-1:flags=lanczos,"
        "format=rgba,setpts=PTS-STARTPTS"
    )
    required = {"scale", "format", "setpts", "overlay"}
    if animation == "fade":
        preparation += (
            f",fade=t=in:st={start:.3f}:d={animation_duration:.3f}:alpha=1"
            f",fade=t=out:st={end - animation_duration:.3f}:"
            f"d={animation_duration:.3f}:alpha=1"
        )
        required.add("fade")
    preparation += f"[{prepared_label}]"

    x_expression = target_x
    y_expression = target_y
    if animation == "slide":
        axis, offscreen, target = _slide_axis(
            str(item["anchor"]),
            target_x,
            target_y,
        )
        slide = _slide_expression(
            offscreen,
            target,
            start,
            end,
            animation_duration,
        )
        if axis == "x":
            x_expression = slide
        else:
            y_expression = slide

    composition = (
        f"[{base_label}][{prepared_label}]"
        f"overlay=x='{x_expression}':y='{y_expression}':"
        f"enable='between(t,{start:.3f},{end:.3f})':eof_action=pass"
        f"[{next_label}]"
    )
    return [preparation, composition], next_label, required
