from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe
from jsonschema import Draft202012Validator

from vlog_director.subtitle_preview import render_subtitle_preview
from vlog_director.subtitle_readability import (
    SubtitleReadabilityPolicy,
    audit_subtitle_readability,
)


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class SubtitlePreviewIntegrationTests(unittest.TestCase):
    def test_real_libass_risk_preview_only_burns_selected_cue(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        inventory = subprocess.run([ffmpeg, "-hide_banner", "-filters"], check=True,
                                   capture_output=True, text=True).stdout
        self.assertIn(" subtitles ", inventory)
        with tempfile.TemporaryDirectory(prefix="firered-subtitle-preview-") as temporary:
            root = Path(temporary)
            project = root / "project"
            base = root / "explicit-base.mkv"
            subprocess.run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=white:s=320x180:r=10:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                "-c:v", "ffv1", "-c:a", "pcm_s16le", "-shortest", str(base),
            ], check=True)
            source = project / "work" / "subtitles" / "source.json"
            timeline = project / "work" / "qa" / "timeline.json"
            readability = project / "work" / "qa" / "readability.json"
            _write(source, {
                "schema_version": "1.0", "project_id": "synthetic", "status": "review_required",
                "language": "en", "style": {"font_name": "Arial", "font_size": 64,
                    "margin_v": 72, "outline": 4, "shadow": 1, "bold": True,
                    "position": "bottom_center", "max_lines": 2,
                    "safe_margin_percent": 8.0, "max_chars_per_line": 18,
                    "background_opacity_percent": 42.0, "background_padding": 8},
                "cues": [
                    {"cue_id": "risk-cue", "segment_id": "s1", "chapter_id": "c1",
                     "start_sec": 0.4, "end_sec": 1.2, "text": "VISIBLE RISK",
                     "review_status": "review_required"},
                    {"cue_id": "ordinary-cue", "segment_id": "s2", "chapter_id": "c2",
                     "start_sec": 1.8, "end_sec": 2.8, "text": "MUST NOT RENDER",
                     "review_status": "review_required"},
                ]})
            _write(timeline, {"schema_version": "1.0", "project_id": "synthetic",
                "duration_sec": 3.0, "segments": [
                    {"segment_id": "s1", "start_sec": 0.0, "end_sec": 1.5},
                    {"segment_id": "s2", "start_sec": 1.5, "end_sec": 3.0}]})
            source_document = json.loads(source.read_text(encoding="utf-8"))
            source_document["coverage"] = {"status": "pending"}
            source_document["segment_coverage"] = [
                {"segment_id": "s1", "actual_start_sec": 0.0, "actual_end_sec": 1.5},
                {"segment_id": "s2", "actual_start_sec": 1.5, "actual_end_sec": 3.0},
            ]
            for cue in source_document["cues"]:
                cue["risk_flags"] = (
                    ["machine_text_corrected_review_required"]
                    if cue["cue_id"] == "risk-cue"
                    else []
                )
            _write(source, source_document)
            _write(
                readability,
                audit_subtitle_readability(
                    source_document,
                    policy=SubtitleReadabilityPolicy(cut_boundary_tolerance_sec=0.1),
                    mode="preview",
                    subtitle_source_sha256=_sha(source),
                    realized_timeline_sha256=_sha(timeline),
                ),
            )

            manifest = render_subtitle_preview(
                project=project, base_video=base, subtitle_source=source,
                realized_timeline=timeline, readability_qa=readability,
                scope="risk", proxy_unit="cue", padding_sec=0.2,
                executable=ffmpeg)

            schema = json.loads((ROOT / "schemas" / "subtitle-preview-manifest.schema.json").read_text())
            self.assertEqual(list(Draft202012Validator(schema).iter_errors(manifest)), [])
            self.assertEqual(manifest["selection"]["unrendered_due_to_scope_cue_ids"],
                             ["ordinary-cue"])
            output = manifest["outputs"][0]
            proxy, ass = project / output["media_path"], project / output["ass_path"]
            self.assertEqual(output["trigger_cue_ids"], ["risk-cue"])
            self.assertEqual(output["rendered_cue_ids"], ["risk-cue"])
            self.assertEqual(_sha(proxy), output["media_sha256"])
            self.assertEqual(_sha(ass), output["ass_sha256"])
            self.assertIn("VISIBLE RISK", ass.read_text(encoding="utf-8"))
            self.assertNotIn("MUST NOT RENDER", ass.read_text(encoding="utf-8"))
            self.assertTrue((project / manifest["progress_path"]).is_file())
            self.assertTrue((project / manifest["ffmpeg_log_path"]).is_file())
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-xerror",
                            "-i", str(proxy), "-map", "0:v:0", "-map", "0:a:0",
                            "-f", "null", os.devnull], check=True)


if __name__ == "__main__":
    unittest.main()
