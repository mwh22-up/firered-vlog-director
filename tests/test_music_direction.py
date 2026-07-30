import unittest

from vlog_director.music_direction import build_music_reference, to_enhancement_music


PLAN = {
    "project_id": "demo",
    "version": 2,
    "chapters": [
        {
            "id": "ch01",
            "title": "Journey",
            "segments": [
                {"source": "a", "in_sec": 0, "out_sec": 20, "story_role": "journey"},
                {"source": "a", "in_sec": 20, "out_sec": 35, "story_role": "dialogue"},
            ],
        },
        {
            "id": "ch02",
            "title": "Closing",
            "segments": [
                {"source": "b", "in_sec": 0, "out_sec": 20, "story_role": "closing"},
            ],
        },
    ],
}
PROFILE = {
    "profile_id": "reference",
    "source_count": 15,
    "audio_model": {
        "kind_ratios": {
            "music_likely": {"minimum": 0.02, "average": 0.12, "maximum": 0.2}
        }
    },
}


class MusicDirectionTests(unittest.TestCase):
    def test_reference_is_non_blocking_and_capcut_ready(self) -> None:
        reference = build_music_reference(PLAN, PROFILE)
        self.assertEqual(reference["status"], "reference_ready")
        self.assertEqual(reference["output_kind"], "non_blocking_music_reference")
        self.assertTrue(reference["non_blocking"])
        self.assertLessEqual(reference["suggested_coverage_ratio"], 0.2)
        self.assertTrue(reference["recommendations"])
        for item in reference["recommendations"]:
            self.assertTrue(item["capcut_search_keywords"])
            self.assertTrue(item["rhythm_advice"])
            self.assertTrue(item["entry_advice"])
            self.assertTrue(item["exit_advice"])
            self.assertTrue(item["optional"])
            self.assertFalse(20 <= item["start_sec"] < 35)
        enhancement = to_enhancement_music(reference)
        self.assertTrue(enhancement["non_blocking"])
        self.assertEqual(enhancement["mode"], "manual_capcut_reference")
        self.assertEqual(enhancement["tracks"], [])

    def test_subtitle_dialogue_is_removed_from_non_dialogue_window(self) -> None:
        plan = {
            "project_id": "spoken-culture",
            "version": 1,
            "chapters": [
                {
                    "id": "ch01",
                    "title": "Culture",
                    "segments": [
                        {"source": "a", "in_sec": 0, "out_sec": 30, "story_role": "culture"}
                    ],
                }
            ],
        }
        subtitles = {
            "cues": [
                {"start_sec": 0.0, "end_sec": 10.0, "text": "spoken"},
                {"start_sec": 18.0, "end_sec": 30.0, "text": "spoken"},
            ]
        }
        profile = {
            "profile_id": "subtitle-aware",
            "source_count": 2,
            "audio_model": {
                "kind_ratios": {
                    "music_likely": {"minimum": 0.05, "average": 0.20, "maximum": 0.25}
                }
            },
        }
        reference = build_music_reference(
            plan,
            profile,
            subtitles,
            dialogue_padding_sec=0.5,
        )
        self.assertEqual(reference["dialogue_evidence"]["subtitle_cue_count"], 2)
        self.assertEqual(len(reference["recommendations"]), 1)
        music = reference["recommendations"][0]
        self.assertGreaterEqual(music["start_sec"], 10.5)
        self.assertLessEqual(music["end_sec"], 17.5)
        for protected in reference["dialogue_intervals"]:
            overlap = max(
                0.0,
                min(music["end_sec"], protected["end_sec"])
                - max(music["start_sec"], protected["start_sec"]),
            )
            self.assertEqual(overlap, 0.0)

    def test_empty_timeline_needs_no_music_and_still_passes(self) -> None:
        reference = build_music_reference(
            {"project_id": "quiet", "version": 1, "chapters": []},
            PROFILE,
        )
        self.assertEqual(reference["status"], "no_music_suggestion")
        self.assertEqual(reference["recommendations"], [])
        self.assertTrue(to_enhancement_music(reference)["non_blocking"])


if __name__ == "__main__":
    unittest.main()
