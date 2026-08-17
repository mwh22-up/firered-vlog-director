from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from vlog_director.enhancement import build_enhancement_plan
from vlog_director.enhancement_assets import validate_enhancement_assets
from vlog_director.ffmpeg import probe_media, run_command
from vlog_director.renderers import render_enhanced_video
from vlog_director.visual_treatment_analysis import analyze_visual_segments
from vlog_director.visual_treatment_approval import (
    apply_approved_visual_treatments,
    build_visual_treatment_approval,
    validate_visual_treatment_approval,
)
from vlog_director.visual_treatment_preview import (
    qa_visual_treatments,
    render_treatment_previews,
)
from vlog_director.visual_treatments import build_visual_treatment_plan


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class VisualTreatmentIntegrationTests(unittest.TestCase):
    def test_real_ffmpeg_analysis_preview_qa_approval_apply_and_render(self) -> None:
        ffmpeg = get_ffmpeg_exe()
        with tempfile.TemporaryDirectory(prefix="firered-visual-treatment-") as temporary:
            project = Path(temporary) / "project"
            base = project / "output" / "directed.v1.mkv"
            base.parent.mkdir(parents=True)
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
                    "color=c=0x303030:size=160x90:rate=12:duration=1.8",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1.8",
                    "-c:v",
                    "ffv1",
                    "-c:a",
                    "pcm_s16le",
                    "-shortest",
                    str(base),
                ]
            )
            edit_plan = {
                "schema_version": "1.0",
                "project_id": "visual-integration",
                "version": 1,
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "抵达",
                        "segments": [
                            {
                                "id": "seg-1",
                                "source": "raw/a.mp4",
                                "in_sec": 0.0,
                                "out_sec": 1.8,
                                "story_role": "establishing",
                                "keep_original_audio": True,
                            }
                        ],
                    }
                ],
            }
            edit_path = project / "work" / "plans" / "edit_plan.v1.json"
            _write(edit_path, edit_plan)
            realized = {
                "duration_sec": 1.8,
                "base_size_bytes": base.stat().st_size,
                "base_sha256": _sha(base),
                "segments": [
                    {"segment_id": "seg-1", "start_sec": 0.0, "end_sec": 1.8}
                ],
            }
            realized_path = project / "work" / "qa" / "realized.v1.json"
            _write(
                realized_path,
                {
                    "project_id": "visual-integration",
                    "version": 1,
                    "actual_duration_sec": 1.8,
                    "output_identity": {
                        "size_bytes": base.stat().st_size,
                        "sha256": _sha(base),
                    },
                    "segment_measurements": [
                        {
                            "chapter_id": "ch01",
                            "segment_index": 1,
                            "source": "raw/a.mp4",
                            "actual_start_sec": 0.0,
                            "actual_end_sec": 1.8,
                        }
                    ],
                    "cut_boundaries": [],
                },
            )
            analysis_path = (
                project / "work" / "analysis" / "visual" / "analysis.v1.json"
            )
            analysis = analyze_visual_segments(
                project,
                base,
                edit_path,
                realized_path,
                analysis_path,
                executable=ffmpeg,
            )
            self.assertEqual(len(analysis["segments"]), 1)
            self.assertLess(analysis["segments"][0]["metrics"]["luma_mean"], 0.42)

            treatment_plan = build_visual_treatment_plan(
                edit_plan,
                analysis,
                analysis_path=analysis_path.relative_to(project).as_posix(),
                analysis_sha256=_sha(analysis_path),
            )
            plan_path = project / "work" / "treatments" / "plan.v1.json"
            _write(plan_path, treatment_plan)
            self.assertEqual(len(treatment_plan["proposals"]), 1)

            preview_directory = project / "work" / "proxy" / "treatments" / "job-1"
            manifest = render_treatment_previews(
                project,
                base,
                plan_path,
                realized_path,
                preview_directory,
                executable=ffmpeg,
            )
            manifest_path = preview_directory / "preview-manifest.json"
            preview_media = project / manifest["previews"][0]["path"]
            preview_probe = probe_media(ffmpeg, preview_media)
            self.assertEqual(preview_probe["width"], 320)
            self.assertEqual(preview_probe["height"], 90)

            qa_directory = project / "work" / "qa" / "treatments" / "job-1"
            qa = qa_visual_treatments(
                project,
                plan_path,
                manifest_path,
                qa_directory,
                executable=ffmpeg,
            )
            self.assertEqual(qa["status"], "passed", qa)
            self.assertEqual(
                {row["role"] for row in qa["proposals"][0]["frames"]},
                {"entry", "middle", "exit"},
            )
            qa_path = qa_directory / "visual-qa.json"
            human_path = qa_directory / "human-review.json"
            proposal_id = treatment_plan["proposals"][0]["proposal_id"]
            _write(
                human_path,
                {
                    "schema_version": "1.0",
                    "contract_version": "visual-treatment-human-review-v1",
                    "status": "approved",
                    "reviewer": "Test Editor",
                    "reviewed_at": "2026-08-15T12:00:00+08:00",
                    "plan_sha256": _sha(plan_path),
                    "treatment_payload_sha256": treatment_plan[
                        "treatment_payload_sha256"
                    ],
                    "preview_manifest_sha256": _sha(manifest_path),
                    "visual_qa_sha256": _sha(qa_path),
                    "base_media_sha256": _sha(base),
                    "proposals": [
                        {
                            "proposal_id": proposal_id,
                            "decision": "accepted",
                            "checks": ["exposure", "color", "detail", "composition"],
                        }
                    ],
                    "attestation": "I reviewed every before/after visual treatment preview.",
                },
            )
            approval_path = qa_directory / "approval.json"
            approval = build_visual_treatment_approval(
                project,
                plan_path,
                manifest_path,
                qa_path,
                human_path,
                approval_path,
            )
            self.assertEqual(approval["accepted_proposal_ids"], [proposal_id])
            self.assertEqual(
                validate_visual_treatment_approval(
                    project,
                    plan_path,
                    manifest_path,
                    qa_path,
                    human_path,
                    approval_path,
                )["status"],
                "passed",
            )

            enhancement = build_enhancement_plan(edit_plan)
            enhancement["subtitles"]["status"] = "disabled"
            enhancement["illustration_motion"]["status"] = "disabled"
            enhancement_path = (
                project / "work" / "enhancement" / "enhancement_plan.v1.json"
            )
            _write(enhancement_path, enhancement)
            applied_path = (
                project / "work" / "enhancement" / "enhancement_plan.v2.json"
            )
            applied = apply_approved_visual_treatments(
                project,
                enhancement_path,
                plan_path,
                manifest_path,
                qa_path,
                human_path,
                approval_path,
                applied_path,
            )
            self.assertGreater(
                applied["video_treatments"][0]["visual"]["brightness"], 0
            )
            self.assertEqual(validate_enhancement_assets(project, applied), [])

            output = project / "output" / "enhanced.v2.mp4"
            render_enhanced_video(
                project,
                base,
                applied,
                output,
                executable=ffmpeg,
                realized_timeline=realized,
                video_preset="veryfast",
                video_crf=24,
            )
            self.assertTrue(output.is_file())

            changed = copy.deepcopy(applied)
            changed["video_treatments"][0]["visual"]["brightness"] += 0.01
            codes = {
                row["code"] for row in validate_enhancement_assets(project, changed)
            }
            self.assertIn("visual_treatment_payload_sha_mismatch", codes)


if __name__ == "__main__":
    unittest.main()
