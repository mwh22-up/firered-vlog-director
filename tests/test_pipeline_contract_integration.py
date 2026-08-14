from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.approval import (
    _expected_rate_candidate,
    approve_previewed_timeline,
    plan_sha256,
)
from vlog_director.production_contract import bind_directed_base


WORKSPACE = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = next(
    (
        candidate
        for candidate in (
            WORKSPACE / "firered-vlog-pipeline",
            WORKSPACE / "vlog-pipeline",
        )
        if candidate.is_dir()
    ),
    WORKSPACE / "firered-vlog-pipeline",
)


@unittest.skipUnless(PIPELINE_ROOT.is_dir(), "sibling firered-vlog-pipeline is unavailable")
class PipelineContractIntegrationTests(unittest.TestCase):
    def test_playback_rate_derivation_and_review_schema_match_across_repositories(
        self,
    ) -> None:
        sys.path.insert(0, str(PIPELINE_ROOT))
        try:
            from app.playback_rate import build_rate_candidate, canonical_sha256

            plan = {
                "project_id": "synthetic",
                "version": 2,
                "brief": {"target_duration_sec": 12.0},
                "chapters": [
                    {
                        "target_duration_sec": 12.0,
                        "segments": [
                            {
                                "source": "raw/A.mp4",
                                "in_sec": 0.0,
                                "out_sec": 12.0,
                                "story_role": "transition",
                                "reason": "travel",
                            }
                        ],
                    }
                ],
            }
            proposal = {
                "proposal_id": "playback-rate-0123456789abcdef",
                "technique_key": "playback-rate-fast-forward-travel-compression-visual-estimate",
                "category": "playback_rate",
                "executor": "propose_travel_compression_preview",
                "execution_mode": "preview_only",
                "status": "human_rate_selection_required",
                "source_support": 2,
                "average_confidence": 0.8,
                "target_evidence": ["shot:travel:visual.motion=0.11000"],
                "evidence": {
                    "shot_id": "travel",
                    "role": "transition",
                    "duration_sec": 8.0,
                    "speech_ratio": 0.0,
                    "motion": 0.11,
                    "protected_overlap": False,
                    "user_lock_overlap": False,
                    "contains_key_dialogue": False,
                },
                "affected_ranges": [
                    {
                        "source": "raw/A.mp4",
                        "start_sec": 2.0,
                        "end_sec": 10.0,
                        "effect": "travel_compression_preview_without_rate",
                    }
                ],
                "parameters": {
                    "playback_rate": None,
                    "rate_source": "human_preview_selection",
                },
            }
            proposal_sha = canonical_sha256(proposal)
            pipeline_plan = build_rate_candidate(
                plan,
                proposal,
                proposal_sha=proposal_sha,
                playback_rate=1.5,
            )
            director_plan = _expected_rate_candidate(
                plan,
                proposal,
                proposal_sha256=proposal_sha,
                selected_rate=1.5,
            )
            self.assertEqual(pipeline_plan, director_plan)

            pipeline_schema = json.loads(
                (
                    PIPELINE_ROOT
                    / "schemas"
                    / "directed-candidate-review-pack.schema.json"
                ).read_text(encoding="utf-8")
            )
            director_schema = json.loads(
                (
                    Path(__file__).parents[1]
                    / "schemas"
                    / "directed-candidate-review-pack.schema.json"
                ).read_text(encoding="utf-8")
            )
            pipeline_schema.pop("$id", None)
            director_schema.pop("$id", None)
            self.assertEqual(pipeline_schema, director_schema)
        finally:
            sys.path.remove(str(PIPELINE_ROOT))

    def test_pipeline_review_pack_drives_preview_bound_director_approval(self) -> None:
        sys.path.insert(0, str(PIPELINE_ROOT))
        try:
            from app.candidate_preview import build_candidate_review_pack
            from app.plan_approval import validate_plan_approval

            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "projects" / "synthetic"
                proposal = project / "work" / "director" / "v2-proposal"
                candidates = proposal / "candidates"
                candidates.mkdir(parents=True)
                (project / "work" / "plans").mkdir(parents=True)
                (project / "work" / "qa").mkdir(parents=True)
                (project / ".vlog-project.json").write_text(
                    json.dumps({"project_id": "synthetic"}), encoding="utf-8"
                )
                media = root / "media" / "A.mp4"
                media.parent.mkdir(parents=True)
                media.write_bytes(b"proxy-source")
                (project / "work" / "assets.json").write_text(
                    json.dumps(
                        {
                            "assets": [
                                {
                                    "source_relative": "A.mp4",
                                    "source": str(media),
                                    "proxy": str(media),
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )

                candidate_paths: list[Path] = []
                for label, start in (("concise", 0.0), ("immersive", 1.0)):
                    plan = {
                        "schema_version": "1.0",
                        "project_id": "synthetic",
                        "version": 2,
                        "parent_version": 1,
                        "brief": {
                            "target_duration_sec": 1.0,
                            "aspect_ratio": "16:9",
                            "mode": "timeline",
                            "keep_dialogue": False,
                        },
                        "chapters": [
                            {
                                "id": "ch01",
                                "title": label,
                                "target_duration_sec": 1.0,
                                "segments": [
                                    {
                                        "source": "raw/A.mp4",
                                        "in_sec": start,
                                        "out_sec": start + 1.0,
                                        "story_role": "opening",
                                        "reason": label,
                                        "keep_original_audio": True,
                                        "beat_snap": False,
                                        "confidence": 1.0,
                                    }
                                ],
                            }
                        ],
                        "music": [],
                        "qa": [],
                        "created_at": "2026-08-14T00:00:00Z",
                    }
                    candidate_path = candidates / f"candidate.{label}.json"
                    candidate_path.write_text(json.dumps(plan), encoding="utf-8")
                    candidate_paths.append(candidate_path)

                def fake_run(arguments: list[str], _ffmpeg: Path) -> None:
                    output = Path(arguments[-1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"rendered:" + output.name.encode("ascii"))

                with (
                    patch(
                        "app.render_ffmpeg.validate_plan",
                        return_value={
                            "valid": True,
                            "errors": [],
                            "total_duration_sec": 1.0,
                        },
                    ),
                    patch(
                        "app.render_ffmpeg.resolve_media_program",
                        side_effect=lambda name: Path(name),
                    ),
                    patch("app.render_ffmpeg.run_ffmpeg", side_effect=fake_run),
                    patch("app.render_ffmpeg._watermark_font", return_value=media),
                    patch(
                        "app.render_ffmpeg.probe_duration",
                        return_value=1.0,
                    ),
                    patch("app.cut_qa.resolve_media_program", return_value=Path("ffmpeg")),
                ):
                    review_pack = build_candidate_review_pack(
                        project,
                        [
                            ("concise", candidate_paths[0]),
                            ("immersive", candidate_paths[1]),
                        ],
                    )

                review_pack_path = proposal / "review-pack.json"
                selected = review_pack["candidates"][0]
                selection_path = proposal / "selection.json"
                selection_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "contract_version": "directed-preview-selection-v1",
                            "status": "approved",
                            "project_id": "synthetic",
                            "plan_version": 2,
                            "review_pack_sha256": hashlib.sha256(
                                review_pack_path.read_bytes()
                            ).hexdigest(),
                            "selected_label": selected["label"],
                            "selected_candidate_sha256": selected["candidate"]["sha256"],
                            "preview_media_sha256": selected["preview_media"]["sha256"],
                            "realized_timeline_sha256": selected["realized_timeline"]["sha256"],
                            "cut_qa_sha256": selected["cut_qa"]["sha256"],
                            "checks": {
                                "preview_playback": "approved",
                                "visual_continuity": "approved",
                                "speech_completeness": "approved",
                                "audio_continuity": "approved",
                                "story_coherence": "approved",
                            },
                            "selected_by": "integration-reviewer",
                            "selected_at": "2026-08-14T00:10:00Z",
                            "attestation": "I watched the selected non-release preview and approve this timeline for source rendering.",
                        }
                    ),
                    encoding="utf-8",
                )
                approved_plan = project / "work" / "plans" / "edit_plan.v2.json"
                approval_path = project / "work" / "qa" / "edit_plan.v2.approval.json"
                receipt = approve_previewed_timeline(
                    project=project,
                    candidate_path=candidate_paths[0],
                    review_pack_path=review_pack_path,
                    selection_path=selection_path,
                    output_path=approved_plan,
                    receipt_path=approval_path,
                    approved_by="integration-operator",
                )

                approved_document = json.loads(approved_plan.read_text(encoding="utf-8"))
                self.assertEqual(receipt["status"], "approved")
                self.assertEqual(validate_plan_approval(approved_document, approved_plan), [])
                self.assertNotIn("output", Path(selected["preview_media"]["path"]).parts)
        finally:
            sys.path.remove(str(PIPELINE_ROOT))

    def test_pipeline_artifacts_bind_without_manual_timeline_rewriting(self) -> None:
        sys.path.insert(0, str(PIPELINE_ROOT))
        try:
            from app.cut_qa import review_rendered_cuts
            from app.render_ffmpeg import render_plan

            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project = root / "projects" / "synthetic"
                plans = project / "work" / "plans"
                qa = project / "work" / "qa"
                plans.mkdir(parents=True)
                qa.mkdir(parents=True)
                (project / ".vlog-project.json").write_text(
                    json.dumps({"project_id": "synthetic"}), encoding="utf-8"
                )
                source = root / "media" / "A.mp4"
                source.parent.mkdir(parents=True)
                source.write_bytes(b"source-media")
                (project / "work" / "assets.json").write_text(
                    json.dumps(
                        {
                            "assets": [
                                {
                                    "source_relative": "A.mp4",
                                    "source": str(source),
                                    "proxy": str(source),
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                plan = {
                    "schema_version": "1.0",
                    "project_id": "synthetic",
                    "version": 2,
                    "parent_version": 1,
                    "brief": {
                        "target_duration_sec": 1.0,
                        "aspect_ratio": "16:9",
                        "mode": "timeline",
                        "keep_dialogue": False,
                    },
                    "chapters": [
                        {
                            "id": "ch01",
                            "title": "Synthetic",
                            "target_duration_sec": 1.0,
                            "segments": [
                                {
                                    "source": "raw/A.mp4",
                                    "in_sec": 0.0,
                                    "out_sec": 1.0,
                                    "story_role": "opening",
                                    "reason": "contract test",
                                    "keep_original_audio": True,
                                    "beat_snap": False,
                                    "confidence": 1.0,
                                }
                            ],
                        }
                    ],
                    "music": [],
                    "qa": [],
                    "created_at": "2026-08-14T00:00:00Z",
                }
                plan_path = plans / "edit_plan.v2.json"
                plan_path.write_text(json.dumps(plan), encoding="utf-8")
                approval_path = qa / "edit_plan.v2.approval.json"
                approval_path.write_text(
                    json.dumps(
                        {
                            "status": "approved",
                            "project_id": "synthetic",
                            "plan_version": 2,
                            "plan_sha256": plan_sha256(plan),
                        }
                    ),
                    encoding="utf-8",
                )

                def fake_run(arguments: list[str], _ffmpeg: Path) -> None:
                    output = Path(arguments[-1])
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(b"rendered:" + output.name.encode("ascii"))

                with (
                    patch(
                        "app.render_ffmpeg.validate_plan",
                        return_value={
                            "valid": True,
                            "errors": [],
                            "total_duration_sec": 1.0,
                        },
                    ),
                    patch(
                        "app.render_ffmpeg.resolve_media_program",
                        side_effect=lambda name: Path(name),
                    ),
                    patch(
                        "app.render_ffmpeg.guard_render_plan",
                        return_value=(
                            plan,
                            {
                                "status": "passed",
                                "report_path": str(qa / "protection.v2.json"),
                            },
                            hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                        ),
                    ),
                    patch("app.render_ffmpeg.require_guarded_plan_unchanged"),
                    patch("app.render_ffmpeg.run_ffmpeg", side_effect=fake_run),
                    patch(
                        "app.render_ffmpeg.probe_duration",
                        return_value=1.0,
                    ),
                ):
                    render_report = render_plan(
                        project,
                        plan_path,
                        director_python=Path("director-python"),
                    )

                base_media = project / "output" / "directed.v2.mp4"
                timeline_path = qa / "render.v2.json"
                cut_directory = qa / "cut-review.v2"
                with patch("app.cut_qa.resolve_media_program", return_value=Path("ffmpeg")):
                    review_rendered_cuts(
                        base_media,
                        plan,
                        cut_directory,
                        plan_path=plan_path,
                        realized_timeline_path=timeline_path,
                    )
                cut_qa_path = cut_directory / "cut-review.json"
                media_sha = hashlib.sha256(base_media.read_bytes()).hexdigest()
                human_review_path = qa / "directed-base-human-review.v2.json"
                human_review_path.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "contract_version": "directed-base-human-review-v1",
                            "status": "approved",
                            "project_id": "synthetic",
                            "plan_version": 2,
                            "bindings": {
                                "plan_sha256": hashlib.sha256(
                                    plan_path.read_bytes()
                                ).hexdigest(),
                                "realized_timeline_sha256": hashlib.sha256(
                                    timeline_path.read_bytes()
                                ).hexdigest(),
                                "base_media_sha256": media_sha,
                                "cut_qa_sha256": hashlib.sha256(
                                    cut_qa_path.read_bytes()
                                ).hexdigest(),
                            },
                            "checks": {
                                "visual_continuity": "approved",
                                "speech_completeness": "approved",
                                "audio_continuity": "approved",
                                "story_coherence": "approved",
                            },
                            "reviewed_by": "integration-reviewer",
                            "reviewed_at": "2026-08-14T00:10:00Z",
                            "attestation": "I reviewed every rendered cut against the approved edit plan.",
                        }
                    ),
                    encoding="utf-8",
                )

                contract_path = qa / "directed-base.v2.json"
                with (
                    patch(
                        "vlog_director.production_contract.find_ffmpeg",
                        return_value="ffmpeg",
                    ),
                    patch(
                        "vlog_director.production_contract.probe_media",
                        return_value={
                            "duration_sec": 1.0,
                            "width": 160,
                            "height": 90,
                            "has_video": True,
                            "has_audio": True,
                        },
                    ),
                    patch(
                        "vlog_director.production_contract.inspect_ffmpeg_identity",
                        return_value={
                            "executable_sha256": "f" * 64,
                            "version_line": "ffmpeg synthetic",
                        },
                    ),
                ):
                    contract = bind_directed_base(
                        project=project,
                        edit_plan_path=plan_path,
                        approval_path=approval_path,
                        realized_timeline_path=timeline_path,
                        cut_qa_path=cut_qa_path,
                        human_review_path=human_review_path,
                        base_media_path=base_media,
                        output_path=contract_path,
                        producer={
                            "repository": "firered-vlog-pipeline",
                            "commit_sha": "a" * 40,
                            "contract": render_report["contract_version"],
                        },
                    )

                self.assertEqual(contract["status"], "ready")
                self.assertEqual(contract["base_media"]["sha256"], media_sha)
                self.assertEqual(contract["producer"]["contract"], "render-directed-v2")
        finally:
            sys.path.remove(str(PIPELINE_ROOT))


if __name__ == "__main__":
    unittest.main()
