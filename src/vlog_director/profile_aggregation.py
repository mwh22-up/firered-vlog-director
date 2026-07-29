from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


def aggregate_analyses(
    analyses: list[dict[str, Any]],
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not analyses:
        raise ValueError("at least one reference analysis is required")
    support_threshold = math.ceil(len(analyses) / 2)
    role_rows = aggregate_roles(analyses)
    shared_rules = infer_shared_rules(
        analyses,
        role_rows,
        support_threshold,
    )
    return {
        "schema_version": "1.0",
        "profile_id": "aggregated-reference-director-v1",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(analyses),
        "reference_sources": [
            analysis["source"]
            for analysis in analyses
        ],
        "shared_rules": shared_rules,
        "semantic_principles": aggregate_semantic_principles(
            profiles or [],
            support_threshold,
        ),
        "shot_selection_model": {
            "retain_archetypes": [
                row
                for row in role_rows
                if row["source_support"] >= support_threshold
                and row["average_keep_score"] >= 0.68
                and row["average_retained_ratio"] >= 0.35
            ],
            "selective_archetypes": [
                row
                for row in role_rows
                if row["source_support"] >= support_threshold
                and row["average_keep_score"] >= 0.68
                and row["average_retained_ratio"] < 0.35
            ],
            "cut_first_signals": aggregate_cut_signals(
                analyses,
                support_threshold,
            ),
            "sequence_dependencies": [
                "建立镜头、行动或信息、结果、人物反应应作为镜头组评估。",
                "存在 payoff 或 reaction 时，不应仅保留爆点而删除铺垫。",
                "事件完整度优先于单镜头分数，完整事件可提升边缘镜头的保留级别。"
            ],
        },
        "pacing_model": {
            "median_shot_duration_sec": metric_range(
                analyses,
                "median_shot_duration_sec",
            ),
            "opening_average_shot_duration_sec": opening_range(analyses),
            "silent_ratio": metric_range(analyses, "silent_ratio"),
        },
        "audio_model": {
            "kind_ratios": aggregate_audio_ratios(analyses),
            "music_segment_duration_sec": music_segment_range(analyses),
            "rule": "对白区间优先保留原声；可能配乐用于跨镜头托底；环境声承担地点质感；静音仅用于有意停顿。"
        },
        "source_variants": [
            source_variant(analysis)
            for analysis in analyses
        ],
        "limitations": [
            "聚合结果来自已经完成剪辑的参考片，不包含原始废片。",
            "真正的保留与删除监督学习需要原始素材、最终成片和时间线映射。",
            "自动镜头角色是启发式判断，低置信度结果必须通过事件联系表人工抽查。"
        ],
    }


def aggregate_roles(
    analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for analysis in analyses:
        for row in analysis["learning_summary"]["retention_archetypes"]:
            grouped.setdefault(row["role"], []).append(row)
    return [
        {
            "role": role,
            "source_support": len(rows),
            "shot_count": sum(row["shot_count"] for row in rows),
            "average_retained_ratio": round(
                mean(row["retained_ratio"] for row in rows),
                4,
            ),
            "average_duration_sec": round(
                mean(row["average_duration_sec"] for row in rows),
                3,
            ),
            "average_keep_score": round(
                mean(row["average_keep_score"] for row in rows),
                4,
            ),
        }
        for role, rows in sorted(grouped.items())
    ]


def aggregate_cut_signals(
    analyses: list[dict[str, Any]],
    support_threshold: int,
) -> list[dict[str, Any]]:
    support = Counter()
    shot_counts = Counter()
    for analysis in analyses:
        seen = set()
        for row in analysis["learning_summary"]["cut_first_signals"]:
            signal = row["signal"]
            shot_counts[signal] += row["shot_count"]
            seen.add(signal)
        support.update(seen)
    return [
        {
            "signal": signal,
            "source_support": support[signal],
            "shot_count": shot_counts[signal],
        }
        for signal in sorted(support)
        if support[signal] >= support_threshold
    ]


def infer_shared_rules(
    analyses: list[dict[str, Any]],
    role_rows: list[dict[str, Any]],
    support_threshold: int,
) -> list[dict[str, Any]]:
    rules = []
    role_labels = {
        "action": "动作推进",
        "ambient": "环境停留",
        "detail": "关键细节",
        "dialogue": "有效对白",
        "establishing": "环境建立",
        "payoff": "结果或爆点",
        "reaction": "人物反应",
        "transition": "章节过渡",
    }
    fast_openings = sum(
        analysis["media"]["opening_15_sec"]["average_shot_duration_sec"]
        < analysis["media"]["median_shot_duration_sec"] * 0.8
        for analysis in analyses
    )
    if fast_openings >= support_threshold:
        rules.append(
            {
                "id": "opening-faster-than-body",
                "source_support": fast_openings,
                "rule": "开场15秒应明显快于正文，用跨地点和跨体验镜头建立观看承诺。"
            }
        )
    continuous_audio = sum(
        analysis["media"]["silent_ratio"] < 0.05
        for analysis in analyses
    )
    if continuous_audio >= support_threshold:
        rules.append(
            {
                "id": "continuous-audio-bed",
                "source_support": continuous_audio,
                "rule": "对白、环境声或配乐应持续托底，避免没有叙事目的的声音空洞。"
            }
        )
    for row in role_rows:
        if (
            row["source_support"] >= support_threshold
            and row["average_keep_score"] >= 0.68
            and row["average_retained_ratio"] >= 0.35
        ):
            rules.append(
                {
                    "id": f"retain-{row['role']}",
                    "source_support": row["source_support"],
                    "rule": (
                        f"优先保留承担{role_labels[row['role']]}功能"
                        "且质量合格的镜头。"
                    )
                }
            )
        elif (
            row["source_support"] >= support_threshold
            and row["average_keep_score"] >= 0.68
        ):
            rules.append(
                {
                    "id": f"selective-{row['role']}",
                    "source_support": row["source_support"],
                    "rule": (
                        f"{role_labels[row['role']]}镜头只在提供新信息、完成事件结构"
                        "或承担必要过渡时保留。"
                    )
                }
            )
    core_roles = {
        row["role"]
        for row in role_rows
        if row["source_support"] >= support_threshold
        and row["average_retained_ratio"] >= 0.35
    }
    if {"action", "dialogue", "reaction"}.issubset(core_roles):
        rules.append(
            {
                "id": "preserve-event-chain",
                "source_support": len(analyses),
                "rule": "镜头必须放回事件链判断：铺垫、行动、结果和人物反应应成组保留，不能只留下单个漂亮镜头或爆点。"
            }
        )
    return rules


def metric_range(
    analyses: list[dict[str, Any]],
    key: str,
) -> dict[str, float]:
    values = [float(analysis["media"][key]) for analysis in analyses]
    return {
        "minimum": round(min(values), 4),
        "average": round(mean(values), 4),
        "maximum": round(max(values), 4),
    }


def opening_range(
    analyses: list[dict[str, Any]],
) -> dict[str, float]:
    values = [
        float(
            analysis["media"]["opening_15_sec"]["average_shot_duration_sec"]
        )
        for analysis in analyses
    ]
    return {
        "minimum": round(min(values), 4),
        "average": round(mean(values), 4),
        "maximum": round(max(values), 4),
    }


def source_variant(analysis: dict[str, Any]) -> dict[str, Any]:
    event_types = Counter(
        event["event_type"]
        for event in analysis["events"]
    )
    top_roles = sorted(
        analysis["learning_summary"]["retention_archetypes"],
        key=lambda row: row["average_keep_score"],
        reverse=True,
    )[:3]
    return {
        "source_id": analysis["source"]["source_id"],
        "median_shot_duration_sec": analysis["media"][
            "median_shot_duration_sec"
        ],
        "top_retained_roles": [row["role"] for row in top_roles],
        "dominant_event_types": [
            event_type
            for event_type, _ in event_types.most_common(3)
        ],
    }


def aggregate_audio_ratios(
    analyses: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    kinds = sorted(
        {
            kind
            for analysis in analyses
            for kind in analysis["media"].get("audio_kind_ratios", {})
        }
    )
    return {
        kind: {
            "minimum": round(min(values), 4),
            "average": round(mean(values), 4),
            "maximum": round(max(values), 4),
        }
        for kind in kinds
        if (
            values := [
                float(
                    analysis["media"]
                    .get("audio_kind_ratios", {})
                    .get(kind, 0)
                )
                for analysis in analyses
            ]
        )
    }


def music_segment_range(
    analyses: list[dict[str, Any]],
) -> dict[str, float]:
    values = []
    for analysis in analyses:
        durations = [
            segment["end_sec"] - segment["start_sec"]
            for segment in analysis.get("audio_segments", [])
            if segment["kind"] == "music_likely"
        ]
        values.append(mean(durations) if durations else 0.0)
    return {
        "minimum": round(min(values), 4),
        "average": round(mean(values), 4),
        "maximum": round(max(values), 4),
    }


def load_analysis(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def load_profile(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def aggregate_semantic_principles(
    profiles: list[dict[str, Any]],
    support_threshold: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for profile in profiles:
        for principle in profile.get("principles", []):
            grouped.setdefault(principle["id"], []).append(principle)
    return [
        {
            "id": principle_id,
            "source_support": len(rows),
            "average_confidence": round(
                mean(float(row["confidence"]) for row in rows),
                4,
            ),
            "rule": max(rows, key=lambda row: len(row["rule"]))["rule"],
            "source_variants": [row["rule"] for row in rows],
        }
        for principle_id, rows in sorted(grouped.items())
        if len(rows) >= support_threshold
    ]


def write_aggregate(profile: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
