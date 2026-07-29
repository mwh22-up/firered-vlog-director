import tempfile
import unittest
from pathlib import Path

from vlog_director.renderers import load_json


class JsonCompatibilityTests(unittest.TestCase):
    def test_load_json_accepts_utf8_bom_from_windows_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "plan.json"
            path.write_text('{"schema_version":"1.0"}', encoding="utf-8-sig")

            self.assertEqual(load_json(path)["schema_version"], "1.0")


if __name__ == "__main__":
    unittest.main()
