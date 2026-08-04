from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _edit_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "effect-cli-demo",
        "version": 2,
        "chapters": [
            {
                "id": "ch01",
                "title": "冲进暴风雪",
                "segments": [
                    {
                        "source": "raw/a.mp4",
                        "in_sec": 0,
                        "out_sec": 2,
                        "story_role": "opening_preview",
                    }
                ],
            }
        ],
    }


class EffectCliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-m", "vlog_director.cli", *arguments],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_plan_and_compose_effects_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            (project / "work" / "plans").mkdir(parents=True)
            (project / "work" / "effects").mkdir(parents=True)
            (project / "work" / "plans" / "edit_plan.v2.json").write_text(
                json.dumps(_edit_plan(), ensure_ascii=False), encoding="utf-8"
            )
            plan_path = project / "work" / "effects" / "effect_plan.v2.json"

            planned = self._run(
                "plan-effects",
                "--project",
                str(project),
                "--version",
                "2",
            )
            self.assertEqual(planned.returncode, 0, planned.stderr + planned.stdout)
            self.assertTrue(plan_path.is_file())
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["effects"][0]["intent"], "impact_hit")
            self.assertEqual(plan["effects"][0]["status"], "review_required")

            composed = self._run(
                "compose-effects",
                "--project",
                str(project),
                "--plan",
                str(plan_path),
                "--output-directory",
                str(project / "work" / "effects" / "job-001"),
            )
            self.assertEqual(composed.returncode, 0, composed.stderr + composed.stdout)
            manifest = project / "work" / "effects" / "job-001" / "composition-manifest.json"
            self.assertTrue(manifest.is_file())

    def test_plan_effects_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            (project / "work" / "plans").mkdir(parents=True)
            (project / "work" / "effects").mkdir(parents=True)
            (project / "work" / "plans" / "edit_plan.v2.json").write_text(
                json.dumps(_edit_plan()), encoding="utf-8"
            )
            first = self._run("plan-effects", "--project", str(project), "--version", "2")
            second = self._run("plan-effects", "--project", str(project), "--version", "2")
            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 2)
            self.assertIn("already exists", second.stdout)

    def test_effect_qa_approval_and_apply_commands_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            for command, arguments, code in (
                (
                    "qa-effects",
                    [
                        "--plan", "missing-plan.json",
                        "--render-manifest", "missing-render.json",
                        "--base-video", "missing.mp4",
                        "--output-directory", "missing-qa",
                    ],
                    "effect_visual_qa_failed",
                ),
                (
                    "approve-effects",
                    [
                        "--plan", "missing-plan.json",
                        "--render-manifest", "missing-render.json",
                        "--visual-qa", "missing-visual.json",
                        "--human-review", "missing-human.json",
                        "--output", "missing-approval.json",
                    ],
                    "effect_approval_failed",
                ),
                (
                    "apply-effects",
                    [
                        "--enhancement-plan", "missing-enhancement.json",
                        "--plan", "missing-plan.json",
                        "--render-manifest", "missing-render.json",
                        "--visual-qa", "missing-visual.json",
                        "--human-review", "missing-human.json",
                        "--approval", "missing-approval.json",
                        "--output", "missing-output.json",
                    ],
                    "effect_apply_failed",
                ),
            ):
                completed = self._run(command, "--project", str(project), *arguments)
                self.assertEqual(completed.returncode, 2)
                self.assertIn(code, completed.stdout)


if __name__ == "__main__":
    unittest.main()
