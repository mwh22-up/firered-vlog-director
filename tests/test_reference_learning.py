import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.asr import transcribe_media
from vlog_director.event_analysis import group_shots_into_events
from vlog_director.profile_aggregation import aggregate_analyses
from vlog_director.reference_learning import (
    build_audio_segments,
    speech_intervals,
    write_portable_analysis,
)
from vlog_director.review_pack import select_events
from vlog_director.shot_scoring import score_shot


def make_shot(
    shot_id: str,
    start: float,
    end: float,
    role: str,
    *,
    novelty: float = 0.5,
    speech: float = 0.0,
    sharpness: float = 0.12,
    motion: float = 0.06,
    peak: float = 0.6,
    audio_kind: str = "ambient_likely",
) -> dict:
    shot = {
        "shot_id": shot_id,
        "start_sec": start,
        "end_sec": end,
        "duration_sec": end - start,
        "role": role,
        "speech_ratio": speech,
        "visual": {
            "brightness": 0.5,
            "contrast": 0.2,
            "sharpness": sharpness,
            "motion": motion,
            "visual_hash": "f" * 36,
        },
        "audio": {
            "rms": 0.08,
            "peak": peak,
            "spectral_centroid_hz": 1800,
            "spectral_flatness": 0.12,
            "kind": audio_kind,
        },
        "novelty_score": novelty,
    }
    score_shot(shot)
    return shot


class ShotSelectionTests(unittest.TestCase):
    def test_clear_dialogue_is_retained(self) -> None:
        shot = make_shot(
            "shot-0001",
            0,
            3,
            "dialogue",
            speech=0.9,
            novelty=0.6,
        )
        self.assertIn(shot["recommendation"], {"protect", "retain"})
        self.assertIn("包含可理解对白", shot["reasons"])

    def test_duplicate_blurry_silent_shot_is_cut_first(self) -> None:
        shot = make_shot(
            "shot-0002",
            3,
            5,
            "ambient",
            novelty=0.01,
            sharpness=0.01,
            motion=0.0,
            peak=0.0,
            audio_kind="silence",
        )
        self.assertEqual(shot["recommendation"], "cut_first")
        self.assertIn("与前一镜头高度重复", shot["reasons"])

    def test_event_preserves_sequence_dependency(self) -> None:
        shots = [
            make_shot("setup", 0, 5, "establishing"),
            make_shot("action", 5, 12, "action", motion=0.14),
            make_shot("payoff", 12, 16, "payoff", peak=0.9),
            make_shot("reaction", 16, 30, "reaction", speech=0.4),
        ]
        event = group_shots_into_events(shots)[0]
        self.assertEqual(event["sequence_dependency"]["setup_shot_id"], "setup")
        self.assertEqual(event["sequence_dependency"]["payoff_shot_id"], "payoff")
        self.assertEqual(event["sequence_dependency"]["reaction_shot_id"], "reaction")


