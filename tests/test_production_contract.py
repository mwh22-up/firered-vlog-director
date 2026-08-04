import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vlog_director.approval import plan_sha256
from vlog_director.production_contract import bind_directed_base


class ProductionContractTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path]:
        project = root / "project"
        (project / "work" / "plans").mkdir(parents=True)
        (project / "work" / "qa").mkdir(parents=True)
        (project / ".vlog-project.json").write_text(
            json.dumps({"project_id": "synthetic"}), encoding="utf-8"
        )
        plan = {
            "schema_version": "1.0",
            "project_id": "synthetic",
            "version": 2,
            "parent_version": 1,
            "brief": {"target_duration_sec": 1.0},
            "chapters": [
                {
                    "id": "ch01",
                    "title": "Synthetic",
                    "segments": [
                        {
                            "source": "raw/synthetic.mp4",
                            "in_sec": 0.0,
                            "out_sec": 1.0,
                        }
                    ],
                }
            ],
            "music": [],
            "qa": [],
            "created_at": "2026-08-04T00:00:00Z",
        }
        plan_path = project / "work" / "plans" / "edit_plan.v2.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        approval_path = project / "work" / "qa" / "approval.v2.json"
        approval_path.write_text(
            json.dumps(
                {
                    "status": "approved",
                    "project_id": "synthetic",
                    "plan_version": 2,
                    "plan_sha256": plan_sha256(plan),
                }
            ),
            encoding="utf-8",
        )
        media = root / "directed-base.mp4"
        media.write_bytes(b"synthetic-media")
        import hashlib

        timeline_path = project / "work" / "qa" / "render.v2.json"
        timeline_path.write_text(
            json.dumps(
                {
                    "project_id": "synthetic",
                    "version": 2,
                    "duration_sec": 1.0,
                    "segments": [
                        {"segment_id": "ch01-s001", "start_sec": 0.0, "end_sec": 1.0}
                    ],
                    "output_identity": {
                        "size_bytes": media.stat().st_size,
                        "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "project": project,
            "plan": plan_path,
            "approval": approval_path,
            "timeline": timeline_path,
            "media": media,
            "output": project / "work" / "qa" / "directed-base.v2.json",
        }

    def test_contract_binds_approved_plan_timeline_media_and_producer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            with (
                patch("vlog_director.production_contract.find_ffmpeg", return_value="ffmpeg"),
                patch(
                    "vlog_director.production_contract.probe_media",
                    return_value={
                        "duration_sec": 1.0,
                        "width": 160,
                        "height": 90,
                        "has_video": True,
                        "has_audio": True,
                    },
                ),
                patch(
                    "vlog_director.production_contract.inspect_ffmpeg_identity",
                    return_value={"executable_sha256": "f" * 64, "version_line": "ffmpeg synthetic"},
                ),
            ):
                result = bind_directed_base(
                    project=fixture["project"],
                    edit_plan_path=fixture["plan"],
                    approval_path=fixture["approval"],
                    realized_timeline_path=fixture["timeline"],
                    base_media_path=fixture["media"],
                    output_path=fixture["output"],
                    producer={
                        "repository": "https://github.com/mwh22-up/firered-vlog-pipeline.git",
                        "commit_sha": "a" * 40,
                        "contract": "render-directed-v1",
                    },
                )

            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["base_media"]["sha256"], json.loads(fixture["timeline"].read_text())["output_identity"]["sha256"])
            self.assertTrue(fixture["output"].is_file())
            self.assertNotIn(str(Path(directory).resolve()), fixture["output"].read_text(encoding="utf-8"))

    def test_contract_fails_when_media_changed_after_timeline_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            fixture["media"].write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "base SHA-256"):
                bind_directed_base(
                    project=fixture["project"],
                    edit_plan_path=fixture["plan"],
                    approval_path=fixture["approval"],
                    realized_timeline_path=fixture["timeline"],
                    base_media_path=fixture["media"],
                    output_path=fixture["output"],
                    producer={"repository": "repo", "commit_sha": "a" * 40, "contract": "v1"},
                )


if __name__ == "__main__":
    unittest.main()
