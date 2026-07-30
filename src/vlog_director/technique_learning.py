from __future__ import annotations

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
    threshold = minimum_source_support or math.ceil(len(source_ids) / 2)
    if threshold < 1 or threshold > len(source_ids):
        raise ValueError("minimum_source_support is outside the source range")

    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for study in studies:
        source_id = str(study["source"]["source_id"])
        for observation in study["technique_observations"]:
            key = str(observation["technique_key"])
            previous = grouped[key].get(source_id)
            if previous is None or float(observation["confidence"]) > float(
                previous["confidence"]
            ):
                grouped[key][source_id] = observation

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
    return {
        "schema_version": "1.0",
        "profile_id": "aggregated-reference-techniques-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(source_ids),
        "source_ids": sorted(source_ids),
        "minimum_source_support": threshold,
        "stable_patterns": stable,
        "source_specific_patterns": source_specific,
        "opening_recipes": [
            {
                "source_id": study["source"]["source_id"],
                **study.get("opening_recipe", {}),
            }
            for study in studies
            if study.get("opening_recipe")
        ],
        "model_context_policy": {
            "default_maximum_characters": 180_000,
            "hard_limit_characters": 200_000,
            "comparison": "strictly_less_than",
        },
        "limitations": [
            "Playback rate is exact only when verified from an editable timeline; visual estimates remain estimates.",
            "Danmaku density is an audience-response clue, not proof that an editing treatment caused the response.",
            "Final reference videos provide positive retained-pattern evidence, not supervised deletion labels.",
        ],
    }


def _aggregate_pattern(
    technique_key: str,
    source_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = list(source_rows.values())
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
                "source_id": source_id,
                **row.get("parameters", {}),
            }
            for source_id, row in sorted(source_rows.items())
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


def write_technique_aggregate(
    aggregate: dict[str, Any],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
