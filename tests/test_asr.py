import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.asr import load_transcript


class TranscriptLoadingTests(unittest.TestCase):
    def test_external_complete_transcript_is_normalized(self) -> None:
        nested_word = {
            "start_sec": 0.1,
            "end_sec": 0.4,
            "word": "hello",
            "probability": 0.98,
        }
        transcript = {
            "schema_version": "1.0",
            "model": "large-v3-turbo",
            "segments": [
                {
                    "id": 0,
                    "start_sec": 0.1,
                    "end_sec": 1.2,
                    "text": "hello world",
                    "words": [nested_word],
                }
            ],
        }

        loaded = self._load(transcript)

        self.assertEqual(loaded["status"], "ready")
        self.assertEqual(loaded["provider"], "external")
        self.assertEqual(loaded["words"], [nested_word])
        self.assertEqual(loaded["model"], "large-v3-turbo")

    def test_explicit_non_ready_status_is_not_promoted(self) -> None:
        loaded = self._load(
            {
                "status": "partial",
                "segments": [
                    {
                        "start_sec": 0.0,
                        "end_sec": 1.0,
                        "text": "incomplete",
                    }
                ],
            }
        )

        self.assertEqual(loaded["status"], "partial")
        self.assertEqual(loaded["provider"], "external")

    def test_redacted_portable_transcript_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "portable transcript is redacted"):
            self._load(
                {
                    "status": "ready",
                    "provider": "faster-whisper",
                    "segments": [],
                    "words": [],
                    "portable_redaction": "full transcript remains local",
                }
            )

    def test_empty_complete_transcript_can_represent_no_speech(self) -> None:
        loaded = self._load({"segments": []})

        self.assertEqual(loaded["status"], "ready")
        self.assertEqual(loaded["provider"], "external")

    @staticmethod
    def _load(document: dict) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return load_transcript(path)


if __name__ == "__main__":
    unittest.main()
