import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.approval import approve_timeline, verify_approval


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


if __name__ == "__main__":
    unittest.main()
