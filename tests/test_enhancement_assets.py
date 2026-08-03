from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.enhancement_assets import validate_enhancement_assets
from vlog_director.renderers import render_enhanced_video


REQUIRED_SCOPES = [
    "synchronize",
    "modify",
    "render",
    "distribute_with_project",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class EnhancementAssetValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.music_path = self.project / "assets" / "music" / "bed.wav"
        self.music_path.parent.mkdir(parents=True)
        self.music_path.write_bytes(b"approved project music")
        self.manifest_path = self.music_path.parent / "rights.json"
        self.audition_path = self.project / "work" / "qa" / "audition.json"
        self.manifest = {
            "rights_approval": {
                "status": "approved",
                "rights_holder": "Project Owner",
                "approved_by": "Project Owner",
                "approved_at": "2026-08-03T12:00:00Z",
                "required_scope": REQUIRED_SCOPES,
            },
            "assets": [
                {
                    "id": "bed",
                    "path": "bed.wav",
                    "size_bytes": self.music_path.stat().st_size,
                    "sha256": _sha256(self.music_path),
                }
            ],
        }
        self.audition = {
            "status": "passed",
            "blocking_items": [],
            "assets": [{"id": "bed", "audition_status": "passed"}],
        }
        _write_json(self.manifest_path, self.manifest)
        _write_json(self.audition_path, self.audition)
        self.plan = {
            "music": {
                "status": "ready",
                "rights_manifest": "assets/music/rights.json",
                "audition_report": "work/qa/audition.json",
                "tracks": [
                    {
                        "id": "bed",
                        "source": "assets/music/bed.wav",
                        "start_sec": 0.0,
                        "end_sec": 1.0,
                        "gain_db": -18.0,
                    }
                ],
            },
            "subtitles": {"status": "planned", "cues": []},
            "illustration_motion": {"status": "ready", "items": []},
        }

    def _codes(self, plan: dict | None = None) -> set[str]:
        return {
            issue["code"]
            for issue in validate_enhancement_assets(
                self.project,
                self.plan if plan is None else plan,
            )
        }

    def _ready_subtitle_plan(self) -> dict:
        cue = {
            "start_sec": 0.25,
            "end_sec": 1.5,
            "text": "Verified subtitle",
            "review_status": "verified",
            "position": "bottom_center",
        }
        source_path = self.project / "work" / "subtitles" / "reviewed.json"
        source_cue = {**cue, "cue_id": "subtitle-0001", "segment_id": "segment-1"}
        _write_json(
            source_path,
            {
                "status": "ready",
                "coverage": {"status": "verified", "cue_count": 1},
                "cues": [source_cue],
            },
        )
        plan = copy.deepcopy(self.plan)
        plan["music"] = {"status": "planned", "tracks": []}
        plan["subtitles"] = {
            "status": "ready",
            "source": "work/subtitles/reviewed.json",
            "source_sha256": _sha256(source_path),
            "coverage": {"status": "verified"},
            "cues": [cue],
        }
        return plan

    def _review_subtitle_plan(self) -> dict:
        cue = {
            "start_sec": 0.25,
            "end_sec": 1.5,
            "text": "Review subtitle",
            "review_status": "review_required",
        }
        source_path = self.project / "work" / "subtitles" / "review-required.json"
        _write_json(
            source_path,
            {
                "status": "review_required",
                "coverage": {"status": "pending"},
                "cues": [{**cue, "cue_id": "subtitle-0001"}],
            },
        )
        plan = copy.deepcopy(self.plan)
        plan["music"] = {"status": "planned", "tracks": []}
        plan["subtitles"] = {
            "status": "review",
            "source": "work/subtitles/review-required.json",
            "source_sha256": _sha256(source_path),
            "coverage": {"status": "pending"},
            "cues": [cue],
        }
        return plan

    def test_fully_approved_music_assets_pass(self) -> None:
        self.assertEqual(validate_enhancement_assets(self.project, self.plan), [])

    def test_overlay_path_traversal_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["music"] = {"status": "planned", "tracks": []}
        asset = self.project / "assets" / "title.png"
        asset.write_bytes(b"png")
        plan["illustration_motion"]["items"] = [
            {
                "id": "title",
                "source": "assets/illustrations/../title.png",
            }
        ]

        self.assertIn("enhancement_asset_path_invalid", self._codes(plan))

    def test_absolute_drive_relative_and_unc_paths_are_rejected(self) -> None:
        invalid_paths = [
            str((self.project / "assets" / "music" / "bed.wav").resolve()),
            "C:assets/music/bed.wav",
            r"\\server\share\bed.wav",
        ]
        for source in invalid_paths:
            with self.subTest(source=source):
                plan = copy.deepcopy(self.plan)
                plan["music"]["tracks"][0]["source"] = source
                self.assertIn("enhancement_asset_path_invalid", self._codes(plan))

    def test_missing_overlay_file_is_rejected(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["music"] = {"status": "planned", "tracks": []}
        plan["illustration_motion"]["items"] = [
            {"id": "missing", "source": "assets/illustrations/missing.png"}
        ]

        self.assertIn("enhancement_asset_missing", self._codes(plan))

    def test_music_sha_mismatch_is_rejected(self) -> None:
        self.manifest["assets"][0]["sha256"] = "0" * 64
        _write_json(self.manifest_path, self.manifest)

        self.assertIn("music_asset_sha256_mismatch", self._codes())

    def test_audition_allows_pending_rights_and_listening_results(self) -> None:
        self.plan["music"]["status"] = "audition"
        self.manifest["rights_approval"]["status"] = "pending_user_confirmation"
        self.audition["status"] = "pending"
        self.audition["blocking_items"] = ["Listen in context"]
        self.audition["assets"][0]["audition_status"] = "pending"
        _write_json(self.manifest_path, self.manifest)
        _write_json(self.audition_path, self.audition)

        self.assertEqual(validate_enhancement_assets(self.project, self.plan), [])

    def test_audition_still_rejects_music_sha_mismatch(self) -> None:
        self.plan["music"]["status"] = "audition"
        self.manifest["assets"][0]["sha256"] = "0" * 64
        _write_json(self.manifest_path, self.manifest)

        self.assertIn("music_asset_sha256_mismatch", self._codes())

    def test_audition_requires_selected_track_in_report(self) -> None:
        self.plan["music"]["status"] = "audition"
        self.audition["assets"] = []
        _write_json(self.audition_path, self.audition)

        self.assertIn("music_track_audition_missing", self._codes())

    def test_pending_music_rights_are_rejected(self) -> None:
        self.manifest["rights_approval"]["status"] = "pending_user_confirmation"
        _write_json(self.manifest_path, self.manifest)

        self.assertIn("music_rights_not_approved", self._codes())

    def test_pending_music_audition_is_rejected(self) -> None:
        self.audition["status"] = "pending"
        self.audition["blocking_items"] = ["Listen in context"]
        self.audition["assets"][0]["audition_status"] = "pending"
        _write_json(self.audition_path, self.audition)

        codes = self._codes()
        self.assertIn("music_audition_not_passed", codes)
        self.assertIn("music_audition_blocked", codes)
        self.assertIn("music_track_audition_not_passed", codes)

    def test_ready_subtitle_source_and_plan_pass_when_equivalent(self) -> None:
        plan = self._ready_subtitle_plan()

        self.assertEqual(validate_enhancement_assets(self.project, plan), [])

    def test_review_subtitle_source_and_plan_pass_when_equivalent(self) -> None:
        plan = self._review_subtitle_plan()

        self.assertEqual(validate_enhancement_assets(self.project, plan), [])

    def test_review_subtitle_source_sha_and_projection_are_enforced(self) -> None:
        plan = self._review_subtitle_plan()
        plan["subtitles"]["source_sha256"] = "0" * 64
        plan["subtitles"]["cues"][0]["text"] = "changed"

        codes = self._codes(plan)
        self.assertIn("subtitle_source_sha256_mismatch", codes)
        self.assertIn("subtitle_source_plan_mismatch", codes)

    def test_ready_subtitle_source_path_is_confined(self) -> None:
        plan = self._ready_subtitle_plan()
        plan["subtitles"]["source"] = "work/subtitles/../reviewed.json"

        self.assertIn("enhancement_asset_path_invalid", self._codes(plan))

    def test_ready_subtitle_source_sha_must_match(self) -> None:
        plan = self._ready_subtitle_plan()
        plan["subtitles"]["source_sha256"] = "0" * 64

        self.assertIn("subtitle_source_sha256_mismatch", self._codes(plan))

    def test_ready_subtitle_plan_coverage_must_be_verified(self) -> None:
        plan = self._ready_subtitle_plan()
        plan["subtitles"]["coverage"]["status"] = "pending"

        self.assertIn("subtitle_plan_coverage_unverified", self._codes(plan))

    def test_ready_subtitle_source_must_be_reviewed_and_equivalent(self) -> None:
        plan = self._ready_subtitle_plan()
        source_path = self.project / plan["subtitles"]["source"]
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["status"] = "review_required"
        source["coverage"]["status"] = "pending"
        source["cues"][0]["review_status"] = "review_required"
        _write_json(source_path, source)
        plan["subtitles"]["source_sha256"] = _sha256(source_path)

        codes = self._codes(plan)
        self.assertIn("subtitle_source_not_ready", codes)
        self.assertIn("subtitle_source_coverage_unverified", codes)
        self.assertIn("subtitle_source_cue_unverified", codes)
        self.assertIn("subtitle_source_plan_mismatch", codes)

    def test_renderer_rejects_assets_before_ffmpeg_discovery(self) -> None:
        self.manifest["rights_approval"]["status"] = "pending"
        _write_json(self.manifest_path, self.manifest)
        base_video = self.project / "base.mkv"
        base_video.write_bytes(b"base")

        with (
            patch("vlog_director.renderers.find_ffmpeg") as find_ffmpeg,
            self.assertRaisesRegex(ValueError, "asset validation failed"),
        ):
            render_enhanced_video(
                self.project,
                base_video,
                self.plan,
                self.project / "output.mp4",
            )
        find_ffmpeg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
