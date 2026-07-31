from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.test_director_engine import MOMENTS, PROFILE, parent_plan, target_analysis
from vlog_director.cli import main
from vlog_director.technique_learning import aggregate_technique_studies


def _write_json(path: Path, document: dict) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _technique_study(source_id: str, observation_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "study_id": f"study-{source_id}",
        "source": {
            "source_id": source_id,
            "url": f"https://example.com/{source_id}",
        },
        "technique_observations": [
            {
                "observation_id": observation_id,
                "technique_key": "humor-preserve-real-awkward-process",
                "start_sec": 1.0,
                "end_sec": 2.0,
                "category": "humor",
                "trigger": "the target footage contains an evidence-backed awkward process",
                "treatment": "retain the complete process before its resolution",
                "confidence": 0.9,
                "parameters": {"resolution_retained": True},
                "guardrails": ["apply only when target fun evidence is present"],
            }
        ],
    }


def _valid_technique_aggregate() -> dict:
    return aggregate_technique_studies(
        [
            _technique_study("reference-a", "observation-a"),
            _technique_study("reference-b", "observation-b"),
        ],
        minimum_source_support=2,
    )


class DirectTimelineCliTests(unittest.TestCase):
    def _write_inputs(self, root: Path, aggregate: dict) -> dict[str, Path]:
        paths = {
            "parent": root / "parent.json",
            "analysis": root / "analysis.json",
            "profile": root / "profile.json",
            "technique_profile": root / "technique-profile.json",
            "moments": root / "moments.json",
            "output": root / "director-output",
        }
        _write_json(paths["parent"], parent_plan())
        _write_json(paths["analysis"], target_analysis())
        _write_json(paths["profile"], PROFILE)
        _write_json(paths["technique_profile"], aggregate)
        _write_json(paths["moments"], MOMENTS)
        return paths

    @staticmethod
    def _argv(paths: dict[str, Path]) -> list[str]:
        return [
            "vlog-director",
            "direct-timeline",
            "--parent",
            str(paths["parent"]),
            "--analysis",
            str(paths["analysis"]),
            "--profile",
            str(paths["profile"]),
            "--technique-profile",
            str(paths["technique_profile"]),
            "--moments",
            str(paths["moments"]),
            "--version",
            "2",
            "--output-directory",
            str(paths["output"]),
        ]

    def test_direct_timeline_writes_content_digest_technique_profile_id(self) -> None:
        aggregate = _valid_technique_aggregate()
        expected_profile_id = aggregate["profile_id"]
        self.assertRegex(
            expected_profile_id,
            r"^aggregated-reference-techniques-v1-[0-9a-f]{12}$",
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = self._write_inputs(Path(temporary_directory), aggregate)
            stdout = io.StringIO()
            with patch.object(sys, "argv", self._argv(paths)), redirect_stdout(stdout):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["technique_profile_id"], expected_profile_id)

            report_path = paths["output"] / "director_report.json"
            self.assertTrue(report_path.is_file())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["technique_profile_id"], expected_profile_id)
            self.assertEqual(
                report["technique_application"]["profile_id"],
                expected_profile_id,
            )
            self.assertTrue(report["candidates"])
            self.assertTrue(
                all(
                    candidate["evaluation"]["technique_application"]["profile_id"]
                    == expected_profile_id
                    for candidate in report["candidates"]
                )
            )

    def test_invalid_technique_profile_fails_before_writing_artifacts(self) -> None:
        invalid = copy.deepcopy(_valid_technique_aggregate())
        invalid["source_count"] += 1

        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = self._write_inputs(Path(temporary_directory), invalid)
            stdout = io.StringIO()
            with self.assertRaisesRegex(ValueError, "source_count must match source_ids"):
                with patch.object(sys, "argv", self._argv(paths)), redirect_stdout(stdout):
                    main()

            self.assertEqual(stdout.getvalue(), "")
            self.assertFalse((paths["output"] / "director_report.json").exists())
            self.assertEqual(list(paths["output"].glob("candidate.*.json")), [])


if __name__ == "__main__":
    unittest.main()
