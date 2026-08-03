from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from imageio_ffmpeg import get_ffmpeg_exe
from jsonschema import Draft202012Validator

from vlog_director.cli import main


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run(*arguments: object) -> tuple[int, dict]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = ["vlog-director", *(str(argument) for argument in arguments)]
    with (
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = main()
    output = stdout.getvalue().strip()
    return exit_code, json.loads(output) if output else {}


class SubtitleCliIntegrationTests(unittest.TestCase):
    def test_project_subtitles_accepts_portable_timeline_and_writes_review_bundle(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="firered-project-subtitles-cli-"
        ) as temporary:
            root = Path(temporary)
            project = root / "project"
            edit = project / "work" / "plans" / "edit.json"
            timeline = project / "work" / "qa" / "realized.json"
            analysis = project / "work" / "analysis" / "analysis.json"
            draft = project / "work" / "subtitles" / "draft.json"
            review = project / "work" / "subtitles" / "review.json"
            srt = project / "work" / "subtitles" / "draft.srt"
            _write(
                edit,
                {
                    "project_id": "projection-cli",
                    "version": 1,
                    "chapters": [
                        {
                            "id": "c1",
                            "segments": [
                                {
                                    "id": "s1",
                                    "source": "raw/GX000001.MP4",
                                    "in_sec": 0.0,
                                    "out_sec": 2.0,
                                }
                            ],
                        }
                    ],
                },
            )
            _write(
                timeline,
                {
                    "project_id": "projection-cli",
                    "duration_sec": 2.0,
                    "segments": [
                        {"segment_id": "s1", "start_sec": 0.0, "end_sec": 2.0}
                    ],
                },
            )
            _write(
                analysis,
                {
                    "source": {"source_id": "GX000001"},
                    "transcription": {
                        "status": "ready",
                        "provider": "test",
                        "model": "test-model",
                        "language": "zh",
                        "segments": [
                            {
                                "id": "asr-1",
                                "start_sec": 0.2,
                                "end_sec": 1.3,
                                "text": "你好 世界",
                                "avg_logprob": -0.1,
                                "no_speech_probability": 0.0,
                                "words": [
                                    {
                                        "start_sec": 0.2,
                                        "end_sec": 0.7,
                                        "text": "你好",
                                        "probability": 0.99,
                                    },
                                    {
                                        "start_sec": 0.8,
                                        "end_sec": 1.3,
                                        "text": "世界",
                                        "probability": 0.99,
                                    },
                                ],
                            }
                        ],
                    },
                },
            )

            exit_code, result = _run(
                "project-subtitles",
                "--project",
                project,
                "--edit-plan",
                edit,
                "--realized-timeline",
                timeline,
                "--analysis",
                analysis,
                "--subtitle-version",
                1,
                "--draft-output",
                draft,
                "--review-output",
                review,
                "--srt-output",
                srt,
            )

            self.assertEqual(exit_code, 0, result)
            document = json.loads(draft.read_text(encoding="utf-8"))
            self.assertEqual(document["status"], "review_required")
            self.assertEqual(document["readability"]["status"], "review_required")
            self.assertEqual(document["readability"]["policy_version"], "1.0")
            cue_id = document["cues"][0]["cue_id"]
            self.assertTrue(cue_id.startswith("subtitle-v1-"))
            self.assertNotEqual(cue_id, "subtitle-v1-0001")
            self.assertTrue(review.is_file())
            self.assertTrue(srt.is_file())
            for path in (draft, review, srt):
                self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_short_real_media_runs_layout_proxy_and_visual_qa_only(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(
            prefix="firered-subtitle-cli-real-"
        ) as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "explicit-base.mkv"
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=navy:s=320x180:r=10:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=2",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base),
                ],
                check=True,
            )
            source = project / "work" / "subtitles" / "review.json"
            timeline = project / "work" / "qa" / "timeline.json"
            plan = project / "work" / "enhancement" / "plan.json"
            readability = project / "work" / "qa" / "readability.json"
            layout = project / "work" / "qa" / "layout.json"
            proxy = project / "work" / "proxy" / "explicit-proxy"
            manifest_copy = project / "work" / "proxy" / "manifest-copy.json"
            visual = project / "work" / "qa" / "visual.json"
            evidence = project / "work" / "qa" / "visual-evidence"
            style = {
                "font_name": "Arial",
                "font_size": 64,
                "margin_v": 72,
                "outline": 4,
                "shadow": 1,
                "bold": True,
                "position": "bottom_center",
                "max_lines": 2,
                "safe_margin_percent": 8.0,
                "max_chars_per_line": 18,
                "background_opacity_percent": 42.0,
                "background_padding": 8,
            }
            cues = [
                {
                    "cue_id": "cue-one",
                    "segment_id": "s1",
                    "chapter_id": "c1",
                    "start_sec": 0.05,
                    "end_sec": 0.85,
                    "text": "Hello there",
                    "position": "top_center",
                    "review_status": "verified",
                    "risk_flags": [],
                },
                {
                    "cue_id": "cue-two",
                    "segment_id": "s2",
                    "chapter_id": "c2",
                    "start_sec": 1.05,
                    "end_sec": 1.9,
                    "text": "字幕测试 123",
                    "position": "bottom_center",
                    "review_status": "verified",
                    "risk_flags": [],
                },
            ]
            _write(
                source,
                {
                    "schema_version": "1.0",
                    "document_type": "subtitle_review_draft",
                    "project_id": "cli-real",
                    "subtitle_version": 1,
                    "status": "review_required",
                    "language": "zh-CN",
                    "coverage": {"status": "verified"},
                    "style": style,
                    "segment_coverage": [
                        {
                            "segment_id": "s1",
                            "actual_start_sec": 0.0,
                            "actual_end_sec": 0.9,
                        },
                        {
                            "segment_id": "s2",
                            "actual_start_sec": 0.9,
                            "actual_end_sec": 2.0,
                        },
                    ],
                    "cues": cues,
                },
            )
            _write(
                timeline,
                {
                    "schema_version": "1.0",
                    "project_id": "cli-real",
                    "duration_sec": 2.0,
                    "segments": [
                        {"segment_id": "s1", "start_sec": 0.0, "end_sec": 0.9},
                        {"segment_id": "s2", "start_sec": 0.9, "end_sec": 2.0},
                    ],
                },
            )
            _write(plan, {"subtitles": {"style": style}})

            exit_code, audit = _run(
                "audit-subtitles",
                "--project",
                project,
                "--subtitle-source",
                source,
                "--realized-timeline",
                timeline,
                "--output",
                readability,
                "--mode",
                "preview",
            )
            self.assertEqual(exit_code, 0, audit)
            exit_code, measured = _run(
                "probe-subtitle-layout",
                "--project",
                project,
                "--base-video",
                base,
                "--subtitle-source",
                source,
                "--plan",
                plan,
                "--realized-timeline",
                timeline,
                "--readability-qa",
                readability,
                "--output",
                layout,
                "--ffmpeg-executable",
                ffmpeg,
                "--mode",
                "preview",
            )
            self.assertEqual(exit_code, 0, measured)
            measured = json.loads(
                layout.read_text(encoding="utf-8")
            )
            self.assertEqual(measured["probe_mode"], "real_libass")
            self.assertTrue(
                all(item["inside_safe_area"] for item in measured["cues"])
            )

            exit_code, rendered = _run(
                "render-subtitle-preview",
                "--project",
                project,
                "--base-video",
                base,
                "--subtitle-source",
                source,
                "--realized-timeline",
                timeline,
                "--plan",
                plan,
                "--readability-qa",
                readability,
                "--layout-qa",
                layout,
                "--scope",
                "all",
                "--proxy-unit",
                "timeline",
                "--output-directory",
                proxy,
                "--manifest-output",
                manifest_copy,
                "--ffmpeg-executable",
                ffmpeg,
                "--foreground",
            )
            self.assertEqual(exit_code, 0, rendered)
            manifest = project / rendered["manifest_path"]
            self.assertTrue(manifest.is_file())
            self.assertEqual(
                json.loads(manifest_copy.read_text(encoding="utf-8")),
                json.loads(manifest.read_text(encoding="utf-8")),
            )
            render_log = (project / rendered["ffmpeg_log_path"]).read_text(
                encoding="utf-8"
            )
            self.assertIn("subtitles=", render_log)
            for forbidden in ("sidechaincompress", "overlay=", "amix=", "hqdn3d"):
                self.assertNotIn(forbidden, render_log)

            exit_code, report = _run(
                "qa-subtitles",
                "--project",
                project,
                "--preview-manifest",
                manifest,
                "--readability-qa",
                readability,
                "--layout-qa",
                layout,
                "--output",
                visual,
                "--evidence-directory",
                evidence,
                "--ffmpeg-executable",
                ffmpeg,
                "--foreground",
            )
            self.assertEqual(exit_code, 0, report)
            self.assertEqual(report["machine_status"], "passed")
            self.assertEqual(report["human_review"]["status"], "pending")
            self.assertFalse(report["release_ready"])
            self.assertEqual(report["missing_cue_ids"], [])
            self.assertEqual(len(report["cue_evidence"]), 2)
            schema = json.loads(
                (ROOT / "schemas" / "subtitle-visual-qa.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                list(Draft202012Validator(schema).iter_errors(report)), []
            )


if __name__ == "__main__":
    unittest.main()
