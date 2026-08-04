from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.effect_plan import build_effect_plan
from vlog_director.hyperframes_effects import (
    _run,
    build_hyperframes_compositions,
    render_hyperframes_compositions,
)


def _canonical_digest(document: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _edit_plan() -> dict:
    return {
        "schema_version": "1.0",
        "project_id": "hf-demo",
        "version": 1,
        "chapters": [
            {
                "id": "ch01",
                "title": "大胆出发",
                "segments": [
                    {
                        "source": "raw/a.mp4",
                        "in_sec": 0.0,
                        "out_sec": 3.0,
                        "story_role": "reaction",
                        "confidence": 0.95,
                    }
                ],
            }
        ],
    }


class HyperFramesEffectTests(unittest.TestCase):
    def test_windows_command_shim_is_resolved_after_start_failure(self) -> None:
        completed = subprocess.CompletedProcess(["npx.cmd", "--version"], 0, "0.7.90\n", "")
        with (
            patch(
                "vlog_director.hyperframes_effects.subprocess.run",
                side_effect=[OSError("cannot execute extensionless shim"), completed],
            ) as run,
            patch(
                "vlog_director.hyperframes_effects.shutil.which",
                return_value=r"C:\Program Files\nodejs\npx.cmd",
            ),
        ):
            result = _run(["npx", "--version"], cwd=Path.cwd())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            run.call_args_list[1].args[0][0],
            r"C:\Program Files\nodejs\npx.cmd",
        )

    def _project(self, root: Path) -> tuple[Path, Path, dict]:
        project = root / "project"
        (project / "work" / "plans").mkdir(parents=True)
        (project / "work" / "effects").mkdir(parents=True)
        edit_plan = _edit_plan()
        edit_path = project / "work" / "plans" / "edit_plan.v1.json"
        edit_path.write_text(json.dumps(edit_plan), encoding="utf-8")
        effect_plan = build_effect_plan(
            edit_plan,
            edit_plan_sha256=_canonical_digest(edit_plan),
        )
        effect_path = project / "work" / "effects" / "effect_plan.v1.json"
        effect_path.write_text(json.dumps(effect_plan), encoding="utf-8")
        return project, effect_path, effect_plan

    def test_builds_seekable_network_free_bold_compositions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, effect_plan = self._project(Path(temporary))
            output = project / "work" / "effects" / "job-001"

            result = build_hyperframes_compositions(project, effect_path, output)

            self.assertEqual(result["status"], "composed")
            self.assertEqual(len(result["effects"]), len(effect_plan["effects"]))
            for row in result["effects"]:
                html = (project / row["composition"]).read_text(encoding="utf-8")
                self.assertIn('data-composition-id="', html)
                self.assertIn("data-no-timeline", html)
                self.assertIn('data-start="0"', html)
                self.assertIn("element.animate", html)
                self.assertIn("animation.pause()", html)
                self.assertIn("@font-face", html)
                self.assertIn('local("Microsoft YaHei")', html)
                self.assertIn("data-layout-allow-overflow", html)
                self.assertNotIn("https://", html)
                self.assertNotIn("Math.random", html)
                self.assertNotIn("setTimeout", html)
                self.assertNotIn("requestAnimationFrame", html)
                self.assertIn("#ff3d00", html.lower())
                self.assertEqual(
                    row["composition_sha256"],
                    hashlib.sha256((project / row["composition"]).read_bytes()).hexdigest(),
                )

    def test_composition_job_must_be_new_strict_child_of_work_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, _ = self._project(Path(temporary))
            allowed = project / "work" / "effects" / "job-001"
            build_hyperframes_compositions(project, effect_path, allowed)
            with self.assertRaises(FileExistsError):
                build_hyperframes_compositions(project, effect_path, allowed)
            with self.assertRaises(ValueError):
                build_hyperframes_compositions(
                    project,
                    effect_path,
                    project / "work" / "effects",
                )
            with self.assertRaises(ValueError):
                build_hyperframes_compositions(
                    project,
                    effect_path,
                    project / "outside",
                )

    def test_render_pins_cli_checks_strictly_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, _ = self._project(Path(temporary))
            job = project / "work" / "effects" / "job-001"
            composition = build_hyperframes_compositions(project, effect_path, job)
            composition_manifest = job / "composition-manifest.json"
            commands: list[list[str]] = []

            def fake_run(command, **kwargs):
                command = [str(value) for value in command]
                commands.append(command)
                if command[-1] == "--version":
                    return subprocess.CompletedProcess(command, 0, "0.7.90\n", "")
                if "render" in command:
                    output = Path(command[command.index("--output") + 1])
                    output.write_bytes(b"fake-transparent-mov")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("vlog_director.hyperframes_effects.subprocess.run", side_effect=fake_run):
                result = render_hyperframes_compositions(
                    project,
                    effect_path,
                    composition_manifest,
                    executable="npx",
                    quality="draft",
                )

            self.assertEqual(result["status"], "rendered")
            self.assertEqual(result["hyperframes"]["version"], "0.7.90")
            self.assertTrue(
                all(command[:3] == ["npx", "--yes", "hyperframes@0.7.90"] for command in commands)
            )
            self.assertTrue(any("check" in command and "--strict" in command for command in commands))
            self.assertTrue(
                all("--no-best-effort" in command for command in commands if "render" in command)
            )
            self.assertTrue(all(row["output_sha256"] for row in result["effects"]))
            with patch("vlog_director.hyperframes_effects.subprocess.run", side_effect=fake_run):
                with self.assertRaises(FileExistsError):
                    render_hyperframes_compositions(
                        project,
                        effect_path,
                        composition_manifest,
                        executable="hyperframes",
                    )

    def test_render_rejects_unpinned_hyperframes_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, _ = self._project(Path(temporary))
            job = project / "work" / "effects" / "job-001"
            build_hyperframes_compositions(project, effect_path, job)

            with patch(
                "vlog_director.hyperframes_effects.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "0.8.0\n", ""),
            ):
                with self.assertRaisesRegex(RuntimeError, "0.7.90"):
                    render_hyperframes_compositions(
                        project,
                        effect_path,
                        job / "composition-manifest.json",
                        executable="hyperframes",
                    )


if __name__ == "__main__":
    unittest.main()
