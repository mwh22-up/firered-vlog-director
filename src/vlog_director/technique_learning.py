from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

TECHNIQUE_CATEGORIES = {
    "opening_montage",
    "music_rhythm",
    "scenic",
    "narrative",
    "subtitle",
    "graphic",
    "humor",
    "playback_rate",
    "sound_effect",
}

AGGREGATE_KEYS = {
    "schema_version",
    "profile_id",
    "generated_at",
    "source_count",
    "source_ids",
    "minimum_source_support",
    "stable_patterns",
    "source_specific_patterns",
    "opening_recipes",
    "model_context_policy",
    "limitations",
}
PATTERN_KEYS = {
    "technique_key",
    "category",
    "source_support",
    "source_ids",
    "average_confidence",
    "trigger_examples",
    "treatment_examples",
    "parameter_variants",
    "guardrail_variants",
    "evidence_ranges",
}


def validate_technique_study(study: dict[str, Any]) -> None:
    source = study.get("source", {})
    source_id = str(source.get("source_id", "")).strip()
    if not source_id:
        raise ValueError("technique study source.source_id is required")
    observations = study.get("technique_observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("technique study requires technique_observations")
    seen = set()
    for observation in observations:
        observation_id = str(observation.get("observation_id", "")).strip()
        if not observation_id or observation_id in seen:
            raise ValueError("observation_id must be present and unique")
        seen.add(observation_id)
        category = str(observation.get("category", ""))
        if category not in TECHNIQUE_CATEGORIES:
            raise ValueError(f"unsupported technique category: {category}")
        if not str(observation.get("technique_key", "")).strip():
            raise ValueError("technique_key is required")
        start = float(observation.get("start_sec", -1.0))
        end = float(observation.get("end_sec", -1.0))
        if start < 0 or end <= start:
            raise ValueError("observation time range must be positive")
        confidence = float(observation.get("confidence", -1.0))
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("observation confidence must be between 0 and 1")
        if not str(observation.get("trigger", "")).strip():
            raise ValueError("observation trigger is required")
        if not str(observation.get("treatment", "")).strip():
            raise ValueError("observation treatment is required")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    return [_require_string(item, f"{label} item") for item in value]


def _reject_unknown_keys(
    document: dict[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {', '.join(unknown)}")


def validate_technique_aggregate(aggregate: dict[str, Any]) -> None:
    if not isinstance(aggregate, dict):
        raise ValueError("technique aggregate must be an object")
    _reject_unknown_keys(aggregate, AGGREGATE_KEYS, "technique aggregate")
    if aggregate.get("schema_version") != "1.0":
        raise ValueError("technique aggregate schema_version must be 1.0")
    _require_string(aggregate.get("profile_id"), "technique aggregate profile_id")
    if "generated_at" in aggregate:
        _require_string(aggregate["generated_at"], "technique aggregate generated_at")

    source_ids = _require_string_list(
        aggregate.get("source_ids"),
        "technique aggregate source_ids",
    )
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise ValueError("technique aggregate source_ids must be present and unique")
    source_count = _require_integer(
        aggregate.get("source_count"),
        "technique aggregate source_count",
        minimum=1,
    )
    if source_count != len(source_ids):
        raise ValueError("technique aggregate source_count must match source_ids")
    minimum_support = _require_integer(
        aggregate.get("minimum_source_support"),
        "technique aggregate minimum_source_support",
        minimum=1,
    )
    if not 1 <= minimum_support <= source_count:
        raise ValueError("technique aggregate minimum_source_support is invalid")
    model_context_policy = aggregate.get("model_context_policy")
    if not isinstance(model_context_policy, dict):
        raise ValueError("technique aggregate model_context_policy is required")
    _reject_unknown_keys(
        model_context_policy,
        {"default_maximum_characters", "hard_limit_characters", "comparison"},
        "technique aggregate model_context_policy",
    )
    default_limit = _require_integer(
        model_context_policy.get("default_maximum_characters"),
        "model context default_maximum_characters",
        minimum=1,
    )
    hard_limit = _require_integer(
        model_context_policy.get("hard_limit_characters"),
        "model context hard_limit_characters",
        minimum=2,
    )
    if (
        hard_limit <= default_limit
        or model_context_policy.get("comparison") != "strictly_less_than"
    ):
        raise ValueError("technique aggregate model_context_policy is invalid")
    _require_string_list(
        aggregate.get("limitations"),
        "technique aggregate limitations",
    )

    known_sources = set(source_ids)
    opening_recipes = aggregate.get("opening_recipes", [])
    if not isinstance(opening_recipes, list):
        raise ValueError("technique aggregate opening_recipes must be a list")
    opening_sources: set[str] = set()
    for recipe in opening_recipes:
        if not isinstance(recipe, dict):
            raise ValueError("technique aggregate opening recipe must be an object")
        recipe_source = _require_string(
            recipe.get("source_id"),
            "technique aggregate opening recipe source_id",
        )
        if recipe_source not in known_sources or recipe_source in opening_sources:
            raise ValueError("technique aggregate opening recipe source is inconsistent")
        opening_sources.add(recipe_source)

    seen_keys: set[str] = set()
    pattern_groups = (
        ("stable_patterns", True),
        ("source_specific_patterns", False),
    )
    for group_name, stable in pattern_groups:
        patterns = aggregate.get(group_name)
        if not isinstance(patterns, list):
            raise ValueError(f"technique aggregate {group_name} must be a list")
        for pattern in patterns:
            if not isinstance(pattern, dict):
                raise ValueError(f"technique aggregate {group_name} item must be an object")
            _reject_unknown_keys(pattern, PATTERN_KEYS, "technique aggregate pattern")
            key = _require_string(
                pattern.get("technique_key"),
                "aggregate technique_key",
            )
            if key in seen_keys:
                raise ValueError("aggregate technique_key must be present and unique")
            seen_keys.add(key)
            category = _require_string(
                pattern.get("category"),
                f"aggregate pattern {key} category",
            )
            if category not in TECHNIQUE_CATEGORIES:
                raise ValueError(f"unsupported aggregate technique category: {pattern.get('category')}")
            pattern_sources = _require_string_list(
                pattern.get("source_ids"),
                f"aggregate pattern {key} source_ids",
            )
            if not pattern_sources or len(pattern_sources) != len(set(pattern_sources)):
                raise ValueError(f"aggregate pattern {key} source_ids must be unique")
            if not set(pattern_sources) <= known_sources:
                raise ValueError(f"aggregate pattern {key} references an unknown source")
            support = _require_integer(
                pattern.get("source_support"),
                f"aggregate pattern {key} source_support",
                minimum=1,
            )
            if support != len(pattern_sources):
                raise ValueError(f"aggregate pattern {key} source_support is inconsistent")
            if stable and support < minimum_support:
                raise ValueError(f"stable pattern {key} is below minimum source support")
            if not stable and support >= minimum_support:
                raise ValueError(f"source-specific pattern {key} meets stable support")
            confidence = _require_number(
                pattern.get("average_confidence"),
                f"aggregate pattern {key} average_confidence",
            )
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"aggregate pattern {key} confidence is invalid")
            _require_string_list(
                pattern.get("trigger_examples"),
                f"aggregate pattern {key} trigger_examples",
            )
            _require_string_list(
                pattern.get("treatment_examples"),
                f"aggregate pattern {key} treatment_examples",
            )
            parameter_variants = pattern.get("parameter_variants")
            if not isinstance(parameter_variants, list):
                raise ValueError(f"aggregate pattern {key} parameter_variants must be a list")
            parameter_sources: set[str] = set()
            for variant in parameter_variants:
                if not isinstance(variant, dict):
                    raise ValueError(f"aggregate pattern {key} parameter variant must be an object")
                variant_source = _require_string(
                    variant.get("source_id"),
                    f"aggregate pattern {key} parameter source_id",
                )
                if variant_source not in pattern_sources or variant_source in parameter_sources:
                    raise ValueError(f"aggregate pattern {key} parameter source is inconsistent")
                parameter_sources.add(variant_source)
            if parameter_sources != set(pattern_sources):
                raise ValueError(f"aggregate pattern {key} parameter sources are incomplete")
            evidence_ranges = pattern.get("evidence_ranges")
            if not isinstance(evidence_ranges, list) or len(evidence_ranges) != support:
                raise ValueError(f"aggregate pattern {key} evidence_ranges are inconsistent")
            evidence_sources: set[str] = set()
            evidence_observations: dict[str, str] = {}
            for evidence in evidence_ranges:
                if not isinstance(evidence, dict):
                    raise ValueError(f"aggregate pattern {key} evidence must be an object")
                _reject_unknown_keys(
                    evidence,
                    {"source_id", "start_sec", "end_sec", "observation_id"},
                    f"aggregate pattern {key} evidence",
                )
                evidence_source = _require_string(
                    evidence.get("source_id"),
                    f"aggregate pattern {key} evidence source_id",
                )
                if evidence_source not in pattern_sources or evidence_source in evidence_sources:
                    raise ValueError(f"aggregate pattern {key} evidence source is inconsistent")
                evidence_sources.add(evidence_source)
                start = _require_number(
                    evidence.get("start_sec"),
                    f"aggregate pattern {key} evidence start_sec",
                )
                end = _require_number(
                    evidence.get("end_sec"),
                    f"aggregate pattern {key} evidence end_sec",
                )
                if start < 0 or end <= start:
                    raise ValueError(f"aggregate pattern {key} evidence range is invalid")
                evidence_observations[evidence_source] = _require_string(
                    evidence.get("observation_id"),
                    f"aggregate pattern {key} observation_id",
                )
            guardrail_variants = pattern.get("guardrail_variants")
            if not isinstance(guardrail_variants, list):
                raise ValueError(f"aggregate pattern {key} guardrail_variants must be a list")
            guardrail_sources: set[str] = set()
            for variant in guardrail_variants:
                if not isinstance(variant, dict):
                    raise ValueError(f"aggregate pattern {key} guardrail variant must be an object")
                _reject_unknown_keys(
                    variant,
                    {"source_id", "observation_id", "guardrails"},
                    f"aggregate pattern {key} guardrail variant",
                )
                variant_source = _require_string(
                    variant.get("source_id"),
                    f"aggregate pattern {key} guardrail source_id",
                )
                if variant_source not in pattern_sources:
                    raise ValueError(f"aggregate pattern {key} guardrail source is inconsistent")
                if variant_source in guardrail_sources:
                    raise ValueError(f"aggregate pattern {key} guardrail source is duplicated")
                guardrail_sources.add(variant_source)
                observation_id = _require_string(
                    variant.get("observation_id"),
                    f"aggregate pattern {key} guardrail observation_id",
                )
                if evidence_observations.get(variant_source) != observation_id:
                    raise ValueError(f"aggregate pattern {key} guardrail observation is inconsistent")
                _require_string_list(
                    variant.get("guardrails"),
                    f"aggregate pattern {key} guardrails",
                )


def aggregate_technique_studies(
    studies: list[dict[str, Any]],
    *,
    minimum_source_support: int | None = None,
) -> dict[str, Any]:
    if not studies:
        raise ValueError("at least one technique study is required")
    for study in studies:
        validate_technique_study(study)

    source_ids = {
        str(study["source"]["source_id"])
        for study in studies
    }
    if len(source_ids) != len(studies):
        raise ValueError("technique studies must have unique source IDs")
    threshold = (
        math.ceil(len(source_ids) / 2)
        if minimum_source_support is None
        else _require_integer(
            minimum_source_support,
            "minimum_source_support",
            minimum=1,
        )
    )
    if threshold < 1 or threshold > len(source_ids):
        raise ValueError("minimum_source_support is outside the source range")

    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    categories_by_key: dict[str, set[str]] = defaultdict(set)
    for study in studies:
        source_id = str(study["source"]["source_id"])
        for observation in study["technique_observations"]:
            key = str(observation["technique_key"])
            categories_by_key[key].add(str(observation["category"]))
            previous = grouped[key].get(source_id)
            if previous is None or float(observation["confidence"]) > float(
                previous["confidence"]
            ):
                grouped[key][source_id] = observation

    inconsistent_keys = sorted(
        key for key, categories in categories_by_key.items() if len(categories) != 1
    )
    if inconsistent_keys:
        raise ValueError(
            "technique_key has inconsistent categories: "
            + ", ".join(inconsistent_keys)
        )

    patterns = [
        _aggregate_pattern(key, source_rows)
        for key, source_rows in sorted(grouped.items())
    ]
    stable = [
        pattern
        for pattern in patterns
        if pattern["source_support"] >= threshold
    ]
    source_specific = [
        pattern
        for pattern in patterns
        if pattern["source_support"] < threshold
    ]
    opening_recipes = sorted(
        [
            {
                **study.get("opening_recipe", {}),
                "source_id": study["source"]["source_id"],
            }
            for study in studies
            if study.get("opening_recipe")
        ],
        key=lambda row: str(row["source_id"]),
    )
    model_context_policy = {
        "default_maximum_characters": 180_000,
        "hard_limit_characters": 200_000,
        "comparison": "strictly_less_than",
    }
    limitations = [
        "Playback rate is exact only when verified from an editable timeline; visual estimates remain estimates.",
        "Danmaku density is an audience-response clue, not proof that an editing treatment caused the response.",
        "Final reference videos provide positive retained-pattern evidence, not supervised deletion labels.",
    ]
    profile_basis = {
        "schema_version": "1.0",
        "source_count": len(source_ids),
        "source_ids": sorted(source_ids),
        "minimum_source_support": threshold,
        "stable_patterns": stable,
        "source_specific_patterns": source_specific,
        "opening_recipes": opening_recipes,
        "model_context_policy": model_context_policy,
        "limitations": limitations,
    }
    profile_digest = hashlib.sha256(
        json.dumps(
            profile_basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    aggregate = {
        "schema_version": "1.0",
        "profile_id": f"aggregated-reference-techniques-v1-{profile_digest}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(source_ids),
        "source_ids": sorted(source_ids),
        "minimum_source_support": threshold,
        "stable_patterns": stable,
        "source_specific_patterns": source_specific,
        "opening_recipes": opening_recipes,
        "model_context_policy": model_context_policy,
        "limitations": limitations,
    }
    validate_technique_aggregate(aggregate)
    return aggregate


def _aggregate_pattern(
    technique_key: str,
    source_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered_source_rows = sorted(source_rows.items())
    rows = [row for _, row in ordered_source_rows]
    categories = {str(row["category"]) for row in rows}
    if len(categories) != 1:
        raise ValueError(f"technique_key {technique_key} has inconsistent categories")
    best = max(rows, key=lambda row: float(row["confidence"]))
    return {
        "technique_key": technique_key,
        "category": best["category"],
        "source_support": len(source_rows),
        "source_ids": sorted(source_rows),
        "average_confidence": round(
            mean(float(row["confidence"]) for row in rows),
            4,
        ),
        "trigger_examples": list(
            dict.fromkeys(str(row["trigger"]) for row in rows)
        ),
        "treatment_examples": list(
            dict.fromkeys(str(row["treatment"]) for row in rows)
        ),
        "parameter_variants": [
            {
                **row.get("parameters", {}),
                "source_id": source_id,
            }
            for source_id, row in sorted(source_rows.items())
        ],
        "guardrail_variants": [
            {
                "source_id": source_id,
                "observation_id": row["observation_id"],
                "guardrails": list(row.get("guardrails", [])),
            }
            for source_id, row in sorted(source_rows.items())
            if row.get("guardrails")
        ],
        "evidence_ranges": [
            {
                "source_id": source_id,
                "start_sec": row["start_sec"],
                "end_sec": row["end_sec"],
                "observation_id": row["observation_id"],
            }
            for source_id, row in sorted(source_rows.items())
        ],
    }


def load_technique_study(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def load_technique_aggregate(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        aggregate = json.load(file)
    validate_technique_aggregate(aggregate)
    return aggregate


def write_technique_aggregate(
    aggregate: dict[str, Any],
    output_path: Path,
) -> None:
    validate_technique_aggregate(aggregate)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
