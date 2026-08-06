import copy
import unittest
from pathlib import Path

from vlog_director.technique_learning import (
    aggregate_technique_studies,
    load_technique_aggregate,
    load_technique_study,
    validate_technique_aggregate,
)


def study(source_id: str, observations: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "study_id": f"study-{source_id}",
        "source": {
            "source_id": source_id,
            "url": f"https://example.com/{source_id}",
        },
        "technique_observations": observations,
    }


def speed_observation(
    observation_id: str,
    confidence: float,
    *,
    guardrails: list[str] | None = None,
) -> dict:
    observation = {
        "observation_id": observation_id,
        "technique_key": "humor-fluster-speed-up",
        "start_sec": 10,
        "end_sec": 14,
        "category": "playback_rate",
        "trigger": "character becomes visibly flustered",
        "treatment": "compress the repetitive action with an estimated 2x speed-up",
        "confidence": confidence,
        "parameters": {
            "playback_rate": 2.0,
            "rate_source": "visual_estimate",
        },
    }
    if guardrails is not None:
        observation["guardrails"] = guardrails
    return observation


class TechniqueLearningTests(unittest.TestCase):
    def test_support_is_deduplicated_by_source_id(self) -> None:
        studies = [
            study(
                "source-a",
                [
                    speed_observation("a-low", 0.6),
                    speed_observation("a-high", 0.9),
                ],
            ),
            study("source-b", [speed_observation("b", 0.8)]),
        ]
        aggregate = aggregate_technique_studies(studies)
        pattern = aggregate["stable_patterns"][0]
        self.assertEqual(pattern["source_support"], 2)
        self.assertEqual(pattern["source_ids"], ["source-a", "source-b"])
        self.assertEqual(len(pattern["evidence_ranges"]), 2)
        self.assertEqual(pattern["average_confidence"], 0.85)

    def test_aggregate_content_and_profile_id_are_input_order_independent(self) -> None:
        studies = [
            study("source-b", [speed_observation("b", 0.8)]),
            study("source-a", [speed_observation("a", 0.9)]),
        ]

        forward = aggregate_technique_studies(
            studies,
            minimum_source_support=2,
        )
        reverse = aggregate_technique_studies(
            list(reversed(studies)),
            minimum_source_support=2,
        )

        forward.pop("generated_at")
        reverse.pop("generated_at")
        self.assertEqual(forward, reverse)
        self.assertRegex(
            forward["profile_id"],
            r"^aggregated-reference-techniques-v1-[0-9a-f]{12}$",
        )

    def test_guardrails_keep_the_selected_observation_trace(self) -> None:
        studies = [
            study(
                "source-a",
                [
                    speed_observation(
                        "a-low",
                        0.6,
                        guardrails=["discarded lower-confidence guardrail"],
                    ),
                    speed_observation(
                        "a-high",
                        0.9,
                        guardrails=["preview before applying speed"],
                    ),
                ],
            ),
            study(
                "source-b",
                [
                    speed_observation(
                        "b",
                        0.8,
                        guardrails=["preserve intelligible dialogue"],
                    )
                ],
            ),
        ]

        aggregate = aggregate_technique_studies(studies)
        pattern = aggregate["stable_patterns"][0]

        self.assertEqual(
            pattern["guardrail_variants"],
            [
                {
                    "source_id": "source-a",
                    "observation_id": "a-high",
                    "guardrails": ["preview before applying speed"],
                },
                {
                    "source_id": "source-b",
                    "observation_id": "b",
                    "guardrails": ["preserve intelligible dialogue"],
                },
            ],
        )
        evidence_by_source = {
            row["source_id"]: row["observation_id"]
            for row in pattern["evidence_ranges"]
        }
        self.assertEqual(
            {
                row["source_id"]: row["observation_id"]
                for row in pattern["guardrail_variants"]
            },
            evidence_by_source,
        )

    def test_runtime_validation_accepts_a_consistent_aggregate(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study(
                    "source-a",
                    [
                        speed_observation(
                            "a",
                            0.9,
                            guardrails=["preview before applying speed"],
                        )
                    ],
                ),
                study(
                    "source-b",
                    [
                        speed_observation(
                            "b",
                            0.8,
                            guardrails=["preserve intelligible dialogue"],
                        )
                    ],
                ),
            ],
            minimum_source_support=2,
        )

        validate_technique_aggregate(aggregate)

    def test_runtime_validation_rejects_inconsistent_aggregate_metadata(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study("source-a", [speed_observation("a", 0.9)]),
                study("source-b", [speed_observation("b", 0.8)]),
            ],
            minimum_source_support=2,
        )
        invalid_cases = []

        source_count_mismatch = copy.deepcopy(aggregate)
        source_count_mismatch["source_count"] = 3
        invalid_cases.append(source_count_mismatch)

        support_mismatch = copy.deepcopy(aggregate)
        support_mismatch["stable_patterns"][0]["source_support"] = 1
        invalid_cases.append(support_mismatch)

        invalid_confidence = copy.deepcopy(aggregate)
        invalid_confidence["stable_patterns"][0]["average_confidence"] = 1.1
        invalid_cases.append(invalid_confidence)

        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_technique_aggregate(invalid)

    def test_runtime_validation_rejects_non_finite_evidence_numbers(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study("source-a", [speed_observation("a", 0.9)]),
                study("source-b", [speed_observation("b", 0.8)]),
            ],
            minimum_source_support=2,
        )

        for field, value in (("start_sec", float("nan")), ("end_sec", float("inf"))):
            invalid = copy.deepcopy(aggregate)
            invalid["stable_patterns"][0]["evidence_ranges"][0][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "must be finite"):
                    validate_technique_aggregate(invalid)

    def test_runtime_validation_requires_pattern_examples_and_parameters(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study("source-a", [speed_observation("a", 0.9)]),
                study("source-b", [speed_observation("b", 0.8)]),
            ],
            minimum_source_support=2,
        )

        for field in (
            "trigger_examples",
            "treatment_examples",
            "parameter_variants",
        ):
            invalid = copy.deepcopy(aggregate)
            del invalid["stable_patterns"][0][field]
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_technique_aggregate(invalid)

    def test_parameter_variants_cover_only_the_pattern_sources(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study("source-a", [speed_observation("a", 0.9)]),
                study("source-b", [speed_observation("b", 0.8)]),
            ],
            minimum_source_support=2,
        )
        pattern = aggregate["stable_patterns"][0]

        self.assertEqual(
            [row["source_id"] for row in pattern["parameter_variants"]],
            pattern["source_ids"],
        )

        incomplete = copy.deepcopy(aggregate)
        incomplete["stable_patterns"][0]["parameter_variants"].pop()
        with self.assertRaisesRegex(ValueError, "parameter sources are incomplete"):
            validate_technique_aggregate(incomplete)

        forged = copy.deepcopy(aggregate)
        forged["stable_patterns"][0]["parameter_variants"][0][
            "source_id"
        ] = "forged-source"
        with self.assertRaisesRegex(ValueError, "parameter source is inconsistent"):
            validate_technique_aggregate(forged)

    def test_runtime_validation_rejects_a_forged_opening_recipe_source(self) -> None:
        source_a = study("source-a", [speed_observation("a", 0.9)])
        source_a["opening_recipe"] = {
            "rule": "use target evidence to phase the opening",
        }
        aggregate = aggregate_technique_studies(
            [
                source_a,
                study("source-b", [speed_observation("b", 0.8)]),
            ],
            minimum_source_support=2,
        )
        forged = copy.deepcopy(aggregate)
        forged["opening_recipes"][0]["source_id"] = "forged-source"

        with self.assertRaisesRegex(ValueError, "opening recipe source is inconsistent"):
            validate_technique_aggregate(forged)

    def test_runtime_validation_rejects_untraceable_guardrails(self) -> None:
        aggregate = aggregate_technique_studies(
            [
                study(
                    "source-a",
                    [speed_observation("a", 0.9, guardrails=["preview first"])],
                ),
                study(
                    "source-b",
                    [speed_observation("b", 0.8, guardrails=["protect speech"])],
                ),
            ],
            minimum_source_support=2,
        )
        invalid_cases = []

        missing_observation = copy.deepcopy(aggregate)
        del missing_observation["stable_patterns"][0]["guardrail_variants"][0][
            "observation_id"
        ]
        invalid_cases.append(missing_observation)

        unknown_source = copy.deepcopy(aggregate)
        unknown_source["stable_patterns"][0]["guardrail_variants"][0][
            "source_id"
        ] = "unknown-source"
        invalid_cases.append(unknown_source)

        mismatched_observation = copy.deepcopy(aggregate)
        mismatched_observation["stable_patterns"][0]["guardrail_variants"][0][
            "observation_id"
        ] = "another-observation"
        invalid_cases.append(mismatched_observation)

        for invalid in invalid_cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_technique_aggregate(invalid)

    def test_same_technique_key_cannot_change_category_between_sources(self) -> None:
        source_a = speed_observation("a", 0.9)
        source_b = speed_observation("b", 0.8)
        source_b["category"] = "humor"

        with self.assertRaisesRegex(ValueError, "inconsistent categories"):
            aggregate_technique_studies(
                [
                    study("source-a", [source_a]),
                    study("source-b", [source_b]),
                ],
                minimum_source_support=2,
            )

    def test_eight_formal_studies_keep_the_learning_baseline(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        study_paths = sorted(
            (repository_root / "reference-learning").glob(
                "technique-study.*.v1.json"
            )
        )
        studies = [load_technique_study(path) for path in study_paths]
        observation_count = sum(
            len(item["technique_observations"])
            for item in studies
        )
        unique_keys = {
            observation["technique_key"]
            for item in studies
            for observation in item["technique_observations"]
        }

        self.assertEqual(len(studies), 8)
        self.assertEqual(observation_count, 138)
        self.assertEqual(len(unique_keys), 76)

        aggregate = aggregate_technique_studies(
            studies,
            minimum_source_support=2,
        )
        validate_technique_aggregate(aggregate)

        self.assertEqual(aggregate["source_count"], 8)
        self.assertEqual(aggregate["minimum_source_support"], 2)
        self.assertEqual(len(aggregate["stable_patterns"]), 25)
        self.assertEqual(len(aggregate["source_specific_patterns"]), 51)
        self.assertEqual(
            {
                pattern["technique_key"]
                for group in (
                    aggregate["stable_patterns"],
                    aggregate["source_specific_patterns"],
                )
                for pattern in group
            },
            unique_keys,
        )

        for pattern in (
            aggregate["stable_patterns"]
            + aggregate["source_specific_patterns"]
        ):
            evidence_by_source = {
                row["source_id"]: row["observation_id"]
                for row in pattern["evidence_ranges"]
            }
            for variant in pattern["guardrail_variants"]:
                self.assertEqual(
                    variant["observation_id"],
                    evidence_by_source[variant["source_id"]],
                )
                self.assertTrue(variant["guardrails"])
                self.assertTrue(
                    all(
                        isinstance(value, str) and value.strip()
                        for value in variant["guardrails"]
                    )
                )

    def test_committed_aggregate_matches_the_eight_formal_studies(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        reference_directory = repository_root / "reference-learning"
        studies = [
            load_technique_study(path)
            for path in sorted(
                reference_directory.glob("technique-study.*.v1.json")
            )
        ]
        regenerated = aggregate_technique_studies(
            studies,
            minimum_source_support=2,
        )
        committed = load_technique_aggregate(
            reference_directory / "reference-techniques.aggregate.v1.json"
        )

        regenerated.pop("generated_at", None)
        committed.pop("generated_at", None)
        self.assertEqual(committed, regenerated)


if __name__ == "__main__":
    unittest.main()
