from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.effect_plan import build_effect_plan, canonical_effect_payload_sha256
from vlog_director.effect_visual_qa import qa_hyperframes_effects


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class EffectVisualQATests(unittest.TestCase):
    def _fixture(self, root: Path):
        project = root / "project"
        edit = {
            "schema_version": "1.0",
            "project_id": "qa-demo",
            "version": 1,
            "chapters": [
                {
                    "id": "ch01",
                    "title": "爆点",
                    "segments": [
                        {
                            "source": "raw/a.mp4",
                            "in_sec": 0,
                            "out_sec": 2,
                            "story_role": "reaction",
                        }
                    ],
                }
            ],
        }
        edit_path = project / "work" / "plans" / "edit_plan.v1.json"
        _write(edit_path, edit)
        effect = build_effect_plan(edit, edit_plan_sha256=_canonical(edit))
        effect_duration = round(
            effect["effects"][0]["placement"]["end_sec"]
            - effect["effects"][0]["placement"]["start_sec"],
            4,
        )
        effect_path = project / "work" / "effects" / "effect_plan.v1.json"
        _write(effect_path, effect)
        effect_id = effect["effects"][0]["effect_id"]
        job = project / "work" / "effects" / "job-1"
        composition = job / effect_id / "index.html"
        composition.parent.mkdir(parents=True)
        composition.write_text("<html></html>", encoding="utf-8")
        composition_manifest = job / "composition-manifest.json"
        _write(composition_manifest, {"status": "composed"})
        output = job / effect_id / "overlay.mov"
        output.write_bytes(b"mov")
        render = {
            "schema_version": "1.0",
            "contract_version": "hyperframes-render-manifest-v1",
            "status": "rendered",
            "project_id": edit["project_id"],
            "edit_plan_version": 1,
            "edit_plan_sha256": effect["edit_plan_sha256"],
            "effect_plan": "work/effects/effect_plan.v1.json",
            "effect_plan_sha256": _sha(effect_path),
            "effect_payload_sha256": canonical_effect_payload_sha256(effect),
            "composition_manifest": composition_manifest.relative_to(project).as_posix(),
            "composition_manifest_sha256": _sha(composition_manifest),
            "hyperframes": {
                "executable": "hyperframes",
                "package": "hyperframes",
                "version": "0.7.90",
                "npm_integrity": effect["capability_registry"]["npm_integrity"],
            },
            "effects": [
                {
                    "effect_id": effect_id,
                    "intent": effect["effects"][0]["intent"],
                    "duration_sec": effect_duration,
                    "composition": composition.relative_to(project).as_posix(),
                    "composition_sha256": _sha(composition),
                    "output": output.relative_to(project).as_posix(),
                    "output_size_bytes": output.stat().st_size,
                    "output_sha256": _sha(output),
                }
            ],
        }
        render_path = job / "render-manifest.json"
        _write(render_path, render)
        base = project / "output" / "directed.v1.mp4"
        base.parent.mkdir(parents=True)
        base.write_bytes(b"base")
        return project, effect_path, render_path, base, effect_id

    def test_generates_three_frame_human_pending_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, render_path, base, effect_id = self._fixture(Path(temporary))
            output = project / "work" / "qa" / "effects" / "qa-1"
            expected_duration = json.loads(render_path.read_text(encoding="utf-8"))["effects"][0][
                "duration_sec"
            ]
            commands: list[list[str]] = []

            def fake_run(command: list[str]) -> None:
                commands.append(command)
                Path(command[-1]).write_bytes(("generated:" + Path(command[-1]).name).encode("utf-8"))

            with (
                patch("vlog_director.effect_visual_qa.find_ffmpeg", return_value="ffmpeg"),
                patch(
                    "vlog_director.effect_visual_qa.probe_media",
                    return_value={
                        "duration_sec": 2.0,
                        "width": 1920,
                        "height": 1080,
                        "has_video": True,
                        "has_audio": True,
                    },
                ),
                patch(
                    "vlog_director.effect_visual_qa._probe_effect_video",
                    return_value={
                        "duration_sec": expected_duration,
                        "width": 1920,
                        "height": 1080,
                        "has_alpha": True,
                    },
                ),
                patch("vlog_director.effect_visual_qa.run_command", side_effect=fake_run),
            ):
                report = qa_hyperframes_effects(
                    project,
                    effect_path,
                    render_path,
                    base,
                    output,
                    executable="ffmpeg",
                )

            self.assertEqual(report["status"], "evidence_ready")
            self.assertEqual(report["human_review"]["status"], "pending")
            self.assertEqual(
                report["conclusion"],
                "已生成视觉帧和布局证据，效果适配性仍需人工检查。",
            )
            self.assertEqual([row["role"] for row in report["effects"][0]["frames"]], ["entry", "peak", "exit"])
            self.assertEqual(report["effects"][0]["effect_id"], effect_id)
            exit_command = next(command for command in commands if str(command[-1]).endswith(".exit.png"))
            self.assertLessEqual(
                float(exit_command[exit_command.index("-ss") + 1]),
                expected_duration - 0.08 + 0.000001,
            )
            self.assertTrue((output / "visual-qa.json").is_file())
            with self.assertRaises(FileExistsError):
                qa_hyperframes_effects(project, effect_path, render_path, base, output)

    def test_rejects_changed_rendered_effect_before_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, render_path, base, _ = self._fixture(Path(temporary))
            render = json.loads(render_path.read_text(encoding="utf-8"))
            (project / render["effects"][0]["output"]).write_bytes(b"changed")
            with patch("vlog_director.effect_visual_qa.run_command") as run:
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    qa_hyperframes_effects(
                        project,
                        effect_path,
                        render_path,
                        base,
                        project / "work" / "qa" / "effects" / "qa-1",
                    )
            run.assert_not_called()

    def test_rejects_effect_video_without_alpha_before_compositing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project, effect_path, render_path, base, _ = self._fixture(Path(temporary))
            with (
                patch("vlog_director.effect_visual_qa.find_ffmpeg", return_value="ffmpeg"),
                patch(
                    "vlog_director.effect_visual_qa.probe_media",
                    return_value={
                        "duration_sec": 2.0,
                        "width": 1920,
                        "height": 1080,
                        "has_video": True,
                        "has_audio": True,
                    },
                ),
                patch(
                    "vlog_director.effect_visual_qa._probe_effect_video",
                    return_value={
                        "duration_sec": 1.2,
                        "width": 1920,
                        "height": 1080,
                        "has_alpha": False,
                    },
                ),
                patch("vlog_director.effect_visual_qa.run_command") as run,
            ):
                with self.assertRaisesRegex(ValueError, "alpha"):
                    qa_hyperframes_effects(
                        project,
                        effect_path,
                        render_path,
                        base,
                        project / "work" / "qa" / "effects" / "qa-1",
                        executable="ffmpeg",
                    )
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
