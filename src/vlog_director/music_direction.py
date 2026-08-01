from __future__ import annotations

from typing import Any

from .enhancement import DEFAULT_MUSIC_DUCKING


DIALOGUE_ROLES = {"dialogue", "scenery_dialogue", "local_dialogue", "conversation"}
ROLE_DIRECTION = {
    "opening_preview": (0.95, "清晰、克制的启程感", "轻打击、短促脉冲、无主旋律抢占"),
    "opening": (0.90, "快速建立地点与旅程期待", "短促脉冲、轻打击、留出现场声"),
    "reveal": (0.84, "景观或信息揭示", "克制抬升、宽阔和声、避免夸张高潮"),
    "arrival": (0.80, "抵达与空间展开", "稳定推进、温暖低密度律动"),
    "culture": (0.66, "地方文化观察", "轻巧原声质感、低密度节奏点缀"),
    "people": (0.60, "人物互动与生活感", "温和轻节奏、不给对白制造竞争"),
    "humor": (0.58, "生活幽默", "短促轻巧点缀、禁止罐头喜剧感"),
    "transition": (0.82, "移动与空间转换", "轻节奏、柔和脉冲、低密度"),
    "journey": (0.78, "旅程推进", "稳定律动、轻电子或原声打击"),
    "action": (0.76, "行动推进", "轻快但不喧闹的节奏层"),
    "atmosphere": (0.72, "季节与地点质感", "稀疏氛围、空气感纹理"),
    "nature": (0.7, "自然沉浸", "极简氛围、长音色、保留环境声"),
    "scenery": (0.68, "景观展开", "缓慢铺陈、宽阔但克制"),
    "walk": (0.64, "步行与观察", "低强度节奏、温和律动"),
    "closing": (0.74, "情绪释放与收束", "简洁尾奏、逐步减法"),
    "local_detail": (0.58, "地方细节", "短小点缀、轻巧木质或拨弦音色"),
    "detail": (0.56, "信息发现", "短促轻巧、不过度喜剧化"),
}


ROLE_SEARCH_KEYWORDS = {
    "opening_preview": ["旅行开场", "轻快出发", "清新Vlog", "无歌词"],
    "opening": ["旅行开场", "启程", "清新Vlog", "轻节奏"],
    "transition": ["旅行转场", "城市移动", "轻快节奏", "无歌词"],
    "journey": ["公路旅行", "旅途感", "轻电子", "轻快"],
    "arrival": ["抵达城市", "温暖旅行", "治愈", "轻律动"],
    "reveal": ["风景揭晓", "辽阔氛围", "渐进感", "电影感"],
    "culture": ["地方日常", "原声木吉他", "轻松生活", "Vlog"],
    "people": ["日常互动", "温暖生活", "轻松", "低密度"],
    "humor": ["轻松俏皮", "生活感", "轻快", "短音乐"],
    "action": ["行动推进", "轻快节奏", "律动", "无歌词"],
    "atmosphere": ["旅行氛围", "空气感", "空灵", "轻音乐"],
    "nature": ["自然风景", "空灵氛围", "治愈", "无歌词"],
    "scenery": ["辽阔风景", "治愈氛围", "轻音乐", "无歌词"],
    "walk": ["城市漫步", "轻快", "治愈", "Vlog"],
    "closing": ["旅行收尾", "温暖治愈", "回忆感", "轻音乐"],
    "local_detail": ["生活细节", "轻巧原声", "木质感", "短音乐"],
    "detail": ["发现感", "轻巧", "原声", "短音乐"],
}

ROLE_RHYTHM = {
    "opening_preview": "中速，前2秒快速建立节奏",
    "opening": "中速，轻拍进入",
    "transition": "中速，稳定脉冲",
    "journey": "中速，持续推进",
    "arrival": "中速，温和推进",
    "reveal": "慢到中速，逐渐抬升",
    "culture": "中慢速，低密度",
    "people": "中慢速，节奏不要抢对白",
    "humor": "中速，短促点缀",
    "action": "中快，轻打击",
    "atmosphere": "慢速，弱节拍",
    "nature": "慢速，可无明显鼓点",
    "scenery": "慢速，长音铺陈",
    "walk": "中速，轻松律动",
    "closing": "中慢速，逐步收束",
    "local_detail": "中慢速，短小点缀",
    "detail": "中慢速，短小点缀",
}


def _reference_music_ratio(profile: dict[str, Any]) -> tuple[float, float, float]:
    ratios = profile.get("audio_model", {}).get("kind_ratios", {}).get("music_likely", {})
    minimum = float(ratios.get("minimum", 0.05))
    average = float(ratios.get("average", 0.11))
    maximum = float(ratios.get("maximum", 0.20))
    return max(0.0, minimum), min(0.22, max(0.06, average)), min(0.30, maximum)


