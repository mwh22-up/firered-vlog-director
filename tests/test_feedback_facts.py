import json
import tempfile
import unittest
from pathlib import Path

from vlog_director.feedback_facts import derive_feedback_facts


class FeedbackFactTests(unittest.TestCase):
    def test_derives_restore_remove_extend_and_reorder_without_learning_weights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            plans = project / "work" / "plans"
            plans.mkdir(parents=True)

            def plan(version: int, segments: list[dict]) -> dict:
                return {"project_id": "demo", "version": version, "chapters": [{"id": "ch", "segments": segments}]}

            baseline = plans / "baseline.json"
            candidate = plans / "candidate.json"
            final = plans / "final.json"
            baseline.write_text(json.dumps(plan(1, [{"source": "a.mp4", "in_sec": 0, "out_sec": 2}, {"source": "b.mp4", "in_sec": 0, "out_sec": 1}, {"source": "c.mp4", "in_sec": 0, "out_sec": 1}])), encoding="utf-8")
            candidate.write_text(json.dumps(plan(2, [{"source": "a.mp4", "in_sec": 0, "out_sec": 1}, {"source": "b.mp4", "in_sec": 0, "out_sec": 1}])), encoding="utf-8")
            final.write_text(json.dumps(plan(3, [{"source": "c.mp4", "in_sec": 0, "out_sec": 1}, {"source": "a.mp4", "in_sec": 0, "out_sec": 2}])), encoding="utf-8")
            result = derive_feedback_facts(project=project, candidate_path=candidate, final_path=final, baseline_path=baseline, output_path=project / "work" / "qa" / "feedback.json")

            kinds = {operation["type"] for operation in result["operations"]}
            self.assertTrue({"restore", "remove", "extend", "reorder"}.issubset(kinds))
            self.assertEqual(result["status"], "review_required")
            self.assertFalse(result["learning_policy"]["automatic_weight_update"])
            self.assertTrue(all(operation["review_status"] == "pending" for operation in result["operations"]))


if __name__ == "__main__":
    unittest.main()
