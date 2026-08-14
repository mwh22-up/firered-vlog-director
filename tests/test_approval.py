import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.approval import (
    approve_previewed_timeline,
    approve_timeline,
    verify_approval,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _preview_fixture(root: Path) -> dict[str, Path]:
    project = root / "project"
    proposal = project / "work" / "director" / "v2-proposal"
    candidates = proposal / "candidates"
    candidates.mkdir(parents=True)
    (project / "work" / "plans").mkdir(parents=True)
    (project / "work" / "qa").mkdir(parents=True)
    (project / ".vlog-project.json").write_text(
        json.dumps({"project_id": "demo"}), encoding="utf-8"
    )
    plan = {
        "schema_version": "1.0",
        "project_id": "demo",
        "version": 2,
        "parent_version": 1,
        "brief": {},
        "chapters": [],
    }
    candidate = candidates / "candidate.balanced.json"
    candidate.write_text(json.dumps(plan), encoding="utf-8")
    candidate_sha = _sha(candidate)
    preview_root = proposal / "previews" / candidate_sha
    preview_root.mkdir(parents=True)
    media = preview_root / f"{candidate_sha}.preview.mp4"
    media.write_bytes(b"preview-media")
    media_sha = _sha(media)
    timeline = preview_root / "render.json"
    timeline.write_text(
        json.dumps(
            {
                "contract_version": "render-candidate-preview-v1",
                "status": "review_required",
                "project_id": "demo",
                "version": 2,
                "plan_sha256": candidate_sha,
                "candidate_sha256": candidate_sha,
                "media_quality": "proxy",
                "non_release_marker": {
                    "applied": True,
                    "text": "NON-RELEASE CANDIDATE",
                },
                "output_identity": {"sha256": media_sha, "size_bytes": media.stat().st_size},
            }
        ),
        encoding="utf-8",
    )
    cut_directory = preview_root / "cut-review"
    cut_directory.mkdir()
    cut_qa = cut_directory / "cut-review.json"
    cut_qa.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_version": "directed-cut-qa-v1",
                "status": "review_required",
                "project_id": "demo",
                "plan_version": 2,
                "plan_sha256": candidate_sha,
                "realized_timeline_sha256": _sha(timeline),
                "base_media": {
                    "name": media.name,
                    "sha256": media_sha,
                    "size_bytes": media.stat().st_size,
                },
                "boundary_count": 0,
                "flagged_boundary_count": 0,
                "boundaries": [],
                "created_at": "2026-08-14T00:01:00Z",
                "note": "Human review required.",
            }
        ),
        encoding="utf-8",
    )
    review_pack = proposal / "review-pack.json"
    review_pack.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_version": "directed-candidate-review-pack-v1",
                "status": "review_required",
                "project_id": "demo",
                "plan_version": 2,
                "candidates": [
                    {
                        "label": "balanced",
                        "candidate": {
                            "path": candidate.relative_to(project).as_posix(),
                            "sha256": candidate_sha,
                        },
                        "preview_media": {
                            "path": media.relative_to(project).as_posix(),
                            "sha256": media_sha,
                            "size_bytes": media.stat().st_size,
                        },
                        "realized_timeline": {
                            "path": timeline.relative_to(project).as_posix(),
                            "sha256": _sha(timeline),
                        },
                        "cut_qa": {
                            "path": cut_qa.relative_to(project).as_posix(),
                            "sha256": _sha(cut_qa),
                        },
                        "actual_duration_sec": 1.0,
                        "segment_count": 1,
                        "boundary_count": 0,
                        "flagged_boundary_count": 0,
                        "non_release_marker": {
                            "applied": True,
                            "text": "NON-RELEASE CANDIDATE",
                        },
                    },
                    {
                        "label": "alternate",
                        "candidate": {
                            "path": candidate.relative_to(project).as_posix(),
                            "sha256": "a" * 64,
                        },
                        "preview_media": {
                            "path": media.relative_to(project).as_posix(),
                            "sha256": "b" * 64,
                            "size_bytes": 1,
                        },
                        "realized_timeline": {
                            "path": timeline.relative_to(project).as_posix(),
                            "sha256": "c" * 64,
                        },
                        "cut_qa": {
                            "path": cut_qa.relative_to(project).as_posix(),
                            "sha256": "d" * 64,
                        },
                        "actual_duration_sec": 1.0,
                        "segment_count": 1,
                        "boundary_count": 0,
                        "flagged_boundary_count": 0,
                        "non_release_marker": {
                            "applied": True,
                            "text": "NON-RELEASE CANDIDATE",
                        },
                    },
                ],
                "created_at": "2026-08-14T00:02:00Z",
                "note": "Review required.",
            }
        ),
        encoding="utf-8",
    )
    selection = proposal / "selection.json"
    selection.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "contract_version": "directed-preview-selection-v1",
                "status": "approved",
                "project_id": "demo",
                "plan_version": 2,
                "review_pack_sha256": _sha(review_pack),
                "selected_label": "balanced",
                "selected_candidate_sha256": candidate_sha,
                "preview_media_sha256": media_sha,
                "realized_timeline_sha256": _sha(timeline),
                "cut_qa_sha256": _sha(cut_qa),
                "checks": {
                    "preview_playback": "approved",
                    "visual_continuity": "approved",
                    "speech_completeness": "approved",
                    "audio_continuity": "approved",
                    "story_coherence": "approved",
                },
                "selected_by": "reviewer",
                "selected_at": "2026-08-14T00:03:00Z",
                "attestation": "I watched the selected non-release preview and approve this timeline for source rendering.",
            }
        ),
        encoding="utf-8",
    )
    return {
        "project": project,
        "candidate": candidate,
        "review_pack": review_pack,
        "selection": selection,
        "output": project / "work" / "plans" / "edit_plan.v2.json",
        "receipt": project / "work" / "qa" / "edit_plan.v2.approval.json",
    }


