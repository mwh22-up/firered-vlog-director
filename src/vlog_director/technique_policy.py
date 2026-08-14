from __future__ import annotations

from typing import Any

from .technique_learning import validate_technique_aggregate


HUMOR_AWKWARD_PROCESS = "humor-preserve-real-awkward-process"
OPENING_PHASED_HOOK = "opening-phased-hook-not-uniform-fast-cut"
TRAVEL_COMPRESSION_PREVIEW = (
    "playback-rate-fast-forward-travel-compression-visual-estimate"
)
MINIMUM_EXECUTABLE_SOURCE_SUPPORT = 2

EXECUTABLE_RULES = {
    HUMOR_AWKWARD_PROCESS: {
        "category": "humor",
        "executor": "retain_evidence_backed_fun_process",
        "execution_mode": "automatic_candidate",
        "required_target_evidence": "explicit_fun_score>=0.55",
    },
    OPENING_PHASED_HOOK: {
        "category": "opening_montage",
        "executor": "build_evidence_backed_phased_opening",
        "execution_mode": "automatic_candidate",
        "required_target_evidence": (
            "non_dialogue future_payoff+human_context+action_progression shots"
        ),
        "minimum_average_confidence": 0.8,
    },
    TRAVEL_COMPRESSION_PREVIEW: {
        "category": "playback_rate",
        "executor": "propose_travel_compression_preview",
        "execution_mode": "preview_only",
        "required_target_evidence": (
            "continuous travel shot>=8s, speech_ratio<=0.1, visual.motion>=0.085"
        ),
        "minimum_average_confidence": 0.4,
    },
}


def empty_technique_policy() -> dict[str, Any]:
    return {
        "profile_id": None,
        "source_count": 0,
        "minimum_source_support": None,
        "stable_pattern_count": 0,
        "source_specific_pattern_count": 0,
        "rules": {
            "humor_awkward_process": {
                "active": False,
                "technique_key": HUMOR_AWKWARD_PROCESS,
                "executor": EXECUTABLE_RULES[HUMOR_AWKWARD_PROCESS]["executor"],
            },
            "opening_phased_hook": {
                "active": False,
                "technique_key": OPENING_PHASED_HOOK,
                "executor": EXECUTABLE_RULES[OPENING_PHASED_HOOK]["executor"],
                "execution_mode": "automatic_candidate",
            },
            "travel_compression_preview": {
                "active": False,
                "technique_key": TRAVEL_COMPRESSION_PREVIEW,
                "executor": EXECUTABLE_RULES[TRAVEL_COMPRESSION_PREVIEW]["executor"],
                "execution_mode": "preview_only",
            },
        },
        "eligible_patterns": [],
        "guidance_patterns": [],
    }


