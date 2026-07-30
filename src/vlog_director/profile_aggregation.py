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
        "learning_memory": build_learning_memory(
            analyses,
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
            "music_context_model": music_context_model(analyses),
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


def music_context_model(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    phase_duration = Counter()
    role_duration = Counter()
    total_music = 0.0
    speech_overlap = 0.0
    segment_count = 0
    for analysis in analyses:
        duration = float(analysis.get("media", {}).get("duration_sec", 0.0))
        if duration <= 0:
            duration = max(
                (float(shot["end_sec"]) for shot in analysis.get("shots", [])),
                default=0.0,
            )
        shots = analysis.get("shots", [])
        for segment in analysis.get("audio_segments", []):
            if segment.get("kind") != "music_likely":
                continue
            start = float(segment["start_sec"])
            end = float(segment["end_sec"])
            segment_duration = max(0.0, end - start)
            if segment_duration <= 0:
                continue
            segment_count += 1
            total_music += segment_duration
            midpoint = (start + end) / 2
            phase = (
                "opening"
                if midpoint <= min(15.0, duration * 0.15)
                else "closing"
                if duration and midpoint >= duration * 0.85
                else "body"
            )
            phase_duration[phase] += segment_duration
            for shot in shots:
                overlap = max(
                    0.0,
                    min(end, float(shot["end_sec"]))
                    - max(start, float(shot["start_sec"])),
                )
                if overlap <= 0:
                    continue
                role_duration[str(shot.get("role", "ambient"))] += overlap
                if (
                    str(shot.get("role")) == "dialogue"
                    or float(shot.get("speech_ratio", 0.0)) >= 0.3
                ):
                    speech_overlap += overlap
    denominator = max(total_music, 0.001)
    return {
        "segment_count": segment_count,
        "phase_ratios": {
            phase: round(phase_duration.get(phase, 0.0) / denominator, 4)
            for phase in ("opening", "body", "closing")
        },
        "role_overlap_ratios": {
            role: round(value / denominator, 4)
            for role, value in role_duration.most_common()
        },
        "speech_overlap_ratio": round(min(1.0, speech_overlap / denominator), 4),
        "evidence_note": (
            "music_likely is an acoustic estimate; context ratios guide placement "
            "and sparsity but do not identify songs or prove editorial intent."
        ),
    }


def load_analysis(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def load_profile(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _profile_source_ids(profile: dict[str, Any]) -> set[str]:
    sources = profile.get("reference_sources") or profile.get("sources") or []
    return {
        str(source.get("source_id") or source.get("url"))
        for source in sources
        if source.get("source_id") or source.get("url")
    }


def aggregate_semantic_principles(
    profiles: list[dict[str, Any]],
    support_threshold: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for profile_index, profile in enumerate(profiles, start=1):
        profile_id = str(profile.get("profile_id") or f"profile-{profile_index}")
        profile_sources = _profile_source_ids(profile) or {profile_id}
        for principle in profile.get("principles", []):
            explicit_sources = {
                str(value) for value in principle.get("source_ids", []) if value
            }
            grouped.setdefault(str(principle["id"]), []).append(
                {
                    "principle": principle,
                    "source_ids": explicit_sources or profile_sources,
                    "profile_id": profile_id,
                }
            )

    aggregated = []
    for principle_id, entries in sorted(grouped.items()):
        source_ids = set().union(*(entry["source_ids"] for entry in entries))
        if len(source_ids) < support_threshold:
            continue
        principles = [entry["principle"] for entry in entries]
        aggregated.append(
            {
                "id": principle_id,
                "source_support": len(source_ids),
                "source_ids": sorted(source_ids),
                "profile_support": len({entry["profile_id"] for entry in entries}),
                "average_confidence": round(
                    mean(float(row.get("confidence", 0.5)) for row in principles),
                    4,
                ),
                "rule": max(principles, key=lambda row: len(str(row["rule"])))['rule'],
                "source_variants": list(
                    dict.fromkeys(str(row["rule"]) for row in principles)
                ),
            }
        )
    return aggregated


def build_learning_memory(
    analyses: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    support_threshold: int,
) -> dict[str, Any]:
    principles = aggregate_semantic_principles(profiles, support_threshold)
    principle_ids = {str(item["id"]) for item in principles}
    reference_ids = {
        str(analysis.get("source", {}).get("source_id", ""))
        for analysis in analyses
        if analysis.get("source", {}).get("source_id")
    }
    return {
        "precedence": [
            "explicit_user_feedback",
            "target_footage_evidence",
            "cross_reference_patterns",
            "source_specific_patterns",
        ],
        "content_model": {
            "separate_scores": ["scenic_score", "fun_score"],
            "preference_weights": {"scenic": 1.0, "fun": 1.0},
            "event_chain": ["setup", "trigger", "payoff", "reaction", "callback"],
            "evidence_rules": sorted(
                principle_ids
                & {
                    "seasonal-place-texture",
                    "preserve-complete-event-chain",
                    "dialogue-is-story-structure",
                }
            ),
        },
        "editing_model": {
            "candidate_directions": {
                "concise": "fun_forward",
                "balanced": "scenic_fun_balanced",
                "immersive": "scenic_forward",
            },
            "uses_target_analysis": True,
            "requires_timeline_change": True,
            "reference_source_count": len(reference_ids),
        },
        "effect_model": {
            "non_blocking": True,
            "eligible_only_after_fun_event": True,
            "default_max_primary_effects_per_event": 1,
            "safe_zones": ["faces", "main_subject", "subtitles"],
            "style_status": "awaiting_user_reference_videos",
            "evidence_rules": sorted(
                principle_ids & {"restrained-information-graphics"}
            ),
        },
        "feedback_model": {
            "accepted_decisions": [
                "prefer",
                "restore",
                "extend",
                "avoid",
                "remove",
                "shorten",
                "lock",
            ],
            "feedback_overrides_reference_priors": True,
            "versioned": True,
        },
        "limitations": [
            "Final reference videos provide positive retained-pattern evidence only.",
            "Learning true deletion preference requires raw footage, final edit, and EDL mapping.",
            "Scenic and fun scores require target evidence or explicit human annotation.",
        ],
    }


def write_aggregate(profile: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
