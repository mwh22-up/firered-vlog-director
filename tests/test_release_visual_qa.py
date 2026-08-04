import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.release_visual_qa import (
    TEXT_ACCURACY_STATEMENT,
    qa_release_visual,
)


class ReleaseVisualQATests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        project = root / "project"
        (project / "work" / "enhancement").mkdir(parents=True)
        (project / "work" / "qa").mkdir(parents=True)
        (project / ".vlog-project.json").write_text(
            json.dumps({"project_id": "visual-demo"}), encoding="utf-8"
        )
        plan = project / "work" / "enhancement" / "enhancement_plan.v1.json"
        plan.write_text("{}", encoding="utf-8")
        media = project / "final.mp4"
        media.write_bytes(b"media")
        output = project / "work" / "qa" / "release-visual" / "qa-001"
        return project, plan, media, output

    def test_visual_evidence_never_claims_ocr_or_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, plan, media, output = self._fixture(Path(directory))

            def create_frame(command: list[str]) -> None:
                Path(command[-1]).write_bytes(b"png")

            diagnostics = (
                "[blackdetect] black_start:1.0\n"
                "[blackdetect] black_end:2.2 black_duration:1.2\n"
                "[freezedetect] freeze_start: 3.0\n"
                "[freezedetect] freeze_end: 4.7 | freeze_duration: 1.7\n"
            )
            with (
                patch("vlog_director.release_visual_qa.find_ffmpeg", return_value="ffmpeg"),
                patch(
                    "vlog_director.release_visual_qa.probe_media",
                    return_value={"duration_sec": 6.0, "width": 1920, "height": 1080},
                ),
                patch(
                    "vlog_director.release_visual_qa.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "", diagnostics),
                ),
                patch("vlog_director.release_visual_qa.run_command", side_effect=create_frame),
                patch(
                    "vlog_director.release_visual_qa.inspect_ffmpeg_identity",
                    return_value={"executable_sha256": "f" * 64, "version_line": "ffmpeg test"},
                ),
            ):
                result = qa_release_visual(
                    project=project,
                    media_path=media,
                    enhancement_plan_path=plan,
                    output_directory=output,
                )

            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocking_count"], 1)
            self.assertEqual(result["ocr"]["text_accuracy_verified"], False)
            self.assertEqual(result["human_review"]["status"], "pending")
            self.assertEqual(result["text_accuracy_statement"], TEXT_ACCURACY_STATEMENT)
            self.assertEqual(len(result["frames"]), 3)
            self.assertTrue((output / "visual-qa.json").is_file())

    def test_cleanup_output_cannot_equal_release_visual_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project, plan, media, _ = self._fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "unique child"):
                qa_release_visual(
                    project=project,
                    media_path=media,
                    enhancement_plan_path=plan,
                    output_directory=project / "work" / "qa" / "release-visual",
                )


if __name__ == "__main__":
    unittest.main()
