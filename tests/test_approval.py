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


if __name__ == "__main__":
    unittest.main()
