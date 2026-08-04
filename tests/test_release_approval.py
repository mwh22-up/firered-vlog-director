import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.release_approval import approve_release


class ReleaseApprovalTests(unittest.TestCase):
    def test_release_approval_requires_zero_blockers_and_sha_bound_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            for relative in (
                "output",
                "work/enhancement",
                "work/qa/release-visual/qa-1",
                "work/qa/release-approval",
            ):
                (project / relative).mkdir(parents=True, exist_ok=True)
            (project / ".vlog-project.json").write_text(
                json.dumps({"project_id": "demo"}), encoding="utf-8"
            )
            media = project / "output" / "final.mp4"
            media.write_bytes(b"media")
            plan = project / "work" / "enhancement" / "enhancement_plan.v2.json"
            plan.write_text(
                json.dumps({"edit_plan_version": 2}), encoding="utf-8"
            )
            base = project / "work" / "qa" / "directed-base.v2.json"
            base.write_text(
                json.dumps(
                    {
                        "status": "ready",
                        "project_id": "demo",
                        "edit_plan": {"path": "work/plans/edit_plan.v2.json"},
                    }
                ),
                encoding="utf-8",
            )
            visual = (
                project
                / "work"
                / "qa"
                / "release-visual"
                / "qa-1"
                / "visual-qa.json"
            )

            def sha(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest()

            visual.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "blocking_count": 0,
                        "bindings": {
                            "media": {"sha256": sha(media)},
                            "enhancement_plan": {"sha256": sha(plan)},
                            "directed_base_contract": {"sha256": sha(base)},
                        },
                    }
                ),
                encoding="utf-8",
            )
            review = visual.parent / "human-review.json"
            review.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "contract_version": "release-human-review-v1",
                        "status": "approved",
                        "project_id": "demo",
                        "bindings": {
                            "media_sha256": sha(media),
                            "enhancement_plan_sha256": sha(plan),
                            "visual_qa_sha256": sha(visual),
                        },
                        "decisions": {
                            "black_and_freeze": "approved",
                            "framing_and_crop": "approved",
                            "subtitle_and_effect_collisions": "approved",
                            "text_accuracy_listened": "approved",
                            "overall_visual": "approved",
                        },
                        "reviewed_by": "human",
                        "reviewed_at": "2026-08-04T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            result = approve_release(
                project=project,
                media_path=media,
                enhancement_plan_path=plan,
                directed_base_contract_path=base,
                visual_qa_path=visual,
                human_review_path=review,
                output_path=(
                    project / "work" / "qa" / "release-approval" / "approval.json"
                ),
            )
            self.assertEqual(result["status"], "approved")
            media.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "media SHA-256"):
                approve_release(
                    project=project,
                    media_path=media,
                    enhancement_plan_path=plan,
                    directed_base_contract_path=base,
                    visual_qa_path=visual,
                    human_review_path=review,
                    output_path=(
                        project
                        / "work"
                        / "qa"
                        / "release-approval"
                        / "approval-2.json"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