def _timeline_segments(edit_plan: dict[str, Any]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    for chapter in edit_plan.get("chapters", []):
        for segment in chapter.get("segments", []):
            duration = float(segment["out_sec"]) - float(segment["in_sec"])
            timeline.append(
                {
                    "chapter_id": chapter["id"],
                    "chapter_title": chapter["title"],
                    "story_role": str(segment.get("story_role", "")),
                    "start_sec": round(cursor, 3),
                    "end_sec": round(cursor + duration, 3),
                    "duration_sec": round(duration, 3),
                    "source": segment["source"],
                    "keep_original_audio": bool(segment.get("keep_original_audio", True)),
                }
            )
            cursor += duration
    return timeline


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def _dialogue_intervals(
    edit_plan: dict[str, Any],
    subtitle_document: dict[str, Any] | None = None,
    padding_sec: float = 0.35,
) -> list[tuple[float, float]]:
    timeline = _timeline_segments(edit_plan)
    timeline_duration = sum(item["duration_sec"] for item in timeline)
    intervals = [
        (float(item["start_sec"]), float(item["end_sec"]))
        for item in timeline
        if item["story_role"] in DIALOGUE_ROLES or "dialogue" in item["story_role"]
    ]
    for cue in (subtitle_document or {}).get("cues", []):
        start = max(0.0, float(cue["start_sec"]) - padding_sec)
        end = min(timeline_duration, float(cue["end_sec"]) + padding_sec)
        intervals.append((start, end))
    return _merge_intervals(intervals)


def _available_subwindows(
    start: float,
    end: float,
    protected_intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    available: list[tuple[float, float]] = []
    cursor = start
    for protected_start, protected_end in protected_intervals:
        if protected_end <= cursor or protected_start >= end:
            continue
        if protected_start > cursor:
            available.append((cursor, min(protected_start, end)))
        cursor = max(cursor, protected_end)
        if cursor >= end:
            break
    if cursor < end:
        available.append((cursor, end))
    return [window for window in available if window[1] - window[0] >= 4.0]


def _eligible_windows(
    edit_plan: dict[str, Any],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    timeline = _timeline_segments(edit_plan)
    total_duration = max(sum(item["duration_sec"] for item in timeline), 0.001)
    context = profile.get("audio_model", {}).get("music_context_model", {})
    phase_ratios = context.get("phase_ratios", {})
    role_ratios = context.get("role_overlap_ratios", {})
    maximum_role_support = max((float(value) for value in role_ratios.values()), default=0.0)
    windows: list[dict[str, Any]] = []
    for segment in timeline:
        role = segment["story_role"]
        if role in DIALOGUE_ROLES or "dialogue" in role:
            continue
        direction = ROLE_DIRECTION.get(role)
        if not direction or segment["duration_sec"] < 2.5:
            continue
        midpoint = (segment["start_sec"] + segment["end_sec"]) / 2
        phase = (
            "opening"
            if midpoint <= min(15.0, total_duration * 0.15)
            else "closing"
            if midpoint >= total_duration * 0.85
            else "body"
        )
        base_score, mood, palette = direction
        phase_support = float(phase_ratios.get(phase, 0.0))
        role_support = float(role_ratios.get(role, 0.0))
        normalized_role_support = role_support / maximum_role_support if maximum_role_support else 0.0
        learned_score = min(1.0, base_score + phase_support * 0.08 + normalized_role_support * 0.08)
        windows.append(
            {
                **segment,
                "phase": phase,
                "score": learned_score,
                "base_score": base_score,
                "reference_phase_support": round(phase_support, 4),
                "reference_role_support": round(normalized_role_support, 4),
                "mood": mood,
                "palette": palette,
            }
        )
    return windows

def build_music_reference(
    edit_plan: dict[str, Any],
    profile: dict[str, Any],
    subtitle_document: dict[str, Any] | None = None,
    *,
    dialogue_padding_sec: float = 0.35,
) -> dict[str, Any]:
    timeline_duration = sum(item["duration_sec"] for item in _timeline_segments(edit_plan))
    protected_dialogue = _dialogue_intervals(
        edit_plan,
        subtitle_document,
        padding_sec=dialogue_padding_sec,
    )
    reference_min, reference_average, reference_max = _reference_music_ratio(profile)
    target_coverage = timeline_duration * reference_average
    selected: list[dict[str, Any]] = []
    used = 0.0
    chapter_used: set[str] = set()
    eligible = sorted(
        _eligible_windows(edit_plan, profile),
        key=lambda item: item["score"],
        reverse=True,
    )
    for window in eligible:
        if used >= target_coverage:
            break
        remaining = target_coverage - used
        preferred = 10.0 if window["story_role"] in {"opening", "opening_preview"} else 18.0
        available = _available_subwindows(
            float(window["start_sec"]),
            float(window["end_sec"]),
            protected_dialogue,
        )
        if not available:
            continue
        available_start, available_end = max(available, key=lambda item: item[1] - item[0])
        duration = min(available_end - available_start, preferred, remaining)
        if duration < 4.0:
            continue
        if window["chapter_id"] in chapter_used and window["story_role"] not in {
            "closing",
            "transition",
        }:
            continue
        role = window["story_role"]
        start = round(available_start, 3)
        end = round(available_start + duration, 3)
        selected.append(
            {
                "recommendation_id": f"music-{len(selected) + 1:02d}",
                "chapter_id": window["chapter_id"],
                "chapter_title": window["chapter_title"],
                "story_role": role,
                "start_sec": start,
                "end_sec": end,
                "duration_sec": round(end - start, 3),
                "purpose": window["mood"],
                "sound_direction": window["palette"],
                "capcut_search_keywords": ROLE_SEARCH_KEYWORDS.get(
                    role,
                    ["旅行Vlog", "轻音乐", "无歌词"],
                ),
                "energy": "low" if window["score"] < 0.7 else "medium",
                "rhythm_advice": ROLE_RHYTHM.get(role, "中慢速，低密度"),
                "entry_advice": "从画面动作或转场后轻轻淡入，不必强卡每个切点",
                "exit_advice": "在下一段对白或场景变化前淡出",
                "fade_in_sec": 1.2,
                "fade_out_sec": 1.8,
                "volume_reference_db": (
                    -24.0 if role in {"nature", "scenery", "closing", "atmosphere"} else -22.0
                ),
                "ambient_advice": "保留现场环境声，音乐只做情绪托底",
                "dialogue_advice": "该建议区间已避开当前字幕对白；实际添加时再试听确认",
                "optional": True,
                "reference_context": {
                    "phase": window["phase"],
                    "phase_support": window["reference_phase_support"],
                    "role_support": window["reference_role_support"],
                },
            }
        )
        used += duration
        chapter_used.add(window["chapter_id"])

    selected.sort(key=lambda item: item["start_sec"])
    for index, item in enumerate(selected, start=1):
        item["recommendation_id"] = f"music-{index:02d}"
    actual_ratio = used / max(timeline_duration, 0.001)
    return {
        "schema_version": "1.0",
        "output_kind": "non_blocking_music_reference",
        "non_blocking": True,
        "project_id": edit_plan.get("project_id"),
        "edit_plan_version": edit_plan.get("version"),
        "status": "reference_ready" if selected else "no_music_suggestion",
        "usage": "画面设计完成后的配乐参考；由用户在剪映中自行搜索、试听和添加，不影响画面版本发布。",
        "reference_evidence": {
            "profile_id": profile.get("profile_id"),
            "source_count": profile.get("source_count"),
            "music_coverage_ratio": {
                "minimum": reference_min,
                "average": reference_average,
                "maximum": reference_max,
            },
            "interpretation": "参考片统计只帮助判断哪里适合有音乐、哪里适合留白。",
        },
        "timeline_duration_sec": round(timeline_duration, 3),
        "suggested_coverage_ratio": round(actual_ratio, 4),
        "dialogue_evidence": {
            "subtitle_cue_count": len((subtitle_document or {}).get("cues", [])),
            "subtitle_padding_sec": dialogue_padding_sec,
            "includes_story_role_intervals": True,
        },
        "dialogue_intervals": [
            {"start_sec": start, "end_sec": end}
            for start, end in protected_dialogue
        ],
        "recommendations": selected,
    }


def build_music_intent(
    edit_plan: dict[str, Any],
    profile: dict[str, Any],
    subtitle_document: dict[str, Any] | None = None,
    *,
    dialogue_padding_sec: float = 0.35,
) -> dict[str, Any]:
    """Compatibility alias; the result is advisory and never a release gate."""
    return build_music_reference(
        edit_plan,
        profile,
        subtitle_document,
        dialogue_padding_sec=dialogue_padding_sec,
    )


def to_enhancement_music(reference: dict[str, Any]) -> dict[str, Any]:
    """Create a schema-compatible executable music stub.

    Advisory search guidance stays in the separate reference document. A user
    must select local audio and add executable tracks before marking this block
    ready.
    """
    return {
        "status": "planned" if reference.get("recommendations") else "disabled",
        "tracks": [],
        "ducking": dict(DEFAULT_MUSIC_DUCKING),
    }
