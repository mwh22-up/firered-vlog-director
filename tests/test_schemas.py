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
                "enhancement-plan.schema.json",
                "moments.schema.json",
                "protection-policy.schema.json",
                "reference-analysis.schema.json",
                "reference-technique-aggregate.schema.json",
                "reference-technique-study.schema.json",
            },
        )
        for name, schema in self.schemas.items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)

    def test_runtime_enhancement_schema_matches_formal_schema(self) -> None:
        packaged = load_json(
            PACKAGED_SCHEMA_DIRECTORY / "enhancement-plan.schema.json"
        )
        self.assertEqual(packaged, self.schemas["enhancement-plan.schema.json"])

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
            "reference-analysis.schema.json": 15,
            "reference-technique-study.schema.json": 6,
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
        self.assertEqual(len(formal_reference_paths), 34)

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
        self.assertEqual(len(json_paths), 48)
        for path in json_paths:
            with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                load_json(path)


if __name__ == "__main__":
    unittest.main()
