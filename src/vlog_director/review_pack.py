from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .ffmpeg import find_ffmpeg, run_command


def build_review_pack(
    media_path: Path,
    analysis: dict[str, Any],
    output_directory: Path,
    *,
    event_limit: int = 12,
    shots_per_event: int = 4,
) -> dict[str, Any]:
    output_directory.mkdir(parents=True, exist_ok=True)
    for stale_path in output_directory.glob("event-*.jpg"):
        stale_path.unlink()
    manifest_path = output_directory / "review-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    shots_by_id = {
        shot["shot_id"]: shot
        for shot in analysis["shots"]
    }
    selected_events = select_events(analysis["events"], event_limit)
    manifest_events = []

    for event in selected_events:
        event_shots = select_event_shots(
            event,
            analysis["shots"],
            shots_by_id,
            shots_per_event,
        )
        if not event_shots:
            continue
        frame_paths = []
        for index, shot in enumerate(event_shots, start=1):
            frame_path = output_directory / (
                f"{event['event_id']}-shot-{index:02d}.jpg"
            )
            extract_frame(
                media_path,
                (shot["start_sec"] + shot["end_sec"]) / 2,
                frame_path,
            )
            frame_paths.append(frame_path)
        sheet_path = output_directory / f"{event['event_id']}.jpg"
        compose_sheet(event, frame_paths, sheet_path)
        manifest_events.append(
            {
                "event_id": event["event_id"],
                "start_sec": event["start_sec"],
                "end_sec": event["end_sec"],
                "event_type": event["event_type"],
                "priority_score": event["priority_score"],
                "recommendation": event["recommendation"],
                "sheet_path": str(sheet_path.resolve()),
                "shot_ids": [shot["shot_id"] for shot in event_shots],
            }
        )

    manifest = {
        "schema_version": "1.0",
        "source_id": analysis["source"]["source_id"],
        "events": manifest_events,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def select_event_shots(
    event: dict[str, Any],
    shots: list[dict[str, Any]],
    shots_by_id: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    within_event = [
        shot
        for shot in shots
        if shot["start_sec"] >= event["start_sec"]
        and shot["end_sec"] <= event["end_sec"]
    ]
    dependency = event["sequence_dependency"]
    candidate_ids = [
        within_event[0]["shot_id"] if within_event else None,
        dependency.get("setup_shot_id"),
        dependency.get("payoff_shot_id"),
        dependency.get("reaction_shot_id"),
        within_event[-1]["shot_id"] if within_event else None,
        *event["key_shot_ids"],
    ]
    unique = {
        shot_id: shots_by_id[shot_id]
        for shot_id in candidate_ids
        if shot_id and shot_id in shots_by_id
    }
    ordered = sorted(unique.values(), key=lambda shot: shot["start_sec"])
    if len(ordered) <= limit:
        return ordered
    indexes = {
        round(index * (len(ordered) - 1) / (limit - 1))
        for index in range(limit)
    }
    return [ordered[index] for index in sorted(indexes)]


def select_events(
    events: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if len(events) <= limit:
        return events
    selected = {events[0]["event_id"]: events[0]}
    selected[events[-1]["event_id"]] = events[-1]
    for event in sorted(
        events,
        key=lambda item: item["priority_score"],
        reverse=True,
    ):
        selected[event["event_id"]] = event
        if len(selected) >= limit:
            break
    return sorted(selected.values(), key=lambda item: item["start_sec"])


def extract_frame(
    media_path: Path,
    time_sec: float,
    output_path: Path,
) -> None:
    run_command(
        [
            find_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{time_sec:.3f}",
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-vf",
            "scale=320:180:force_original_aspect_ratio=decrease,"
            "pad=320:180:(ow-iw)/2:(oh-ih)/2:black",
            str(output_path),
        ]
    )


def compose_sheet(
    event: dict[str, Any],
    frame_paths: list[Path],
    output_path: Path,
) -> None:
    images = [Image.open(path).convert("RGB") for path in frame_paths]
    header_height = 34
    canvas = Image.new(
        "RGB",
        (320 * len(images), 180 + header_height),
        "black",
    )
    draw = ImageDraw.Draw(canvas)
    label = (
        f"{event['event_id']}  "
        f"{event['start_sec']:.1f}-{event['end_sec']:.1f}s  "
        f"{event['event_type']}  score={event['priority_score']:.2f}"
    )
    draw.text((8, 9), label, fill="white")
    for index, image in enumerate(images):
        canvas.paste(image, (index * 320, header_height))
        image.close()
    canvas.save(output_path, quality=88)