class AggregationTests(unittest.TestCase):
    def test_aggregate_requires_cross_source_support(self) -> None:
        analyses = [
            sample_analysis("source-a", 2.0, 1.0),
            sample_analysis("source-b", 2.5, 1.2),
        ]
        profiles = [
            {
                "principles": [
                    {
                        "id": "shared-rule",
                        "rule": "retain complete events",
                        "confidence": 0.8,
                    }
                ]
            },
            {
                "principles": [
                    {
                        "id": "shared-rule",
                        "rule": "retain setup, action, payoff, and reaction",
                        "confidence": 0.9,
                    }
                ]
            },
        ]
        profile = aggregate_analyses(analyses, profiles)
        self.assertEqual(profile["source_count"], 2)
        self.assertTrue(profile["shared_rules"])
        self.assertEqual(profile["semantic_principles"][0]["source_support"], 2)
        self.assertEqual(
            profile["shot_selection_model"]["retain_archetypes"][0]["role"],
            "dialogue",
        )

    def test_one_summary_counts_its_independent_reference_sources(self) -> None:
        analyses = [
            sample_analysis("source-a", 2.0, 1.0),
            sample_analysis("source-b", 2.5, 1.2),
            sample_analysis("source-c", 2.2, 1.1),
        ]
        summary = {
            "profile_id": "summary-two-sources",
            "reference_sources": [
                {"source_id": "source-a"},
                {"source_id": "source-b"},
            ],
            "principles": [
                {
                    "id": "restrained-information-graphics",
                    "rule": "Only add overlays when they clarify information or a joke.",
                    "confidence": 0.9,
                }
            ],
        }
        profile = aggregate_analyses(analyses, [summary])
        principle = next(
            item
            for item in profile["semantic_principles"]
            if item["id"] == "restrained-information-graphics"
        )
        self.assertEqual(principle["source_support"], 2)
        self.assertEqual(principle["profile_support"], 1)
        self.assertEqual(
            profile["learning_memory"]["effect_model"]["style_status"],
            "awaiting_user_reference_videos",
        )

    def test_asr_can_be_explicitly_disabled(self) -> None:
        result = transcribe_media(
            None,
            provider="none",
        )
        self.assertEqual(result["status"], "disabled")

    def test_audio_segments_follow_speech_timestamps(self) -> None:
        samples = [
            {
                "time_sec": 0.0,
                "rms": 0.1,
                "peak": 0.5,
                "spectral_centroid_hz": 1800,
                "spectral_flatness": 0.1,
            },
            {
                "time_sec": 0.5,
                "rms": 0.1,
                "peak": 0.6,
                "spectral_centroid_hz": 1800,
                "spectral_flatness": 0.1,
            },
        ]
        segments = build_audio_segments(
            samples,
            [{"start_sec": 0.0, "end_sec": 0.5}],
            0.5,
        )
        self.assertEqual(segments[0]["kind"], "speech")
        self.assertEqual(segments[1]["kind"], "music_likely")

    def test_speech_intervals_use_words_instead_of_long_segment(self) -> None:
        intervals = speech_intervals(
            {
                "segments": [
                    {"start_sec": 0, "end_sec": 20, "text": "short"}
                ],
                "words": [
                    {"start_sec": 1.0, "end_sec": 1.4},
                    {"start_sec": 1.6, "end_sec": 2.0},
                ],
            }
        )
        self.assertEqual(intervals, [{"start_sec": 1.0, "end_sec": 2.0}])

    def test_review_pack_keeps_first_last_and_priority(self) -> None:
        events = [
            {"event_id": f"event-{index}", "start_sec": index, "priority_score": index / 10}
            for index in range(6)
        ]
        selected = select_events(events, 3)
        self.assertEqual(
            [event["event_id"] for event in selected],
            ["event-0", "event-4", "event-5"],
        )

    def test_portable_analysis_removes_transcript_and_local_path(self) -> None:
        analysis = sample_analysis("source-a", 2.0, 1.0)
        analysis["transcription"] = {
            "status": "ready",
            "provider": "faster-whisper",
            "model": "small",
            "language": "zh",
            "segments": [{"text": "private transcript"}],
            "words": [{"text": "private"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "portable.json"
            write_portable_analysis(analysis, output)
            portable = json.loads(output.read_text(encoding="utf-8"))
        self.assertNotIn("media_path", portable["source"])
        self.assertEqual(portable["transcription"]["segments"], [])
        self.assertEqual(portable["transcription"]["segment_count"], 1)


def sample_analysis(
    source_id: str,
    median_duration: float,
    opening_duration: float,
) -> dict:
    return {
        "source": {
            "source_id": source_id,
            "url": f"https://example.com/{source_id}",
            "media_path": f"C:/{source_id}.mp4",
        },
        "media": {
            "median_shot_duration_sec": median_duration,
            "silent_ratio": 0.02,
            "opening_15_sec": {
                "average_shot_duration_sec": opening_duration,
            },
        },
        "events": [
            {"event_type": "activity"},
            {"event_type": "observational"},
        ],
        "learning_summary": {
            "retention_archetypes": [
                {
                    "role": "dialogue",
                    "shot_count": 10,
                    "retained_ratio": 0.8,
                    "average_duration_sec": 3.0,
                    "average_keep_score": 0.72,
                }
            ],
            "cut_first_signals": [
                {"signal": "与前一镜头高度重复", "shot_count": 2}
            ],
        },
    }


if __name__ == "__main__":
    unittest.main()
