import unittest

from vlog_director.model_context import (
    ModelContextLimitError,
    build_reference_context_packet,
    dispatch_model_request,
    validate_serialized_model_request,
)


class ModelContextTests(unittest.TestCase):
    def test_strict_200k_boundary(self) -> None:
        validate_serialized_model_request("x" * 199_999)
        with self.assertRaises(ModelContextLimitError):
            validate_serialized_model_request("x" * 200_000)

    def test_transport_is_not_called_when_request_is_too_large(self) -> None:
        calls = []

        def transport(serialized: str) -> str:
            calls.append(serialized)
            return "sent"

        with self.assertRaises(ModelContextLimitError):
            dispatch_model_request(
                {"content": "x" * 200_000},
                transport,
            )
        self.assertEqual(calls, [])

    def test_reference_packet_is_compacted_below_requested_limit(self) -> None:
        segments = [
            {
                "start_sec": index * 30,
                "end_sec": index * 30 + 20,
                "text": ("narrative text " * 90) + str(index),
            }
            for index in range(500)
        ]
        shots = [
            {
                "shot_id": f"shot-{index:04d}",
                "start_sec": index * 3,
                "end_sec": index * 3 + 3,
                "duration_sec": 3,
                "role": "reaction" if index % 20 == 0 else "action",
                "recommendation": "protect",
                "keep_score": 0.9,
                "speech_ratio": 0.4,
                "visual": {
                    "motion": 0.1,
                    "brightness": 0.5,
                    "sharpness": 0.12,
                },
                "audio": {"kind": "speech", "rms": 0.08},
            }
            for index in range(800)
        ]
        analysis = {
            "source": {
                "source_id": "source-a",
                "url": "https://example.com/a",
                "media_path": "C:/private.mp4",
            },
            "configuration": {},
            "media": {"duration_sec": 2400},
            "transcription": {
                "status": "ready",
                "provider": "test",
                "segments": segments,
                "words": [{}] * 1000,
            },
            "shots": shots,
            "events": [],
            "audio_segments": [],
            "learning_summary": {},
        }
        packet = build_reference_context_packet(
            analysis,
            max_characters=60_000,
        )
        self.assertLess(
            packet["context_budget"]["serialized_characters"],
            60_000,
        )
        self.assertNotIn("media_path", packet["source"])
        self.assertLess(
            len(packet["transcription"]["windows"]),
            len(segments),
        )


if __name__ == "__main__":
    unittest.main()