def _trace(
    pattern: dict[str, Any],
    executor: str,
    *,
    pattern_scope: str,
    required_target_evidence: str | None = None,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    trace = {
        "technique_key": str(pattern["technique_key"]),
        "category": str(pattern["category"]),
        "source_support": int(pattern["source_support"]),
        "average_confidence": float(pattern["average_confidence"]),
        "pattern_scope": pattern_scope,
        "executor": executor,
        "guardrail_variants": list(pattern.get("guardrail_variants", [])),
    }
    if required_target_evidence:
        trace["required_target_evidence"] = required_target_evidence
    if execution_mode:
        trace["execution_mode"] = execution_mode
    return trace


def build_technique_policy(
    aggregate: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map only explicitly supported stable patterns to target-evidence rules.

    Every non-allowlisted stable pattern, plus every source-specific pattern,
    remains guidance until the target analyzer can prove a supported semantic
    trigger. This prevents reference edits from being copied onto unrelated
    footage.
    """
    if aggregate is None:
        return empty_technique_policy()
    validate_technique_aggregate(aggregate)

    patterns = {
        str(pattern["technique_key"]): pattern
        for pattern in aggregate["stable_patterns"]
    }
    executable_patterns = {
        key: pattern
        for key, pattern in patterns.items()
        if key in EXECUTABLE_RULES
        and int(pattern["source_support"]) >= MINIMUM_EXECUTABLE_SOURCE_SUPPORT
        and str(pattern["category"]) == str(EXECUTABLE_RULES[key]["category"])
        and float(pattern["average_confidence"])
        >= float(EXECUTABLE_RULES[key].get("minimum_average_confidence", 0.0))
    }
    eligible = [
        _trace(
            executable_patterns[key],
            str(rule["executor"]),
            pattern_scope="stable",
            required_target_evidence=str(rule["required_target_evidence"]),
            execution_mode=str(rule["execution_mode"]),
        )
        for key, rule in EXECUTABLE_RULES.items()
        if key in executable_patterns
    ]
    guidance = sorted(
        [
            _trace(
                pattern,
                "downstream_guidance",
                pattern_scope="stable",
            )
            for key, pattern in patterns.items()
            if key not in executable_patterns
        ]
        + [
            _trace(
                pattern,
                "downstream_guidance",
                pattern_scope="source_specific",
            )
            for pattern in aggregate["source_specific_patterns"]
        ],
        key=lambda row: (str(row["pattern_scope"]), str(row["technique_key"])),
    )

    humor_pattern = executable_patterns.get(HUMOR_AWKWARD_PROCESS)
    opening_pattern = executable_patterns.get(OPENING_PHASED_HOOK)
    travel_compression_pattern = executable_patterns.get(
        TRAVEL_COMPRESSION_PREVIEW
    )
    # Observation confidence describes evidence quality, not transfer strength.
    # Keep the allowlisted effect fixed and deliberately small.
    humor_multiplier = 1.1 if humor_pattern else 1.0
    return {
        "profile_id": str(aggregate["profile_id"]),
        "source_count": int(aggregate["source_count"]),
        "minimum_source_support": int(aggregate["minimum_source_support"]),
        "stable_pattern_count": len(aggregate["stable_patterns"]),
        "source_specific_pattern_count": len(aggregate["source_specific_patterns"]),
        "rules": {
            "humor_awkward_process": {
                "active": humor_pattern is not None,
                "technique_key": HUMOR_AWKWARD_PROCESS,
                "category": "humor",
                "executor": EXECUTABLE_RULES[HUMOR_AWKWARD_PROCESS]["executor"],
                "minimum_fun_score": 0.55,
                "weight_multiplier": humor_multiplier,
                "source_support": (
                    int(humor_pattern["source_support"])
                    if humor_pattern
                    else 0
                ),
                "average_confidence": (
                    float(humor_pattern["average_confidence"])
                    if humor_pattern
                    else 0.0
                ),
            },
            "opening_phased_hook": {
                "active": opening_pattern is not None,
                "technique_key": OPENING_PHASED_HOOK,
                "category": "opening_montage",
                "executor": EXECUTABLE_RULES[OPENING_PHASED_HOOK]["executor"],
                "execution_mode": "automatic_candidate",
                "minimum_phase_count": 3,
                "maximum_phase_count": 5,
                "minimum_shot_sec": 0.8,
                "maximum_speech_ratio": 0.2,
                "minimum_shot_score": 0.62,
                "source_support": (
                    int(opening_pattern["source_support"])
                    if opening_pattern
                    else 0
                ),
                "average_confidence": (
                    float(opening_pattern["average_confidence"])
                    if opening_pattern
                    else 0.0
                ),
            },
            "travel_compression_preview": {
                "active": travel_compression_pattern is not None,
                "technique_key": TRAVEL_COMPRESSION_PREVIEW,
                "category": "playback_rate",
                "executor": EXECUTABLE_RULES[TRAVEL_COMPRESSION_PREVIEW]["executor"],
                "execution_mode": "preview_only",
                "minimum_shot_sec": 8.0,
                "maximum_speech_ratio": 0.1,
                "minimum_motion": 0.085,
                "allowed_roles": ["action", "transition"],
                "playback_rate": None,
                "requires_human_rate_selection": True,
                "source_support": (
                    int(travel_compression_pattern["source_support"])
                    if travel_compression_pattern
                    else 0
                ),
                "average_confidence": (
                    float(travel_compression_pattern["average_confidence"])
                    if travel_compression_pattern
                    else 0.0
                ),
            },
        },
        "eligible_patterns": eligible,
        "guidance_patterns": guidance,
    }
