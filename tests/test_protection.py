import json
import unittest
from pathlib import Path

from vlog_director.protection import validate_protection

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class ProtectionTests(unittest.TestCase):
    def test_valid_plan_passes(self) -> None:
        result = validate_protection(
            load_fixture("moments.json"),
            load_fixture("edit_plan.valid.json"),
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["blocking_count"], 0)

    def test_missing_locked_and_group_context_blocks(self) -> None:
        result = validate_protection(
            load_fixture("moments.json"),
            load_fixture("edit_plan.invalid.json"),
        )

        self.assertEqual(result["status"], "blocked")
        issue_codes = {issue["code"] for issue in result["issues"]}
        self.assertIn("locked_moment_missing", issue_codes)
        self.assertIn("protected_moment_missing", issue_codes)
        self.assertIn("moment_group_incomplete", issue_codes)


if __name__ == "__main__":
    unittest.main()
