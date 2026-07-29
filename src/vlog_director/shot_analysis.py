from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .event_analysis import refine_sequence_roles
from .shot_scoring import (
    classify_role,
    hash_distance,
    score_shot,
    summarize_audio,
    summarize_visual,
)


def build_shots(
    scene_times: list[float],
    duration_sec: float,
    visual_samples: list[dict[str, Any]],
    audio_samples: list[dict[str, Any]],
    transcript: dict[str, Any],
) -> list[dict[str, Any]]:
    boundaries = [0.0]
    boundaries.extend(
        time_sec
        for time_sec in sorted(set(scene_times))
        if 0 < time_sec < duration_sec
    )
    boundaries.append(duration_sec)
    speech_segments = transcript.get("segments", [])
    shots: list[dict[str, Any]] = []
    previous_hash: str | None = None

    for index in range(len(boundaries) - 1):
        start_sec = boundaries[index]
        end_sec = boundaries[index + 1]
        visual = samples_in_range(visual_samples, start_sec, end_sec)
        audio = samples_in_range(audio_samples, start_sec, end_sec)
        speech_ratio = speech_coverage(speech_segments, start_sec, end_sec)
        visual_summary = summarize_visual(visual)
        audio_summary = summarize_audio(audio, speech_ratio)
        novelty = hash_distance(previous_hash, visual_summary["visual_hash"])
        previous_hash = visual_summary["visual_hash"]
        duration = end_sec - start_sec
        role = classify_role(
            duration,
            visual_summary,
            audio_summary,
            speech_ratio,
            novelty,
        )
        shots.append(
            {
                "shot_id": f"shot-{index + 1:04d}",
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "duration_sec": round(duration, 3),
                "role": role,
                "speech_ratio": round(speech_ratio, 4),
                "visual": visual_summary,
                "audio": audio_summary,
                "novelty_score": round(novelty, 4),
            }
        )

    refine_sequence_roles(shots)
    for shot in shots:
        score_shot(shot)
    calibrate_recommendations(shots)
    return shots


def summarize_patterns(
    shots: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    negative_signals = {
        "与前一镜头高度重复",
        "画面清晰度较低",
        "曝光异常",
        "缺少动作、声音和新增信息",
        "镜头过短且难以辨认",
    }
    role_groups: dict[str, list[dict[str, Any]]] = {}
    for shot in shots:
        role_groups.setdefault(shot["role"], []).append(shot)

    archetypes = []
    for role, role_shots in sorted(role_groups.items()):
        retained = [
            shot
            for shot in role_shots
            if shot["recommendation"] in {"protect", "retain"}
        ]
        archetypes.append(
            {
                "role": role,
                "shot_count": len(role_shots),
                "retained_count": len(retained),
                "retained_ratio": round(len(retained) / len(role_shots), 4),
                "average_duration_sec": round(
                    mean(shot["duration_sec"] for shot in role_shots),
                    3,
                ),
                "average_keep_score": round(
                    mean(shot["keep_score"] for shot in role_shots),
                    4,
                ),
            }
        )

    cut_reasons = Counter()
    for shot in shots:
        if shot["recommendation"] == "cut_first":
            cut_reasons.update(
                reason
                for reason in shot["reasons"]
                if reason in negative_signals
            )
    event_types = Counter(event["event_type"] for event in events)
    return {
        "retention_archetypes": archetypes,
        "cut_first_signals": [
            {"signal": signal, "shot_count": count}
            for signal, count in cut_reasons.most_common()
        ],
        "event_patterns": [
            {"event_type": event_type, "event_count": count}
            for event_type, count in event_types.most_common()
        ],
        "evidence_limits": [
            "参考片是已经剪完的成片，只能直接学习被保留镜头的正向模式。",
            "cut_first 来自重复、模糊、曝光、无动作和无语义等弱信号，不代表原作者真实删除记录。",
            "要监督学习真正的保留与删除偏好，需要同时提供原始素材和最终成片。"
        ],
    }


def samples_in_range(
    samples: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> list[dict[str, Any]]:
    selected = [
        sample
        for sample in samples
        if start_sec <= float(sample["time_sec"]) < end_sec
    ]
    if selected or not samples:
        return selected
    midpoint = (start_sec + end_sec) / 2
    return [min(samples, key=lambda sample: abs(sample["time_sec"] - midpoint))]


def speech_coverage(
    segments: list[dict[str, Any]],
    start_sec: float,
    end_sec: float,
) -> float:
    duration = end_sec - start_sec
    if duration <= 0:
        return 0.0
    overlap = sum(
        max(
            0.0,
            min(end_sec, float(segment["end_sec"]))
            - max(start_sec, float(segment["start_sec"])),
        )
        for segment in segments
    )
    return min(1.0, overlap / duration)


def calibrate_recommendations(
    shots: list[dict[str, Any]],
) -> None:
    scores = sorted(shot["keep_score"] for shot in shots)
    retain_threshold = score_percentile(scores, 0.45)
    protect_threshold = score_percentile(scores, 0.82)
    hard_negative_signals = {
        "与前一镜头高度重复",
        "画面清晰度较低",
        "曝光异常",
        "缺少动作、声音和新增信息",
    }
    for shot in shots:
        reasons = set(shot["reasons"])
        if reasons.intersection(hard_negative_signals) and (
            shot["keep_score"] < retain_threshold
        ):
            shot["recommendation"] = "cut_first"
        elif shot["keep_score"] >= protect_threshold:
            shot["recommendation"] = "protect"
        elif shot["keep_score"] >= retain_threshold:
            shot["recommendation"] = "retain"
        else:
            shot["recommendation"] = "optional"


def score_percentile(
    scores: list[float],
    fraction: float,
) -> float:
    if not scores:
        return 0.0
    index = min(len(scores) - 1, max(0, int(len(scores) * fraction)))
    return scores[index]
