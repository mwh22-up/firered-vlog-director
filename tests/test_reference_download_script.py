from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class ReferenceDownloadScriptTests(unittest.TestCase):
    def test_windows_curl_keeps_tls_validation_when_revocation_service_is_offline(self) -> None:
        script = (REPOSITORY_ROOT / "scripts" / "fetch-bilibili-proxy.ps1").read_text(
            encoding="utf-8"
        )

        self.assertEqual(script.count("--ssl-revoke-best-effort"), 2)
        self.assertNotIn("--ssl-no-revoke", script)
        self.assertNotIn("--insecure", script)


if __name__ == "__main__":
    unittest.main()