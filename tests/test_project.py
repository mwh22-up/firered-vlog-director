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
            self.assertTrue((project / "work" / "jobs").is_dir())

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
            persisted = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "passed")
            self.assertEqual(persisted["project_path"], "${PROJECT_ROOT}")
            self.assertEqual(
                persisted["report_path"],
                "${PROJECT_ROOT}/work/qa/protection.v1.json",
            )

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
            self.assertEqual(result["status"], "preview_ready")
            self.assertTrue(Path(result["report_path"]).is_file())

    def test_guard_resolves_edit_plan_version_from_enhancement_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "projects" / "fixture-vlog"
            init_project(project.parent, project.name)
            shutil.copyfile(
                FIXTURES / "edit_plan.valid.json",
                project / "work" / "plans" / "edit_plan.v1.json",
            )
            created = init_project_enhancement(project, 1)
            enhancement_path = Path(created["enhancement_plan_path"])
            enhancement = json.loads(enhancement_path.read_text(encoding="utf-8"))
            enhancement["version"] = 2
            v2_path = project / "work" / "enhancement" / "enhancement_plan.v2.json"
            v2_path.write_text(
                json.dumps(enhancement, indent=2) + "\n",
                encoding="utf-8",
            )

            result = guard_project_enhancement(project, 2)

            self.assertEqual(result["status"], "preview_ready")
            self.assertTrue(
                Path(result["edit_plan_path"]).samefile(
                    project / "work" / "plans" / "edit_plan.v1.json"
                )
            )
            self.assertTrue(Path(result["enhancement_plan_path"]).samefile(v2_path))

    def test_guard_uses_realized_timeline_for_active_treatments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "projects" / "fixture-vlog"
            init_project(project.parent, project.name)
            shutil.copyfile(
                FIXTURES / "edit_plan.valid.json",
                project / "work" / "plans" / "edit_plan.v1.json",
            )
            created = init_project_enhancement(project, 1)
            enhancement_path = Path(created["enhancement_plan_path"])
            enhancement = json.loads(enhancement_path.read_text(encoding="utf-8"))
            enhancement["video_treatments"][0]["visual"]["brightness"] = 0.05
            enhancement_path.write_text(
                json.dumps(enhancement, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            realized_path = project / "work" / "qa" / "realized.v1.json"
            realized_path.write_text(
                json.dumps(
                    {
                        "project_id": "fixture-vlog",
                        "version": 1,
                        "actual_duration_sec": 22.1,
                        "segments": [
                            {
                                "segment_id": "ch01-s001",
                                "start_sec": 0.0,
                                "end_sec": 10.05,
                            },
                            {
                                "segment_id": "ch01-s002",
                                "start_sec": 10.05,
                                "end_sec": 22.1,
                            },
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            result = guard_project_enhancement(project, 1, realized_path)

            self.assertEqual(result["status"], "blocked")
            self.assertIn(
                "realized_timeline_base_identity_required",
                {issue["code"] for issue in result["issues"]},
            )
            self.assertEqual(result["realized_timeline_path"], str(realized_path))

            realized = json.loads(realized_path.read_text(encoding="utf-8"))
            realized["output_identity"] = {
                "size_bytes": 123,
                "sha256": "3" * 64,
            }
            realized_path.write_text(
                json.dumps(realized, indent=2) + "\n",
                encoding="utf-8",
            )
            result = guard_project_enhancement(project, 1, realized_path)
            self.assertEqual(result["status"], "preview_ready")
            persisted = json.loads(
                (project / "work" / "qa" / "enhancement.v1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(persisted["project_path"], "${PROJECT_ROOT}")
            self.assertEqual(
                persisted["realized_timeline_path"],
                "${PROJECT_ROOT}/work/qa/realized.v1.json",
            )
            self.assertEqual(len(persisted["enhancement_plan_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
