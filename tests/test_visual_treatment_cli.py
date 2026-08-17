from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class VisualTreatmentCliTests(unittest.TestCase):
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

    def test_visual_treatment_commands_have_help(self) -> None:
        for command in (
            "analyze-visual-segments",
            "plan-visual-treatments",
            "render-treatment-preview",
            "qa-visual-treatments",
            "approve-visual-treatments",
            "apply-visual-treatments",
        ):
            with self.subTest(command=command):
                result = self._run(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("--project", result.stdout)
                if command in {
                    "analyze-visual-segments",
                    "render-treatment-preview",
                    "qa-visual-treatments",
                }:
                    self.assertIn("--detached", result.stdout)


if __name__ == "__main__":
    unittest.main()
