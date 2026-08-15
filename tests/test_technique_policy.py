import copy
import unittest
from pathlib import Path

from vlog_director.technique_learning import load_technique_aggregate
from vlog_director.technique_policy import build_technique_policy


class TechniquePolicyTests(unittest.TestCase):
    def test_formal_aggregate_compiles_supported_rules_with_execution_modes(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        aggregate = load_technique_aggregate(
            repository_root
            / "reference-learning"
            / "reference-techniques.aggregate.v1.json"
        )

        policy = build_technique_policy(aggregate)

        self.assertEqual(policy["source_count"], 19)
        self.assertEqual(policy["minimum_source_support"], 2)
        self.assertEqual(policy["stable_pattern_count"], 48)
        self.assertEqual(policy["source_specific_pattern_count"], 75)
        self.assertEqual(
            {
                row["technique_key"]
                for row in policy["eligible_patterns"]
            },
            {
                "humor-preserve-real-awkward-process",
                "opening-phased-hook-not-uniform-fast-cut",
                "playback-rate-fast-forward-travel-compression-visual-estimate",
            },
        )
        self.assertEqual(len(policy["guidance_patterns"]), 120)
        self.assertIn(
            "narrative-failure-adaptation-payoff",
            {row["technique_key"] for row in policy["guidance_patterns"]},
        )
        self.assertEqual(
            sum(
                row["pattern_scope"] == "source_specific"
                for row in policy["guidance_patterns"]
            ),
            75,
        )
        self.assertLessEqual(
            policy["rules"]["humor_awkward_process"]["weight_multiplier"],
            1.15,
        )
        execution_modes = {
            row["technique_key"]: row["execution_mode"]
            for row in policy["eligible_patterns"]
        }
        self.assertEqual(
            execution_modes["opening-phased-hook-not-uniform-fast-cut"],
            "automatic_candidate",
        )
        self.assertEqual(
            execution_modes[
                "playback-rate-fast-forward-travel-compression-visual-estimate"
            ],
            "preview_only",
        )
        self.assertIsNone(
            policy["rules"]["travel_compression_preview"]["playback_rate"]
        )
        self.assertTrue(
            policy["rules"]["travel_compression_preview"]
            ["requires_human_rate_selection"]
        )
        self.assertNotIn("applied_patterns", policy)

    def test_single_source_allowlisted_key_remains_guidance(self) -> None:
        key = "humor-preserve-real-awkward-process"
        aggregate = {
            "schema_version": "1.0",
            "profile_id": "single-source-techniques",
            "source_count": 1,
            "source_ids": ["reference-a"],
            "minimum_source_support": 1,
            "stable_patterns": [
                {
                    "technique_key": key,
                    "category": "humor",
                    "source_support": 1,
                    "source_ids": ["reference-a"],
                    "average_confidence": 0.99,
                    "trigger_examples": ["one reference trigger"],
                    "treatment_examples": ["one reference treatment"],
                    "parameter_variants": [{"source_id": "reference-a"}],
                    "guardrail_variants": [],
                    "evidence_ranges": [
                        {
                            "source_id": "reference-a",
                            "start_sec": 1.0,
                            "end_sec": 2.0,
                            "observation_id": "obs-a",
                        }
                    ],
                }
            ],
            "source_specific_patterns": [],
            "opening_recipes": [],
            "model_context_policy": {
                "default_maximum_characters": 180000,
                "hard_limit_characters": 200000,
                "comparison": "strictly_less_than",
            },
            "limitations": ["positive retained patterns only"],
        }

        policy = build_technique_policy(aggregate)

        self.assertNotIn(
            "humor-preserve-real-awkward-process",
            {row["technique_key"] for row in policy["eligible_patterns"]},
        )
        self.assertEqual(
            [row["technique_key"] for row in policy["guidance_patterns"]],
            [key],
        )
        self.assertFalse(policy["rules"]["humor_awkward_process"]["active"])

    def test_allowlisted_key_with_wrong_category_remains_guidance(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        aggregate = load_technique_aggregate(
            repository_root
            / "reference-learning"
            / "reference-techniques.aggregate.v1.json"
        )
        invalid_semantics = copy.deepcopy(aggregate)
        humor_pattern = next(
            pattern
            for pattern in invalid_semantics["stable_patterns"]
            if pattern["technique_key"] == "humor-preserve-real-awkward-process"
        )
        humor_pattern["category"] = "narrative"

        policy = build_technique_policy(invalid_semantics)

        self.assertNotIn(
            "humor-preserve-real-awkward-process",
            {row["technique_key"] for row in policy["eligible_patterns"]},
        )
        self.assertFalse(policy["rules"]["humor_awkward_process"]["active"])
        self.assertIn(
            "humor-preserve-real-awkward-process",
            {row["technique_key"] for row in policy["guidance_patterns"]},
        )


if __name__ == "__main__":
    unittest.main()
