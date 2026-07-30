import unittest

from vlog_director.technique_learning import aggregate_technique_studies


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


def speed_observation(observation_id: str, confidence: float) -> dict:
    return {
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


if __name__ == "__main__":
    unittest.main()
