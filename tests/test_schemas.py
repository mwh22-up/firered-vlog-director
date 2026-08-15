from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "schemas"
PACKAGED_SCHEMA_DIRECTORY = REPOSITORY_ROOT / "src" / "vlog_director" / "schemas"
REFERENCE_DIRECTORY = REPOSITORY_ROOT / "reference-learning"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class SchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema_paths = sorted(SCHEMA_DIRECTORY.glob("*.schema.json"))
        cls.schemas = {
            path.name: load_json(path)
            for path in cls.schema_paths
        }

    def test_all_schema_documents_are_valid_draft_2020_12(self) -> None:
        self.assertEqual(
            set(self.schemas),
            {
                "director-profile-aggregate.schema.json",
                "director-profile.schema.json",
                "director-feedback-facts.schema.json",
                "directed-base-contract.schema.json",
                "directed-base-human-review.schema.json",
                "directed-candidate-review-pack.schema.json",
                "directed-cut-qa.schema.json",
                "directed-preview-selection.schema.json",
                "effect-approval.schema.json",
                "effect-human-review.schema.json",
                "effect-plan.schema.json",
                "effect-protected-regions.schema.json",
                "effect-visual-qa.schema.json",
                "enhancement-plan.schema.json",
                "hyperframes-composition-manifest.schema.json",
                "hyperframes-render-manifest.schema.json",
                "moments.schema.json",
                "music-audition-report.schema.json",
                "protection-policy.schema.json",
                "reference-analysis.schema.json",
                "release-visual-qa.schema.json",
                "release-approval.schema.json",
                "release-human-review.schema.json",
                "reference-technique-aggregate.schema.json",
                "reference-technique-study.schema.json",
                "subtitle-approval.schema.json",
                "subtitle-human-review.schema.json",
                "subtitle-layout-qa.schema.json",
                "subtitle-preview-manifest.schema.json",
                "subtitle-readability-qa.schema.json",
                "subtitle-visual-qa.schema.json",
                "vlm-analysis-evidence.schema.json",
                "vlm-analysis-request.schema.json",
            },
        )
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)

    def test_every_runtime_schema_matches_its_formal_schema(self) -> None:
        packaged_paths = sorted(PACKAGED_SCHEMA_DIRECTORY.glob("*.schema.json"))
        self.assertEqual(
            {path.name for path in packaged_paths},
            {
                name
                for name in self.schemas
                if name in {
                    "enhancement-plan.schema.json",
                    "directed-base-contract.schema.json",
                    "directed-base-human-review.schema.json",
                    "directed-candidate-review-pack.schema.json",
                    "directed-cut-qa.schema.json",
                    "directed-preview-selection.schema.json",
                    "hyperframes-composition-manifest.schema.json",
                    "hyperframes-render-manifest.schema.json",
                    "release-visual-qa.schema.json",
                    "director-feedback-facts.schema.json",
                    "vlm-analysis-evidence.schema.json",
                    "vlm-analysis-request.schema.json",
                    "music-audition-report.schema.json",
                    "release-approval.schema.json",
                    "release-human-review.schema.json",
                }
                or name.startswith("effect-")
                or name.startswith("subtitle-")
            },
        )
        for path in packaged_paths:
            with self.subTest(schema=path.name):
                self.assertEqual(load_json(path), self.schemas[path.name])

    def test_new_subtitle_artifact_schemas_fail_closed(self) -> None:
        for name, schema in self.schemas.items():
            if name.startswith("subtitle-"):
                with self.subTest(schema=name):
                    self.assertIs(schema.get("additionalProperties"), False)

    def test_renderable_music_schema_requires_audition_artifact_references(self) -> None:
        music_schema = self.schemas["enhancement-plan.schema.json"]["properties"][
            "music"
        ]
        validator = Draft202012Validator(music_schema)
        section = {
            "status": "audition",
            "tracks": [
                {
                    "id": "bed",
                    "source": "assets/music/bed.wav",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "gain_db": -18.0,
                }
            ],
            "ducking": {
                "enabled": True,
                "threshold": 0.125,
                "ratio": 8.0,
                "attack_ms": 20,
                "release_ms": 250,
            },
        }

        for status in ("audition", "ready"):
            with self.subTest(status=status):
                section["status"] = status
                section.pop("rights_manifest", None)
                section.pop("audition_report", None)
                self.assertTrue(list(validator.iter_errors(section)))
                section["rights_manifest"] = "assets/music/rights.json"
                section["audition_report"] = "work/qa/audition.json"
                self.assertEqual(list(validator.iter_errors(section)), [])
                section["tracks"] = []
                self.assertTrue(list(validator.iter_errors(section)))
                section["tracks"] = [
                    {
                        "id": "bed",
                        "source": "assets/music/bed.wav",
                        "start_sec": 0.0,
                        "end_sec": 2.0,
                        "gain_db": -18.0,
                    }
                ]

    def test_ready_subtitle_schema_requires_verified_source_identity(self) -> None:
        subtitle_schema = self.schemas["enhancement-plan.schema.json"]["properties"][
            "subtitles"
        ]
        validator = Draft202012Validator(subtitle_schema)
        section = {
            "status": "ready",
            "language": "zh-CN",
            "source": "work/subtitles/reviewed.json",
            "coverage": {"status": "verified"},
            "cues": [
                {
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "verified",
                    "review_status": "verified",
                }
            ],
            "style": {
                "max_lines": 2,
                "safe_margin_percent": 8.0,
                "position": "bottom_center",
            },
        }

        self.assertTrue(list(validator.iter_errors(section)))
        section["source_sha256"] = "a" * 64
        self.assertTrue(list(validator.iter_errors(section)))
        section["evidence"] = {
            "contract_version": "subtitle-ready-evidence-v1",
            "subtitle_payload_sha256": "b" * 64,
            "subtitle_style_sha256": "c" * 64,
            "verified_cue_set_sha256": "d" * 64,
            **{
                name: {"path": f"work/qa/{name}.json", "sha256": "e" * 64}
                for name in ("readability", "layout", "visual", "human_review", "approval")
            },
        }
        self.assertEqual(list(validator.iter_errors(section)), [])
        section["source_sha256"] = "not-a-sha256"
        self.assertTrue(list(validator.iter_errors(section)))

    def test_review_subtitle_schema_requires_source_identity(self) -> None:
        subtitle_schema = self.schemas["enhancement-plan.schema.json"]["properties"][
            "subtitles"
        ]
        validator = Draft202012Validator(subtitle_schema)
        section = {
            "status": "review",
            "language": "zh-CN",
            "source": "work/subtitles/review-required.json",
            "coverage": {"status": "pending"},
            "cues": [
                {
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "review me",
                    "review_status": "review_required",
                }
            ],
            "style": {
                "max_lines": 2,
                "safe_margin_percent": 8.0,
                "position": "bottom_center",
            },
        }

        self.assertTrue(list(validator.iter_errors(section)))
        section["source_sha256"] = "b" * 64
        self.assertEqual(list(validator.iter_errors(section)), [])

    def test_every_formal_json_artifact_matches_its_schema(self) -> None:
        director_profiles = sorted(
            path
            for path in REFERENCE_DIRECTORY.glob("director-profile.*.json")
            if "aggregate" not in path.name
        )
        director_aggregates = sorted(
            path
            for path in REFERENCE_DIRECTORY.glob("director-profile.*.json")
            if "aggregate" in path.name
        )
        groups = {
            "reference-analysis.schema.json": sorted(
                REFERENCE_DIRECTORY.glob("analysis.*.json")
            ),
            "reference-technique-study.schema.json": sorted(
                REFERENCE_DIRECTORY.glob("technique-study.*.v1.json")
            ),
            "reference-technique-aggregate.schema.json": [
                REFERENCE_DIRECTORY / "reference-techniques.aggregate.v1.json"
            ],
            "director-profile.schema.json": director_profiles,
            "director-profile-aggregate.schema.json": director_aggregates,
            "moments.schema.json": [
                REPOSITORY_ROOT / "tests" / "fixtures" / "moments.json"
            ],
            "protection-policy.schema.json": [
                REPOSITORY_ROOT / "policies" / "moment-protection.json"
            ],
        }
        expected_counts = {
            "reference-analysis.schema.json": 20,
            "reference-technique-study.schema.json": 21,
            "reference-technique-aggregate.schema.json": 1,
            "director-profile.schema.json": 7,
            "director-profile-aggregate.schema.json": 5,
            "moments.schema.json": 1,
            "protection-policy.schema.json": 1,
        }
        mapped_reference_paths: set[Path] = set()

        for schema_name, paths in groups.items():
            self.assertEqual(
                len(paths),
                expected_counts[schema_name],
                f"unexpected artifact count for {schema_name}",
            )
            validator = Draft202012Validator(self.schemas[schema_name])
            for path in paths:
                with self.subTest(schema=schema_name, artifact=path.name):
                    self.assertTrue(path.is_file(), f"missing artifact: {path}")
                    errors = sorted(
                        validator.iter_errors(load_json(path)),
                        key=lambda error: tuple(
                            str(value) for value in error.absolute_path
                        ),
                    )
                    if errors:
                        first = errors[0]
                        self.fail(
                            f"{path.relative_to(REPOSITORY_ROOT)} failed "
                            f"{schema_name} at {first.json_path}: {first.message}"
                        )
                if path.parent == REFERENCE_DIRECTORY:
                    mapped_reference_paths.add(path)

        formal_reference_paths = {
            path
            for path in REFERENCE_DIRECTORY.glob("*.json")
            if ".example." not in path.name
        }
        self.assertEqual(mapped_reference_paths, formal_reference_paths)
        self.assertEqual(len(formal_reference_paths), 54)

    def test_all_repository_json_documents_are_parseable(self) -> None:
        json_paths = sorted(
            path
            for directory in (
                REPOSITORY_ROOT / "policies",
                REFERENCE_DIRECTORY,
                SCHEMA_DIRECTORY,
                REPOSITORY_ROOT / "tests" / "fixtures",
            )
            for path in directory.glob("*.json")
        )
        self.assertEqual(len(json_paths), 93)
        for path in json_paths:
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                load_json(path)


if __name__ == "__main__":
    unittest.main()
