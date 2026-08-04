import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vlog_director.durable_jobs import (
    JOB_RUNTIME_VERSION,
    request_job_cancel,
    run_durable_job,
    submit_durable_job,
)


class DurableJobTests(unittest.TestCase):
    def _queued_job(self, root: Path, operation: str = "render-effects") -> Path:
        job = root / "work" / "jobs" / operation / "20260804T120000-012345abcdef"
        job.mkdir(parents=True)
        spec = {
            "runtime_version": JOB_RUNTIME_VERSION,
            "operation": operation,
            "job_type": operation,
            "project": str(root.resolve()),
            "output_directory": str(job.resolve()),
            "arguments": {"value": 7},
        }
        (job / "job.json").write_text(json.dumps(spec), encoding="utf-8")
        (job / "status.json").write_text(
            json.dumps({"status": "queued"}), encoding="utf-8"
        )
        return job

    def test_job_claim_result_and_terminal_status_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = self._queued_job(Path(directory))
            result = run_durable_job(
                job / "job.json",
                handlers={"render-effects": lambda arguments, cancelled: {"status": "ready", "value": arguments["value"]}},
            )
            status = json.loads((job / "status.json").read_text(encoding="utf-8"))

            self.assertEqual(result["value"], 7)
            self.assertEqual(status["status"], "completed")
            self.assertTrue((job / "claim.json").is_file())
            self.assertTrue((job / "result.json").is_file())
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                run_durable_job(job / "job.json", handlers={})

    def test_spec_must_be_in_exact_project_job_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = self._queued_job(root)
            moved = root / "job.json"
            moved.write_bytes((job / "job.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "escaped"):
                run_durable_job(moved, handlers={})

    def test_cancelled_queued_job_never_calls_handler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = self._queued_job(Path(directory))
            request_job_cancel(job)
            handler = Mock(return_value={"status": "ready"})
            result = run_durable_job(job / "job.json", handlers={"render-effects": handler})

            self.assertEqual(result["status"], "cancelled")
            handler.assert_not_called()
            status = json.loads((job / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "cancelled")

    def test_submit_does_not_overwrite_fast_worker_terminal_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)

            def complete_immediately(command, **kwargs):
                spec_path = Path(command[-1])
                status_path = spec_path.parent / "status.json"
                status_path.write_text(
                    json.dumps({"status": "completed", "exit_code": 0}),
                    encoding="utf-8",
                )
                process = Mock()
                process.pid = 42
                return process

            with patch("vlog_director.durable_jobs.subprocess.Popen", side_effect=complete_immediately):
                result = submit_durable_job(
                    project=project,
                    operation="render-effects",
                    arguments={"project": str(project)},
                )

            status = json.loads(Path(result["job_status"]).read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "completed")


if __name__ == "__main__":
    unittest.main()
