from __future__ import annotations

from statistics import mean
from typing import Any


def summarize_visual(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "brightness": 0.5,
            "contrast": 0.0,
            "sharpness": 0.0,
            "motion": 0.0,
            "visual_hash": "0" * 36,
        }
    midpoint = samples[len(samples) // 2]
    return {
        "brightness": round(mean(item["brightness"] for item in samples), 5),
        "contrast": round(mean(item["contrast"] for item in samples), 5),
        "sharpness": round(mean(item["sharpness"] for item in samples), 5),
        "motion": round(mean(item["motion"] for item in samples), 5),
        "visual_hash": midpoint["visual_hash"],
    }


def summarize_audio(
    samples: list[dict[str, Any]],
    speech_ratio: float,
) -> dict[str, Any]:
    if not samples:
        return {
            "rms": 0.0,
            "peak": 0.0,
            "spectral_centroid_hz": 0.0,
            "spectral_flatness": 0.0,
            "kind": "silence",
        }
    rms = mean(item["rms"] for item in samples)
    centroid = mean(item["spectral_centroid_hz"] for item in samples)
    flatness = mean(item["spectral_flatness"] for item in samples)
    if speech_ratio >= 0.25:
        kind = "speech"
    elif rms < 0.012:
        kind = "silence"
    elif flatness < 0.2 and centroid < 4000:
        kind = "music_likely"
    else:
        kind = "ambient_likely"
    return {
        "rms": round(rms, 6),
        "peak": round(max(item["peak"] for item in samples), 6),
        "spectral_centroid_hz": round(centroid, 2),
        "spectral_flatness": round(flatness, 6),
        "kind": kind,
    }


def classify_role(
    duration: float,
    visual: dict[str, Any],
    audio: dict[str, Any],
    speech_ratio: float,
    novelty: float,
) -> str:
    if speech_ratio >= 0.35:
        return "dialogue"
    if duration <= 2.5 and novelty >= 0.45 and speech_ratio < 0.15:
        return "transition"
    if visual["motion"] >= 0.085 or duration < 1.2:
        return "action"
    if duration >= 3 and visual["motion"] < 0.055 and novelty >= 0.18:
        return "establishing"
    if duration <= 4 and visual["sharpness"] >= 0.085:
        return "detail"
    if audio["peak"] >= 0.75 and duration <= 4.5:
        return "reaction"
    return "ambient"


def score_shot(shot: dict[str, Any]) -> None:
    visual = shot["visual"]
    audio = shot["audio"]
    duration = shot["duration_sec"]
    novelty = shot["novelty_score"]
    exposure = clamp(
        1
        - max(
            (0.12 - visual["brightness"]) / 0.12,
            (visual["brightness"] - 0.9) / 0.1,
            0,
        )
    )
    sharpness = clamp((visual["sharpness"] - 0.025) / 0.11)
    duration_score = (
        0.15
        if duration < 0.35
        else 0.55
        if duration < 0.8
        else 1.0
        if duration <= 8
        else 0.78
        if duration <= 15
        else 0.55
    )
    quality = exposure * 0.35 + sharpness * 0.4 + duration_score * 0.25
    role_weight = {
        "dialogue": 0.14,
        "action": 0.12,
        "establishing": 0.1,
        "detail": 0.08,
        "transition": 0.04,
        "reaction": 0.16,
        "payoff": 0.18,
        "ambient": 0.02,
    }[shot["role"]]
    score = (
        0.27
        + quality * 0.32
        + min(1, novelty * 1.5) * 0.12
        + min(1, shot["speech_ratio"] * 1.6) * 0.08
        + min(1, visual["motion"] / 0.12) * 0.06
        + min(1, audio["peak"]) * 0.05
        + role_weight
    )
    reasons = role_reasons(shot["role"])
    if novelty >= 0.4:
        reasons.append("提供新的视觉信息")
    if audio["peak"] >= 0.7:
        reasons.append("包含声音或情绪峰值")
    if novelty < 0.075 and duration < 4 and shot["speech_ratio"] < 0.2:
        score -= 0.34
        reasons.append("与前一镜头高度重复")
    if sharpness < 0.2:
        score -= 0.18
        reasons.append("画面清晰度较低")
    if exposure < 0.25:
        score -= 0.18
        reasons.append("曝光异常")
    if shot["role"] == "ambient" and audio["kind"] == "silence":
        score -= 0.22
        reasons.append("缺少动作、声音和新增信息")
    score = round(clamp(score), 4)
    shot["quality_score"] = round(quality, 4)
    shot["keep_score"] = score
    shot["recommendation"] = (
        "protect"
        if score >= 0.78
        else "retain"
        if score >= 0.6
        else "optional"
        if score >= 0.4
        else "cut_first"
    )
    shot["reasons"] = reasons or ["缺少明确的保留或删除信号"]


def hash_distance(left: str | None, right: str) -> float:
    if not left:
        return 1.0
    width = max(len(left), len(right)) * 4
    return (int(left, 16) ^ int(right, 16)).bit_count() / width


def role_reasons(role: str) -> list[str]:
    return {
        "dialogue": ["包含可理解对白"],
        "action": ["包含明显动作变化"],
        "establishing": ["建立地点或场景关系"],
        "detail": ["提供清晰细节"],
        "reaction": ["完整人物反应"],
        "payoff": ["事件结果或情绪爆点"],
    }.get(role, [])


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
