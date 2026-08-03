from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from vlog_director.subtitle_layout_probe import (
    LAYOUT_PROBE_VERSION,
    build_layout_cache_key,
    font_directory_identity,
    probe_subtitle_layout,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _style(**overrides: object) -> dict[str, object]:
    style: dict[str, object] = {
        "font_name": "Arial",
        "font_size": 32,
        "margin_v": 24,
        "outline": 3,
        "shadow": 1,
        "bold": True,
        "position": "bottom_center",
        "max_lines": 2,
        "safe_margin_percent": 8.0,
        "max_chars_per_line": 18,
        "background_opacity_percent": 42.0,
        "background_padding": 6,
    }
    style.update(overrides)
    return style


def _cue(**overrides: object) -> dict[str, object]:
    cue: dict[str, object] = {
        "cue_id": "cue-stable-001",
        "start_sec": 0.0,
        "end_sec": 1.0,
        "text": "Readable subtitle",
        "position": "bottom_center",
    }
    cue.update(overrides)
    return cue


class SubtitleLayoutProbeUnitTests(unittest.TestCase):
    def test_cache_key_binds_every_rendering_input(self) -> None:
        base = {
            "text": "one\ntwo",
            "style": _style(),
            "canvas": {"width": 960, "height": 540},
            "font_directory": {"present": False, "sha256": None, "file_count": 0},
            "ffmpeg": {
                "executable_sha256": "1" * 64,
                "version_line": "ffmpeg version test",
                "filters_sha256": "2" * 64,
            },
            "probe_version": LAYOUT_PROBE_VERSION,
        }
        expected = build_layout_cache_key(**base)
        self.assertEqual(expected, build_layout_cache_key(**base))

        mutations = [
            {"text": "one two"},
            {"style": _style(outline=4)},
            {"canvas": {"width": 1920, "height": 1080}},
            {
                "font_directory": {
                    "present": True,
                    "sha256": "3" * 64,
                    "file_count": 1,
                }
            },
            {
                "ffmpeg": {
                    "executable_sha256": "4" * 64,
                    "version_line": "ffmpeg version test",
                    "filters_sha256": "2" * 64,
                }
            },
            {"probe_version": "different-probe-version"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                changed = dict(base)
                changed.update(mutation)
                self.assertNotEqual(expected, build_layout_cache_key(**changed))

    def test_font_directory_identity_is_content_bound_and_portable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-font-identity-") as temporary:
            fonts = Path(temporary) / "fonts"
            fonts.mkdir()
            (fonts / "A.ttf").write_bytes(b"font-a")
            (fonts / "ignore.txt").write_text("not a font", encoding="utf-8")

            first = font_directory_identity(fonts)
            self.assertTrue(first["present"])
            self.assertEqual(first["file_count"], 1)
            self.assertEqual(first["files"][0]["path"], "A.ttf")
            self.assertNotIn(str(fonts), json.dumps(first))
            (fonts / "A.ttf").write_bytes(b"font-b")
            second = font_directory_identity(fonts)
            self.assertNotEqual(first["sha256"], second["sha256"])

    def test_preview_falls_back_with_warning_but_release_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-layout-fallback-") as temporary:
            ass_path = Path(temporary) / "captions.ass"
            ass_path.write_text("[Script Info]\nScriptType: v4.00+\n", encoding="utf-8")
            common = dict(
                ass_path=ass_path,
                cues=[_cue()],
                style=_style(),
                canvas_width=960,
                canvas_height=540,
                executable="missing-ffmpeg-for-layout-probe",
                project_id="project-test",
                subtitle_source_sha256="a" * 64,
                realized_timeline_sha256="b" * 64,
                readability_qa_sha256="c" * 64,
                readability_policy_sha256="d" * 64,
                readability_policy_version="readability-v1",
            )
            preview = probe_subtitle_layout(mode="preview", **common)
            release = probe_subtitle_layout(mode="release", **common)

        self.assertEqual(preview["status"], "warning")
        self.assertEqual(preview["probe_mode"], "heuristic")
        self.assertIn("real_layout_probe_unavailable", preview["warning_codes"])
        self.assertEqual(preview["cues"][0]["measured_bbox"], None)
        self.assertFalse(preview["cues"][0]["real_layout_verified"])
        self.assertEqual(release["status"], "blocked")
        self.assertIn("real_layout_probe_required", release["blocker_codes"])

    def test_missing_subtitles_filter_is_preview_warning_and_release_blocker(self) -> None:
        identity = {
            "executable_name": "ffmpeg.exe",
            "executable_size_bytes": 100,
            "executable_sha256": "1" * 64,
            "version_line": "ffmpeg version test",
            "configuration_sha256": "2" * 64,
            "filters_sha256": "3" * 64,
            "subtitles_filter_available": False,
            "libass_enabled": False,
        }
        with tempfile.TemporaryDirectory(prefix="firered-layout-filter-") as temporary:
            ass_path = Path(temporary) / "captions.ass"
            ass_path.write_text("[Script Info]\nScriptType: v4.00+\n", encoding="utf-8")
            common = dict(
                ass_path=ass_path,
                cues=[_cue()],
                style=_style(),
                canvas_width=960,
                canvas_height=540,
                executable="ffmpeg",
                project_id="project-test",
                subtitle_source_sha256="a" * 64,
                realized_timeline_sha256="b" * 64,
                readability_qa_sha256="c" * 64,
                readability_policy_sha256="d" * 64,
                readability_policy_version="readability-v1",
            )
            with patch(
                "vlog_director.subtitle_layout_probe.inspect_ffmpeg_identity",
                return_value=identity,
            ):
                preview = probe_subtitle_layout(mode="preview", **common)
                release = probe_subtitle_layout(mode="release", **common)

        self.assertIn("subtitles_filter_unavailable", preview["warning_codes"])
        self.assertIn("subtitles_filter_unavailable", release["blocker_codes"])

    def test_formal_and_runtime_schemas_match_and_fail_closed(self) -> None:
        formal = json.loads(
            (REPOSITORY_ROOT / "schemas" / "subtitle-layout-qa.schema.json").read_text(
                encoding="utf-8"
            )
        )
        runtime = json.loads(
            (
                REPOSITORY_ROOT
                / "src"
                / "vlog_director"
                / "schemas"
                / "subtitle-layout-qa.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(formal, runtime)
        Draft202012Validator.check_schema(formal)
        self.assertFalse(formal["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
