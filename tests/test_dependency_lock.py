from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path
from urllib.parse import urlparse

from vlog_director.effect_plan import (
    HYPERFRAMES_NPM_INTEGRITY,
    HYPERFRAMES_VERSION,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DependencyLockTests(unittest.TestCase):
    def test_python_matrix_uses_a_numpy_pin_compatible_with_python_311(self) -> None:
        pyproject = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        constraints = (REPOSITORY_ROOT / "constraints" / "test.txt").read_text(
            encoding="utf-8"
        )

        self.assertEqual(pyproject["project"]["requires-python"], ">=3.11,<3.13")
        self.assertRegex(workflow, r"python-version: \['3\.11', '3\.12'\]")
        numpy_pins = re.findall(r"(?m)^numpy==([^;\s]+)", constraints)
        self.assertEqual(numpy_pins, ["2.4.6"])

    def test_libass_ci_provisions_ffmpeg_and_preserves_probe_diagnostics(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("sudo apt-get install --yes ffmpeg", workflow)
        self.assertIn("ffmpeg -version", workflow)
        self.assertIn("ffmpeg -buildconf", workflow)
        self.assertIn("ffmpeg -hide_banner -filters", workflow)
        self.assertIn("from vlog_director.ffmpeg import require_filters", workflow)
        self.assertNotIn("| grep -E ' subtitles", workflow)

    def test_hyperframes_toolchain_is_pinned_to_public_npm_artifacts(self) -> None:
        package = json.loads(
            (REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8")
        )
        lock = json.loads(
            (REPOSITORY_ROOT / "package-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual(package["devDependencies"]["hyperframes"], HYPERFRAMES_VERSION)
        self.assertEqual(package["devDependencies"]["ffprobe-static"], "3.1.0")
        self.assertEqual(lock["packages"][""]["devDependencies"], package["devDependencies"])

        hyperframes = lock["packages"]["node_modules/hyperframes"]
        self.assertEqual(hyperframes["version"], HYPERFRAMES_VERSION)
        self.assertEqual(hyperframes["integrity"], HYPERFRAMES_NPM_INTEGRITY)

        ffprobe = lock["packages"]["node_modules/ffprobe-static"]
        self.assertEqual(ffprobe["version"], "3.1.0")

        for artifact in (hyperframes, ffprobe):
            with self.subTest(package=artifact["resolved"]):
                self.assertEqual(
                    urlparse(artifact["resolved"]).netloc,
                    "registry.npmjs.org",
                )

        serialized = json.dumps(lock, sort_keys=True).lower()
        self.assertNotIn("nexus.mcd", serialized)
        self.assertNotIn("_auth", serialized)
        self.assertNotIn("token", serialized)


if __name__ == "__main__":
    unittest.main()
