from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from vlog_director.subtitle_layout_probe import (
    inspect_ffmpeg_identity,
    probe_subtitle_layout,
)
from vlog_director.subtitles import write_ass_subtitles


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
        "max_chars_per_line": 22,
        "background_opacity_percent": 50.0,
        "background_padding": 6,
    }
    style.update(overrides)
    return style


class SubtitleLayoutProbeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg = get_ffmpeg_exe()
        cls.identity = inspect_ffmpeg_identity(cls.ffmpeg)
        if not cls.identity["subtitles_filter_available"]:
            raise AssertionError("pinned imageio-ffmpeg must expose the subtitles filter")

    def _write_ass(
        self,
        path: Path,
        cues: list[dict[str, object]],
        style: dict[str, object],
        width: int,
        height: int,
    ) -> None:
        write_ass_subtitles(
            cues,
            path,
            font_name=str(style["font_name"]),
            font_size=int(style["font_size"]),
            margin_v=int(style["margin_v"]),
            outline=int(style["outline"]),
            shadow=int(style["shadow"]),
            bold=bool(style["bold"]),
            position=str(style["position"]),
            max_lines=int(style["max_lines"]),
            safe_margin_percent=float(style["safe_margin_percent"]),
            canvas_width=width,
            canvas_height=height,
            max_chars_per_line=int(style["max_chars_per_line"]),
            minimum_font_size=max(18, int(style["font_size"]) - 8),
            background_opacity_percent=float(style["background_opacity_percent"]),
            background_padding=int(style["background_padding"]),
        )

    def _probe(
        self,
        root: Path,
        *,
        cues: list[dict[str, object]],
        style: dict[str, object],
        width: int,
        height: int,
        mode: str = "preview",
        cache_directory: Path | None = None,
    ) -> dict:
        ass_path = root / f"captions-{width}x{height}.ass"
        self._write_ass(ass_path, cues, style, width, height)
        return probe_subtitle_layout(
            ass_path=ass_path,
            cues=cues,
            style=style,
            canvas_width=width,
            canvas_height=height,
            executable=self.ffmpeg,
            mode=mode,
            cache_directory=cache_directory,
            project_id="integration-test",
            subtitle_source_sha256="a" * 64,
            realized_timeline_sha256="b" * 64,
            readability_qa_sha256="c" * 64,
            readability_policy_sha256="d" * 64,
            readability_policy_version="readability-v1",
        )

    def test_real_libass_measures_language_layout_position_and_canvas_matrix(self) -> None:
        cases = [
            ("zh", "中文测试，数字 123。", "bottom_center", 960, 540),
            ("en", "English words, 123!", "top_center", 960, 540),
            ("mixed-two-line", "中文 Mixed 123\n第二行 punctuation!", "bottom_center", 1920, 1080),
            ("portrait", "Portrait subtitle", "top_center", 1080, 1920),
        ]
        with tempfile.TemporaryDirectory(prefix="firered-layout-real-") as temporary:
            root = Path(temporary)
            for index, (name, text, position, width, height) in enumerate(cases, start=1):
                with self.subTest(case=name):
                    style = _style(position=position, font_size=32 if height == 540 else 64)
                    cue = {
                        "cue_id": f"cue-{index}",
                        "start_sec": 0.0,
                        "end_sec": 1.0,
                        "text": text,
                        "position": position,
                    }
                    report = self._probe(
                        root,
                        cues=[cue],
                        style=style,
                        width=width,
                        height=height,
                    )
                    result = report["cues"][0]
                    self.assertEqual(report["probe_mode"], "real_libass")
                    self.assertIsNotNone(result["measured_bbox"])
                    self.assertFalse(result["clipped"])
                    self.assertEqual(
                        result["real_layout_verified"],
                        bool(result["inside_safe_area"] and not result["clipped"]),
                    )
                    if not result["inside_safe_area"]:
                        self.assertIn(
                            "subtitle_outside_safe_area", result["blocker_codes"]
                        )
                    self.assertEqual(result["line_count"], text.count("\n") + 1)
                    center_y = result["measured_bbox"]["y"] + result["measured_bbox"]["height"] / 2
                    if position == "top_center":
                        self.assertLess(center_y, height / 2)
                    else:
                        self.assertGreater(center_y, height / 2)

    def test_long_text_at_safe_edge_is_measured_not_assumed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-layout-edge-") as temporary:
            root = Path(temporary)
            style = _style(font_size=32, max_chars_per_line=40, safe_margin_percent=10)
            cue = {
                "cue_id": "cue-edge",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "A deliberately long subtitle near the configured safe-area edge",
            }
            report = self._probe(
                root,
                cues=[cue],
                style=style,
                width=960,
                height=540,
            )
            measured = report["cues"][0]
            self.assertIsNotNone(measured["measured_bbox"])
            self.assertIn(measured["inside_safe_area"], {True, False})
            if not measured["inside_safe_area"]:
                self.assertIn("subtitle_outside_safe_area", measured["blocker_codes"])

    def test_cache_is_stable_and_never_crosses_canvas_or_style(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-layout-cache-") as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cue = {
                "cue_id": "cue-cache",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "Cache identity",
            }
            first = self._probe(
                root,
                cues=[cue],
                style=_style(),
                width=960,
                height=540,
                cache_directory=cache,
            )
            second = self._probe(
                root,
                cues=[cue],
                style=_style(),
                width=960,
                height=540,
                cache_directory=cache,
            )
            different_canvas = self._probe(
                root,
                cues=[cue],
                style=_style(font_size=64),
                width=1920,
                height=1080,
                cache_directory=cache,
            )
            different_style = self._probe(
                root,
                cues=[cue],
                style=_style(outline=5),
                width=960,
                height=540,
                cache_directory=cache,
            )

        self.assertFalse(first["cues"][0]["cache_hit"])
        self.assertTrue(second["cues"][0]["cache_hit"])
        self.assertEqual(
            first["cues"][0]["measured_bbox"], second["cues"][0]["measured_bbox"]
        )
        self.assertNotEqual(
            first["cues"][0]["cache_key"],
            different_canvas["cues"][0]["cache_key"],
        )
        self.assertNotEqual(
            first["cues"][0]["cache_key"],
            different_style["cues"][0]["cache_key"],
        )

    def test_forged_cache_cannot_override_identity_or_release_measurement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-layout-cache-forged-") as temporary:
            root = Path(temporary)
            cache = root / "cache"
            cue = {
                "cue_id": "cue-cache-forged",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "Cache must not become proof",
            }
            first = self._probe(
                root,
                cues=[cue],
                style=_style(),
                width=960,
                height=540,
                cache_directory=cache,
            )
            cache_path = next(cache.glob("*.json"))
            document = json.loads(cache_path.read_text(encoding="utf-8"))
            document["measurement"]["cue_id"] = "forged-cue"
            cache_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            preview = self._probe(
                root,
                cues=[cue],
                style=_style(),
                width=960,
                height=540,
                cache_directory=cache,
            )
            self.assertFalse(preview["cues"][0]["cache_hit"])
            self.assertEqual(preview["cues"][0]["cue_id"], cue["cue_id"])

            document = json.loads(cache_path.read_text(encoding="utf-8"))
            forged_bbox = {"x": 100, "y": 100, "width": 1, "height": 1}
            document["measurement"] = {
                "measured_bbox": forged_bbox,
                "measured_pixel_count": 1,
                "clipped": False,
                "inside_safe_area": True,
                "real_layout_verified": True,
                "measurement_method": "ffmpeg-libass-rgb24-control-difference-v1",
                "font_resolution": {
                    "requested_font": "Arial",
                    "status": "resolved",
                    "resolved_faces": ["Arial"],
                    "fallback_detected": False,
                    "missing_glyph_observed": False,
                    "log_sha256": "0" * 64,
                },
            }
            cache_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            release = self._probe(
                root,
                cues=[cue],
                style=_style(),
                width=960,
                height=540,
                mode="release",
                cache_directory=cache,
            )
            self.assertFalse(release["cues"][0]["cache_hit"])
            self.assertNotEqual(release["cues"][0]["measured_bbox"], forged_bbox)
            self.assertEqual(first["cues"][0]["cue_id"], cue["cue_id"])
    def test_missing_font_fallback_is_observed_and_release_blocks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="firered-layout-font-") as temporary:
            root = Path(temporary)
            style = _style(font_name="Definitely Missing Firered Font 9F73")
            cue = {
                "cue_id": "cue-font",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "text": "Fallback 字体",
            }
            preview = self._probe(
                root,
                cues=[cue],
                style=style,
                width=960,
                height=540,
                mode="preview",
            )
            release = self._probe(
                root,
                cues=[cue],
                style=style,
                width=960,
                height=540,
                mode="release",
            )

        self.assertEqual(preview["probe_mode"], "real_libass")
        self.assertTrue(preview["cues"][0]["font_resolution"]["fallback_detected"])
        self.assertIn("font_fallback_unverified", preview["cues"][0]["warning_codes"])
        self.assertEqual(release["status"], "blocked")
        self.assertIn("font_fallback_unverified", release["cues"][0]["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