def _rate_preview_fixture(root: Path) -> dict[str, Path]:
    fixture = _preview_fixture(root)
    project = fixture["project"]
    proposal_root = project / "work" / "director" / "v2-proposal"
    candidate = fixture["candidate"]
    base_plan = {
        "schema_version": "1.0",
        "project_id": "demo",
        "version": 2,
        "parent_version": 1,
        "brief": {
            "target_duration_sec": 12.0,
            "aspect_ratio": "16:9",
            "mode": "timeline",
            "keep_dialogue": False,
        },
        "chapters": [
            {
                "id": "ch01",
                "title": "Travel",
                "target_duration_sec": 12.0,
                "segments": [
                    {
                        "source": "raw/A.mp4",
                        "in_sec": 0.0,
                        "out_sec": 12.0,
                        "story_role": "transition",
                        "reason": "continuous movement",
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
    candidate.write_text(
        json.dumps(base_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    candidate_sha = _sha(candidate)

    def write_preview_evidence(plan_path: Path, plan_sha: str, duration: float) -> dict:
        preview_root = proposal_root / "previews" / plan_sha
        preview_root.mkdir(parents=True, exist_ok=True)
        media = preview_root / "candidate.preview.mp4"
        media.write_bytes(b"preview-" + plan_sha.encode("ascii"))
        media_sha = _sha(media)
        timeline = preview_root / "render.json"
        timeline.write_text(
            json.dumps(
                {
                    "contract_version": "render-candidate-preview-v1",
                    "status": "review_required",
                    "project_id": "demo",
                    "version": 2,
                    "plan_sha256": plan_sha,
                    "candidate_sha256": plan_sha,
                    "media_quality": "proxy",
                    "actual_duration_sec": duration,
                    "non_release_marker": {
                        "applied": True,
                        "text": "NON-RELEASE CANDIDATE",
                    },
                    "output_identity": {
                        "sha256": media_sha,
                        "size_bytes": media.stat().st_size,
                    },
                    "av_sync": {
                        "video_duration_sec": duration,
                        "audio_duration_sec": duration,
                        "delta_sec": 0.0,
                        "tolerance_sec": 0.12,
                        "status": "passed",
                    },
                }
            ),
            encoding="utf-8",
        )
        cut_directory = preview_root / "cut-review"
        cut_directory.mkdir()
        cut = cut_directory / "cut-review.json"
        cut.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "contract_version": "directed-cut-qa-v1",
                    "status": "review_required",
                    "project_id": "demo",
                    "plan_version": 2,
                    "plan_sha256": plan_sha,
                    "realized_timeline_sha256": _sha(timeline),
                    "base_media": {
                        "name": media.name,
                        "sha256": media_sha,
                        "size_bytes": media.stat().st_size,
                    },
                    "boundary_count": 0,
                    "flagged_boundary_count": 0,
                    "boundaries": [],
                    "created_at": "2026-08-14T00:01:00Z",
                    "note": "Human review required.",
                }
            ),
            encoding="utf-8",
        )
        return {
            "preview_media": {
                "path": media.relative_to(project).as_posix(),
                "sha256": media_sha,
                "size_bytes": media.stat().st_size,
            },
            "realized_timeline": {
                "path": timeline.relative_to(project).as_posix(),
                "sha256": _sha(timeline),
            },
            "cut_qa": {
                "path": cut.relative_to(project).as_posix(),
                "sha256": _sha(cut),
            },
        }

    base_evidence = write_preview_evidence(candidate, candidate_sha, 12.0)
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
    proposal_sha = hashlib.sha256(
        json.dumps(
            proposal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    derived = json.loads(json.dumps(base_plan))
    original = derived["chapters"][0]["segments"][0]
    derived["chapters"][0]["segments"] = [
        {**original, "out_sec": 2.0},
        {
            **original,
            "in_sec": 2.0,
            "out_sec": 10.0,
            "playback_rate": 1.5,
            "playback_rate_audio_strategy": "atempo",
            "playback_rate_proposal_sha256": proposal_sha,
        },
        {**original, "in_sec": 10.0},
    ]
    derived["chapters"][0]["target_duration_sec"] = 9.333333
    derived["brief"]["target_duration_sec"] = 9.333333
    derived_path = (
        proposal_root
        / "rate-candidates"
        / candidate_sha
        / proposal_sha
        / "candidate.rate-1_5x.json"
    )
    derived_path.parent.mkdir(parents=True)
    derived_path.write_text(
        json.dumps(derived, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    derived_sha = _sha(derived_path)
    rate_evidence = write_preview_evidence(derived_path, derived_sha, 9.333333)
    rate_row = {
        "playback_rate": 1.5,
        "audio_strategy": "atempo",
        "derived_candidate": {
            "path": derived_path.relative_to(project).as_posix(),
            "sha256": derived_sha,
        },
        **rate_evidence,
        "expected_duration_sec": 5.333333,
        "actual_timeline_duration_sec": 9.333333,
        "ffmpeg_identity": {
            "path": "ffmpeg",
            "sha256": "f" * 64,
            "version_line": "ffmpeg synthetic",
        },
        "av_sync": {
            "video_duration_sec": 9.333333,
            "audio_duration_sec": 9.333333,
            "delta_sec": 0.0,
            "tolerance_sec": 0.12,
            "status": "passed",
        },
        "boundary_count": 0,
        "flagged_boundary_count": 0,
        "non_release_marker": {
            "applied": True,
            "text": "NON-RELEASE CANDIDATE",
        },
    }
    director_report = proposal_root / "candidates" / "director_report.json"
    director_report.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_id": "demo",
                "plan_version": 2,
                "technique_application": {
                    "candidate_applications": {
                        "balanced": {"preview_required_patterns": [proposal]}
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    review_pack = json.loads(fixture["review_pack"].read_text(encoding="utf-8"))
    review_pack["contract_version"] = "directed-candidate-review-pack-v2"
    review_pack["director_report"] = {
        "path": director_report.relative_to(project).as_posix(),
        "sha256": _sha(director_report),
        "size_bytes": director_report.stat().st_size,
    }
    selected = review_pack["candidates"][0]
    selected["candidate"] = {
        "path": candidate.relative_to(project).as_posix(),
        "sha256": candidate_sha,
    }
    selected.update(base_evidence)
    selected["actual_duration_sec"] = 12.0
    selected["playback_rate_proposals"] = [
        {
            "proposal_id": proposal["proposal_id"],
            "proposal_sha256": proposal_sha,
            "proposal": proposal,
            "rate_candidates": [rate_row, {**rate_row, "playback_rate": 1.25}],
        }
    ]
    review_pack["candidates"][1]["playback_rate_proposals"] = []
    fixture["review_pack"].write_text(json.dumps(review_pack), encoding="utf-8")
    selection = json.loads(fixture["selection"].read_text(encoding="utf-8"))
    selection.update(
        {
            "contract_version": "directed-preview-selection-v2",
            "review_pack_sha256": _sha(fixture["review_pack"]),
            "selected_candidate_sha256": candidate_sha,
            "preview_media_sha256": base_evidence["preview_media"]["sha256"],
            "realized_timeline_sha256": base_evidence["realized_timeline"]["sha256"],
            "cut_qa_sha256": base_evidence["cut_qa"]["sha256"],
            "playback_rate_decisions": [
                {
                    "proposal_sha256": proposal_sha,
                    "decision": "selected",
                    "selected_rate": 1.5,
                    "derived_candidate_sha256": derived_sha,
                    "preview_media_sha256": rate_evidence["preview_media"]["sha256"],
                    "realized_timeline_sha256": rate_evidence["realized_timeline"]["sha256"],
                    "cut_qa_sha256": rate_evidence["cut_qa"]["sha256"],
                }
            ],
        }
    )
    fixture["selection"].write_text(json.dumps(selection), encoding="utf-8")
    fixture["rate_preview"] = project / rate_evidence["preview_media"]["path"]
    return fixture


class ApprovalTests(unittest.TestCase):
    def test_approval_hash_blocks_modified_plan(self) -> None:
        plan = {
            "schema_version": "1.0",
            "project_id": "demo",
            "version": 2,
            "parent_version": 1,
            "brief": {},
            "chapters": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate.json"
            output = root / "edit_plan.v2.json"
            receipt_path = root / "edit_plan.v2.approval.json"
            candidate.write_text(json.dumps(plan), encoding="utf-8")
            receipt = approve_timeline(
                candidate, output, receipt_path, approved_by="reviewer"
            )
            self.assertEqual(verify_approval(plan, receipt)["status"], "passed")
            modified = {**plan, "chapters": [{"id": "changed"}]}
            self.assertEqual(verify_approval(modified, receipt)["status"], "blocked")

    def test_previewed_approval_binds_human_selection_and_remains_pipeline_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _preview_fixture(Path(directory))
            receipt = approve_previewed_timeline(
                project=fixture["project"],
                candidate_path=fixture["candidate"],
                review_pack_path=fixture["review_pack"],
                selection_path=fixture["selection"],
                output_path=fixture["output"],
                receipt_path=fixture["receipt"],
                approved_by="release-operator",
            )
            approved_plan = json.loads(fixture["output"].read_text(encoding="utf-8"))
            self.assertEqual(receipt["approval_contract_version"], "previewed-timeline-approval-v1")
            self.assertEqual(receipt["human_selection"]["selected_by"], "reviewer")
            self.assertEqual(verify_approval(approved_plan, receipt)["status"], "passed")

    def test_previewed_approval_rejects_candidate_changed_after_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _preview_fixture(Path(directory))
            candidate = json.loads(fixture["candidate"].read_text(encoding="utf-8"))
            candidate["chapters"] = [{"id": "changed"}]
            fixture["candidate"].write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match candidate input"):
                approve_previewed_timeline(
                    project=fixture["project"],
                    candidate_path=fixture["candidate"],
                    review_pack_path=fixture["review_pack"],
                    selection_path=fixture["selection"],
                    output_path=fixture["output"],
                    receipt_path=fixture["receipt"],
                    approved_by="release-operator",
                )

    def test_v2_approval_outputs_only_the_selected_rate_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _rate_preview_fixture(Path(directory))
            receipt = approve_previewed_timeline(
                project=fixture["project"],
                candidate_path=fixture["candidate"],
                review_pack_path=fixture["review_pack"],
                selection_path=fixture["selection"],
                output_path=fixture["output"],
                receipt_path=fixture["receipt"],
                approved_by="release-operator",
            )

            approved = json.loads(fixture["output"].read_text(encoding="utf-8"))
            rate_segments = [
                segment
                for chapter in approved["chapters"]
                for segment in chapter["segments"]
                if "playback_rate" in segment
            ]
            self.assertEqual(len(rate_segments), 1)
            self.assertEqual(rate_segments[0]["playback_rate"], 1.5)
            self.assertEqual(
                receipt["approval_contract_version"],
                "previewed-timeline-approval-v2",
            )
            self.assertEqual(
                receipt["playback_rate_decision"]["decision"], "selected"
            )
            self.assertEqual(verify_approval(approved, receipt)["status"], "passed")

    def test_v2_approval_can_reject_all_rate_candidates_without_changing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _rate_preview_fixture(Path(directory))
            selection = json.loads(
                fixture["selection"].read_text(encoding="utf-8")
            )
            proposal_sha = selection["playback_rate_decisions"][0][
                "proposal_sha256"
            ]
            selection["playback_rate_decisions"] = [
                {
                    "proposal_sha256": proposal_sha,
                    "decision": "rejected",
                }
            ]
            fixture["selection"].write_text(
                json.dumps(selection), encoding="utf-8"
            )

            receipt = approve_previewed_timeline(
                project=fixture["project"],
                candidate_path=fixture["candidate"],
                review_pack_path=fixture["review_pack"],
                selection_path=fixture["selection"],
                output_path=fixture["output"],
                receipt_path=fixture["receipt"],
                approved_by="release-operator",
            )

            base_candidate = json.loads(
                fixture["candidate"].read_text(encoding="utf-8")
            )
            approved = json.loads(fixture["output"].read_text(encoding="utf-8"))
            self.assertEqual(approved, base_candidate)
            self.assertFalse(
                any(
                    "playback_rate" in segment
                    for chapter in approved["chapters"]
                    for segment in chapter["segments"]
                )
            )
            self.assertEqual(
                receipt["playback_rate_decision"],
                {
                    "decision": "rejected_all",
                    "proposal_sha256s": [proposal_sha],
                },
            )
            self.assertEqual(verify_approval(approved, receipt)["status"], "passed")

    def test_v2_approval_invalidates_changed_rate_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _rate_preview_fixture(Path(directory))
            fixture["rate_preview"].write_bytes(b"changed-preview")
            with self.assertRaisesRegex(ValueError, "changed after review"):
                approve_previewed_timeline(
                    project=fixture["project"],
                    candidate_path=fixture["candidate"],
                    review_pack_path=fixture["review_pack"],
                    selection_path=fixture["selection"],
                    output_path=fixture["output"],
                    receipt_path=fixture["receipt"],
                    approved_by="release-operator",
                )


if __name__ == "__main__":
    unittest.main()
