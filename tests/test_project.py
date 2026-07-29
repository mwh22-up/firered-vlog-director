import json
import shutil
import tempfile
import unittest
from pathlib import Path

from vlog_director.project import (
    guard_project_enhancement,
    guard_project_render,
    init_project,
    init_project_enhancement,
)

FIXTURES = Path(__file__).parent / "fixtures"


class ProjectTests(unittest.TestCase):
    def test_init_project_creates_portable_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = init_project(root, "family-trip")
            project = root / "family-trip"

            self.assertEqual(result["status"], "ready")
            self.assertTrue((project / ".vlog-project.json").is_file())
            self.assertTrue((project / "brief.yaml").is_file())
            self.assertTrue((project / "work" / "analysis").is_dir())
            self.assertTrue((project / "work" / "plans").is_dir())
            self.assertTrue((project / "work" / "qa").is_dir())

    def test_init_project_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                init_project(Path(temporary_directory), "../private")

    def test_guard_project_render_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "projects" / "fixture-vlog"
            init_project(project.parent, project.name)
            shutil.copyfile(
                FIXTURES / "moments.json",
                project / "work" / "analysis" / "moments.json",
            )
            shutil.copyfile(
                FIXTURES / "edit_plan.valid.json",
                project / "work" / "plans" / "edit_plan.v1.json",
            )

            result = guard_project_render(project, 1)
            report = project / "work" / "qa" / "protection.v1.json"

            self.assertEqual(result["status"], "passed")
            self.assertTrue(report.is_file())
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "passed")

    def test_init_and_guard_enhancement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "projects" / "fixture-vlog"
            init_project(project.parent, project.name)
            shutil.copyfile(
                FIXTURES / "edit_plan.valid.json",
                project / "work" / "plans" / "edit_plan.v1.json",
            )

            created = init_project_enhancement(project, 1)
            result = guard_project_enhancement(project, 1)

            self.assertTrue(Path(created["enhancement_plan_path"]).is_file())
            self.assertEqual(result["status"], "passed")
            self.assertTrue(Path(result["report_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
