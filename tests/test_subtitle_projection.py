from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.subtitle_projection import (
    SubtitleCrosscheckPolicy,
    SubtitleMergePolicy,
    apply_evidence_based_text_corrections,
    attach_cross_asr_evidence,
    build_subtitle_review_record,
    build_subtitle_crosscheck_report,
    project_asr_to_realized_timeline,
    write_subtitle_review_bundle,
)


def _analysis(source_id: str, segments: list[dict]) -> dict:
    return {
        "source": {"source_id": source_id},
        "transcription": {
            "status": "ready",
            "provider": "test-asr",
            "model": "test-model",
            "language": "zh",
            "segments": segments,
        },
    }


class SubtitleProjectionTests(unittest.TestCase):
    def test_projects_clipped_words_to_realized_segment_and_marks_risks(self) -> None:
        edit_plan = {
            "project_id": "project",
            "version": 3,
            "chapters": [
                {
                    "id": "ch01",
                    "segments": [
                        {"source": "raw/GX000001.MP4", "in_sec": 10, "out_sec": 20}
                    ],
                }
            ],
        }
        render_report = {
            "version": 3,
            "actual_duration_sec": 16,
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/GX000001.MP4",
                    "planned_duration_sec": 10,
                    "actual_start_sec": 5,
                    "actual_end_sec": 16,
                }
            ],
        }
        analyses = [
            _analysis(
                "GX000001",
                [
                    {
                        "id": "asr-1",
                        "start_sec": 9.8,
                        "end_sec": 10.8,
                        "text": "边界低",
                        "avg_logprob": -1.2,
                        "no_speech_probability": 0.6,
                        "words": [
                            {
                                "start_sec": 9.8,
                                "end_sec": 10.2,
                                "text": "边",
                                "probability": 0.1,
                            },
                            {
                                "start_sec": 10.2,
                                "end_sec": 10.8,
                                "text": "界",
                                "probability": 0.9,
                            },
                        ],
                    }
                ],
            )
        ]

        draft = project_asr_to_realized_timeline(
            edit_plan,
            render_report,
            analyses,
            subtitle_version=4,
            created_at="2026-08-03T00:00:00+00:00",
        )

        self.assertEqual(draft["coverage"]["raw_asr_candidate_count"], 1)
        self.assertEqual(draft["coverage"]["selected_word_count"], 2)
        cue = draft["cues"][0]
        self.assertEqual(cue["start_sec"], 5.0)
        self.assertEqual(cue["end_sec"], 5.88)
        self.assertEqual(cue["source_start_sec"], 10.0)
        self.assertEqual(cue["review_status"], "review_required")
        self.assertIn("source_boundary_clipped", cue["risk_flags"])
        self.assertIn("near_cut_in", cue["risk_flags"])
        self.assertIn("low_confidence_word", cue["risk_flags"])
        self.assertIn("high_no_speech_probability", cue["risk_flags"])
        self.assertEqual(
            cue["asr_provenance"]["word_refs"][0]["source_start_sec"], 10.0
        )

    def test_merges_short_asr_units_but_never_crosses_an_edit_cut(self) -> None:
        edit_plan = {
            "project_id": "project",
            "version": 3,
            "chapters": [
                {
                    "id": "ch01",
                    "segments": [
                        {"source": "raw/GX000001.MP4", "in_sec": 0, "out_sec": 2},
                        {"source": "raw/GX000001.MP4", "in_sec": 2, "out_sec": 4},
                    ],
                }
            ],
        }
        render_report = {
            "version": 3,
            "actual_duration_sec": 4.2,
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/GX000001.MP4",
                    "planned_duration_sec": 2,
                    "actual_start_sec": 0,
                    "actual_end_sec": 2.1,
                },
                {
                    "chapter_id": "ch01",
                    "segment_index": 2,
                    "source": "raw/GX000001.MP4",
                    "planned_duration_sec": 2,
                    "actual_start_sec": 2.1,
                    "actual_end_sec": 4.2,
                },
            ],
        }
        segments = [
            {
                "id": "asr-1",
                "start_sec": 0.1,
                "end_sec": 0.6,
                "text": "你好",
                "avg_logprob": -0.1,
                "no_speech_probability": 0.0,
                "words": [
                    {"start_sec": 0.1, "end_sec": 0.3, "text": "你", "probability": 1},
                    {"start_sec": 0.3, "end_sec": 0.6, "text": "好", "probability": 1},
                ],
            },
            {
                "id": "asr-2",
                "start_sec": 0.7,
                "end_sec": 1.2,
                "text": "世界",
                "avg_logprob": -0.1,
                "no_speech_probability": 0.0,
                "words": [
                    {"start_sec": 0.7, "end_sec": 0.9, "text": "世", "probability": 1},
                    {"start_sec": 0.9, "end_sec": 1.2, "text": "界", "probability": 1},
                ],
            },
            {
                "id": "asr-3",
                "start_sec": 2.0,
                "end_sec": 2.5,
                "text": "下一段",
                "avg_logprob": -0.1,
                "no_speech_probability": 0.0,
                "words": [
                    {"start_sec": 2.0, "end_sec": 2.2, "text": "下", "probability": 1},
                    {"start_sec": 2.2, "end_sec": 2.3, "text": "一", "probability": 1},
                    {"start_sec": 2.3, "end_sec": 2.5, "text": "段", "probability": 1},
                ],
            },
        ]

        draft = project_asr_to_realized_timeline(
            edit_plan,
            render_report,
            [_analysis("GX000001", segments)],
            subtitle_version=4,
            created_at="2026-08-03T00:00:00+00:00",
        )

        self.assertEqual(len(draft["cues"]), 2)
        self.assertEqual(draft["cues"][0]["text"], "你好世界")
        self.assertEqual(draft["cues"][0]["segment_id"], "ch01-s001")
        self.assertEqual(draft["cues"][1]["segment_id"], "ch01-s002")
        self.assertLessEqual(draft["cues"][0]["end_sec"], 2.1)
        self.assertGreaterEqual(draft["cues"][1]["start_sec"], 2.1)

    def test_wraps_at_two_lines_and_writes_utf8_without_bom(self) -> None:
        edit_plan = {
            "project_id": "project",
            "version": 3,
            "chapters": [
                {
                    "id": "ch01",
                    "segments": [
                        {"source": "raw/GX000001.MP4", "in_sec": 0, "out_sec": 3}
                    ],
                }
            ],
        }
        render_report = {
            "version": 3,
            "actual_duration_sec": 3,
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/GX000001.MP4",
                    "planned_duration_sec": 3,
                    "actual_start_sec": 0,
                    "actual_end_sec": 3,
                }
            ],
        }
        words = [
            {
                "start_sec": index * 0.1,
                "end_sec": (index + 1) * 0.1,
                "text": character,
                "probability": 1,
            }
            for index, character in enumerate("一二三四五六七八九十十一十二")
        ]
        analysis = _analysis(
            "GX000001",
            [
                {
                    "id": "asr-1",
                    "start_sec": 0,
                    "end_sec": 1.2,
                    "text": "一二三四五六七八九十十一十二",
                    "avg_logprob": -0.1,
                    "no_speech_probability": 0.0,
                    "words": words,
                }
            ],
        )
        policy = SubtitleMergePolicy(max_chars_per_line=6)
        draft = project_asr_to_realized_timeline(
            edit_plan,
            render_report,
            [analysis],
            subtitle_version=4,
            policy=policy,
            created_at="2026-08-03T00:00:00+00:00",
        )
        review = build_subtitle_review_record(
            draft,
            draft_path="work/subtitles/subtitles.v4.review-required.json",
            created_at="2026-08-03T00:00:00+00:00",
        )

        self.assertLessEqual(max(map(len, draft["cues"][0]["text"].splitlines())), 6)
        self.assertEqual(review["coverage"]["status"], "pending")
        self.assertEqual(review["summary"]["reviewed_cue_count"], 0)
        self.assertTrue(
            all(
                item["review_status"] == "review_required"
                for item in review["cue_reviews"]
            )
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            draft_path = root / "draft.json"
            review_path = root / "review.json"
            srt_path = root / "draft.srt"
            write_subtitle_review_bundle(
                draft,
                review,
                draft_output=draft_path,
                review_output=review_path,
                srt_output=srt_path,
            )
            for path in (draft_path, review_path, srt_path):
                payload = path.read_bytes()
                self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))
                payload.decode("utf-8")
            self.assertEqual(
                json.loads(draft_path.read_text(encoding="utf-8"))["status"],
                "review_required",
            )
            self.assertIn("一二三", srt_path.read_text(encoding="utf-8"))

    def test_preserves_zero_duration_asr_words_as_review_risk(self) -> None:
        edit_plan = {
            "project_id": "project",
            "version": 3,
            "chapters": [
                {
                    "id": "ch01",
                    "segments": [
                        {"source": "raw/GX000001.MP4", "in_sec": 0, "out_sec": 2}
                    ],
                }
            ],
        }
        render_report = {
            "version": 3,
            "actual_duration_sec": 2,
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/GX000001.MP4",
                    "planned_duration_sec": 2,
                    "actual_start_sec": 0,
                    "actual_end_sec": 2,
                }
            ],
        }
        analysis = _analysis(
            "GX000001",
            [
                {
                    "id": "asr-1",
                    "start_sec": 0.2,
                    "end_sec": 0.8,
                    "text": "不要走",
                    "avg_logprob": -0.1,
                    "no_speech_probability": 0.0,
                    "words": [
                        {"start_sec": 0.2, "end_sec": 0.5, "text": "不", "probability": 1},
                        {"start_sec": 0.5, "end_sec": 0.5, "text": "要", "probability": 0.4},
                        {"start_sec": 0.5, "end_sec": 0.8, "text": "走", "probability": 1},
                    ],
                }
            ],
        )

        draft = project_asr_to_realized_timeline(
            edit_plan,
            render_report,
            [analysis],
            subtitle_version=4,
            created_at="2026-08-03T00:00:00+00:00",
        )

        self.assertEqual(draft["coverage"]["selected_word_count"], 3)
        self.assertEqual(draft["cues"][0]["text"], "不要走")
        self.assertIn(
            "zero_duration_word_timing", draft["cues"][0]["risk_flags"]
        )

    def test_rejects_render_measurement_source_mismatch(self) -> None:
        edit_plan = {
            "project_id": "project",
            "version": 3,
            "chapters": [
                {
                    "id": "ch01",
                    "segments": [
                        {"source": "raw/GX000001.MP4", "in_sec": 0, "out_sec": 1}
                    ],
                }
            ],
        }
        render_report = {
            "version": 3,
            "actual_duration_sec": 1,
            "segment_measurements": [
                {
                    "chapter_id": "ch01",
                    "segment_index": 1,
                    "source": "raw/GX999999.MP4",
                    "planned_duration_sec": 1,
                    "actual_start_sec": 0,
                    "actual_end_sec": 1,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "source mismatch"):
            project_asr_to_realized_timeline(
                edit_plan,
                render_report,
                [_analysis("GX000001", [])],
                subtitle_version=4,
            )

    def test_cross_asr_assigns_words_once_and_marks_disagreements(self) -> None:
        draft = {
            "project_id": "project",
            "subtitle_version": 4,
            "status": "review_required",
            "coverage": {"status": "pending"},
            "merge_policy": {"max_lines": 2, "max_chars_per_line": 15},
            "segment_coverage": [],
            "cues": [
                {
                    "cue_id": "subtitle-v4-0001",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "挪威有五百万人",
                    "segment_id": "ch01-s001",
                    "review_status": "review_required",
                    "risk_flags": [],
                },
                {
                    "cue_id": "subtitle-v4-0002",
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                    "text": "相机对不上焦",
                    "segment_id": "ch01-s001",
                    "review_status": "review_required",
                    "risk_flags": [],
                },
                {
                    "cue_id": "subtitle-v4-0003",
                    "start_sec": 3.0,
                    "end_sec": 4.0,
                    "text": "没有机器证据",
                    "segment_id": "ch01-s002",
                    "review_status": "review_required",
                    "risk_flags": [],
                },
            ],
        }
        cross_analysis = {
            "source": {
                "source_id": "crosscheck",
                "media_path": "C:/private/path/video.mp4",
            },
            "transcription": {
                "status": "ready",
                "provider": "faster-whisper",
                "model": "small",
                "language": "zh",
                "segments": [
                    {
                        "id": "asr-1",
                        "words": [
                            {
                                "start_sec": 0.1,
                                "end_sec": 0.9,
                                "text": "罗威有500万人",
                                "probability": 0.9,
                            },
                            {
                                "start_sec": 1.1,
                                "end_sec": 1.9,
                                "text": "今天天气很好",
                                "probability": 0.1,
                            },
                        ],
                    }
                ],
            },
        }

        crosschecked = attach_cross_asr_evidence(
            draft,
            cross_analysis,
            policy=SubtitleCrosscheckPolicy(
                strong_match_threshold=0.75,
                partial_match_threshold=0.45,
            ),
            crosschecked_at="2026-08-03T00:00:00+00:00",
        )

        first, second, third = crosschecked["cues"]
        self.assertEqual(first["cross_asr_evidence"]["status"], "strong_match")
        self.assertEqual(first["cross_asr_evidence"]["text"], "罗威有500万人")
        self.assertEqual(second["cross_asr_evidence"]["status"], "disagreement")
        self.assertIn("cross_asr_disagreement", second["risk_flags"])
        self.assertIn("cross_asr_low_confidence_word", second["risk_flags"])
        self.assertEqual(third["cross_asr_evidence"]["status"], "no_evidence")
        self.assertIn("cross_asr_no_evidence", third["risk_flags"])
        self.assertEqual(
            crosschecked["machine_crosscheck"]["summary"]["assigned_word_count"],
            2,
        )
        self.assertNotIn(
            "C:/private/path", json.dumps(crosschecked, ensure_ascii=False)
        )
        self.assertTrue(
            all(cue["review_status"] == "review_required" for cue in crosschecked["cues"])
        )
        report = build_subtitle_crosscheck_report(
            crosschecked,
            draft_path="work/subtitles/subtitles.v4.review-required.json",
            created_at="2026-08-03T00:00:00+00:00",
        )
        self.assertEqual(report["status"], "review_required")
        self.assertEqual(report["coverage"]["status"], "pending")
        self.assertEqual(report["flagged_cue_count"], 2)
        self.assertTrue(
            all(
                item["review_status"] == "review_required"
                for item in report["flagged_cues"]
            )
        )

    def test_cross_asr_replaces_stale_flags_and_preserves_other_risks(self) -> None:
        draft = {
            "project_id": "project",
            "subtitle_version": 4,
            "status": "review_required",
            "cues": [
                {
                    "cue_id": "subtitle-v4-0001",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "abcdef",
                    "segment_id": "ch01-s001",
                    "review_status": "review_required",
                    "risk_flags": ["near_cut_in"],
                },
                {
                    "cue_id": "subtitle-v4-0002",
                    "start_sec": 1.0,
                    "end_sec": 2.0,
                    "text": "mnopqr",
                    "segment_id": "ch01-s001",
                    "review_status": "review_required",
                    "risk_flags": ["low_confidence_word"],
                },
            ],
        }

        def cross_analysis(first_text: str, second_text: str) -> dict:
            return {
                "source": {"source_id": "crosscheck"},
                "transcription": {
                    "status": "ready",
                    "segments": [
                        {
                            "id": "asr-1",
                            "words": [
                                {
                                    "start_sec": 0.1,
                                    "end_sec": 0.9,
                                    "text": first_text,
                                    "probability": 0.9,
                                },
                                {
                                    "start_sec": 1.1,
                                    "end_sec": 1.9,
                                    "text": second_text,
                                    "probability": 0.9,
                                },
                            ],
                        }
                    ],
                },
            }

        partial = attach_cross_asr_evidence(
            draft,
            cross_analysis("abcxyz", "mnoxyz"),
        )
        self.assertEqual(
            [cue["cross_asr_evidence"]["status"] for cue in partial["cues"]],
            ["partial_match", "partial_match"],
        )

        crosschecked = attach_cross_asr_evidence(
            partial,
            cross_analysis("abcdef", "zzzzzz"),
        )

        strong, disagreement = crosschecked["cues"]
        self.assertEqual(strong["cross_asr_evidence"]["status"], "strong_match")
        self.assertEqual(strong["risk_flags"], ["near_cut_in"])
        self.assertEqual(
            disagreement["cross_asr_evidence"]["status"], "disagreement"
        )
        self.assertEqual(
            disagreement["risk_flags"],
            ["low_confidence_word", "cross_asr_disagreement"],
        )

    def test_evidence_based_correction_remains_pending_and_is_audited(self) -> None:
        draft = {
            "project_id": "project",
            "subtitle_version": 4,
            "status": "review_required",
            "coverage": {"status": "pending"},
            "merge_policy": {"max_lines": 2, "max_chars_per_line": 8},
            "segment_coverage": [],
            "cues": [
                {
                    "cue_id": "subtitle-v4-0001",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "text": "弄点血拍照",
                    "segment_id": "ch01-s001",
                    "review_status": "review_required",
                    "risk_flags": [],
                }
            ],
        }
        corrected = apply_evidence_based_text_corrections(
            draft,
            [
                {
                    "cue_id": "subtitle-v4-0001",
                    "expected_text": "弄点血拍照",
                    "replacement_text": "弄点雪\n拍照",
                    "reason": "homophone correction",
                    "evidence": [
                        "cross ASR transcribes 雪",
                        "the scene and sentence concern snow photography",
                    ],
                }
            ],
        )

        cue = corrected["cues"][0]
        self.assertEqual(cue["text"], "弄点雪\n拍照")
        self.assertEqual(cue["review_status"], "review_required")
        self.assertIn("machine_text_corrected_review_required", cue["risk_flags"])
        self.assertEqual(corrected["coverage"]["status"], "pending")
        self.assertEqual(corrected["machine_text_corrections"]["count"], 1)
        review = build_subtitle_review_record(corrected)
        self.assertEqual(review["summary"]["reviewed_cue_count"], 0)
        self.assertEqual(review["summary"]["machine_text_correction_count"], 1)
        self.assertEqual(
            review["cue_reviews"][0]["machine_text_correction"]["original_text"],
            "弄点血拍照",
        )

        with self.assertRaisesRegex(ValueError, "at least two evidence"):
            apply_evidence_based_text_corrections(
                draft,
                [
                    {
                        "cue_id": "subtitle-v4-0001",
                        "replacement_text": "弄点雪拍照",
                        "reason": "homophone correction",
                        "evidence": ["one source only"],
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
