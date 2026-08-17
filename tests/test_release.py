import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from vlog_director.ffmpeg import run_command
from vlog_director.release import release_readiness_issues, verify_rendered_media


class ReleaseTests(unittest.TestCase):
    def test_release_pixel_treatments_require_current_approval_evidence(self) -> None:
        plan = {
            "video_treatments": [
                {"segment_id": "s1", "visual": {"brightness": 0.05}}
            ],
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {"status": "disabled", "cues": []},
            "illustration_motion": {"status": "disabled", "items": []},
        }
        codes = {row["code"] for row in release_readiness_issues(plan)}
        self.assertIn("release_visual_treatment_evidence_required", codes)

    def test_release_keeps_legacy_static_overlays_preview_only(self) -> None:
        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {"status": "disabled", "cues": []},
            "illustration_motion": {
                "status": "ready",
                "items": [{"id": "legacy", "type": "title_card"}],
            },
        }
        codes = {row["code"] for row in release_readiness_issues(plan)}
        self.assertIn("release_static_overlay_preview_only", codes)

    def test_release_hyperframes_requires_effect_approval_evidence(self) -> None:
        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {"status": "disabled", "cues": []},
            "illustration_motion": {
                "status": "ready",
                "items": [{"id": "motion", "type": "hyperframes"}],
            },
        }
        codes = {row["code"] for row in release_readiness_issues(plan)}
        self.assertIn("release_effect_evidence_required", codes)

    def test_release_rejects_planned_and_empty_ready_sections(self) -> None:
        plan = {
            "music": {"status": "planned", "tracks": []},
            "subtitles": {"status": "ready", "cues": []},
            "illustration_motion": {"status": "disabled", "items": []},
        }

        issues = release_readiness_issues(plan)

        self.assertEqual(
            {issue["code"] for issue in issues},
            {
                "release_section_planned",
                "release_ready_section_empty",
                "release_subtitle_evidence_legacy",
            },
        )

    def test_release_rejects_music_still_in_audition(self) -> None:
        plan = {
            "music": {"status": "audition", "tracks": [{"id": "bed"}]},
            "subtitles": {"status": "disabled", "cues": []},
            "illustration_motion": {"status": "disabled", "items": []},
        }

        issues = release_readiness_issues(plan)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "release_section_not_ready")
        self.assertEqual(issues[0]["subject_id"], "music")

    def test_release_rejects_subtitles_still_in_review(self) -> None:
        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {
                "status": "review",
                "cues": [{"text": "Review subtitle"}],
            },
            "illustration_motion": {"status": "disabled", "items": []},
        }

        issues = release_readiness_issues(plan)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "release_section_not_ready")
        self.assertEqual(issues[0]["subject_id"], "subtitles")

    def test_release_ready_subtitles_require_complete_evidence_contract(self) -> None:
        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {
                "status": "ready",
                "cues": [{"text": "Verified subtitle"}],
            },
            "illustration_motion": {"status": "disabled", "items": []},
        }

        issues = release_readiness_issues(plan)

        self.assertIn(
            "release_subtitle_evidence_legacy",
            {item["code"] for item in issues},
        )

    def test_release_accepts_structurally_complete_ready_evidence(self) -> None:
        def bound(suffix: str) -> dict[str, str]:
            return {
                "path": f"work/qa/{suffix}.json",
                "sha256": "a" * 64,
            }

        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {
                "status": "ready",
                "cues": [{"text": "Verified subtitle"}],
                "evidence": {
                    "contract_version": "subtitle-ready-evidence-v1",
                    "subtitle_payload_sha256": "b" * 64,
                    "subtitle_style_sha256": "c" * 64,
                    "verified_cue_set_sha256": "d" * 64,
                    "readability": bound("readability"),
                    "layout": bound("layout"),
                    "visual": bound("visual"),
                    "human_review": bound("human-review"),
                    "approval": bound("subtitle-approval"),
                },
            },
            "illustration_motion": {"status": "disabled", "items": []},
        }

        self.assertEqual(release_readiness_issues(plan), [])

    def test_release_rejects_malformed_ready_evidence_without_trusting_status(
        self,
    ) -> None:
        plan = {
            "music": {"status": "disabled", "tracks": []},
            "subtitles": {
                "status": "ready",
                "cues": [{"text": "x"}],
                "evidence": {"contract_version": "subtitle-ready-evidence-v1"},
            },
            "illustration_motion": {"status": "disabled", "items": []},
        }

        codes = {item["code"] for item in release_readiness_issues(plan)}
        self.assertIn("release_subtitle_evidence_invalid", codes)

    def test_media_verification_blocks_corrupt_and_missing_stream_outputs(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        plan = {"timeline_duration_sec": 1.0}
        with tempfile.TemporaryDirectory(prefix="firered-release-") as temporary:
            root = Path(temporary)
            corrupt = root / "corrupt.mp4"
            corrupt.write_bytes(b"not media")
            _, corrupt_issues = verify_rendered_media(
                corrupt,
                plan,
                realized_timeline=None,
                executable=ffmpeg,
            )
            self.assertIn(
                "render_media_probe_failed",
                {issue["code"] for issue in corrupt_issues},
            )

            video_only = root / "video-only.mp4"
            run_command(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=160x90:rate=10:duration=1",
                    "-an",
                    "-c:v",
                    "libx264",
                    str(video_only),
                ]
            )
            evidence, stream_issues = verify_rendered_media(
                video_only,
                plan,
                realized_timeline=None,
                executable=ffmpeg,
            )
            self.assertIn(
                "render_stream_layout_invalid",
                {issue["code"] for issue in stream_issues},
            )
            self.assertEqual(evidence["full_decode"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
