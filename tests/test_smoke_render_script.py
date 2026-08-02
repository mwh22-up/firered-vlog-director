from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = REPOSITORY_ROOT / "scripts" / "smoke-render.ps1"


@unittest.skipUnless(os.name == "nt", "PowerShell smoke gate runs on Windows")
class SmokeRenderScriptTests(unittest.TestCase):
    def test_portable_smoke_gate_uses_explicit_bundled_ffmpeg(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
        self.assertIsNotNone(powershell, "PowerShell executable is required")
        ffmpeg = get_ffmpeg_exe()
        self.assertTrue(Path(ffmpeg).is_file())

        completed = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SMOKE_SCRIPT),
                "-PythonExecutable",
                sys.executable,
                "-FFmpegExecutable",
                ffmpeg,
            ],
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("[passed] Formal enhancement schema", completed.stdout)
        self.assertIn("[passed] Runtime enhancement guard", completed.stdout)
        self.assertIn("[passed] Audio QA report", completed.stdout)
        self.assertIn("[passed] Full mapped video/audio decode", completed.stdout)
        self.assertIn(
            "[passed] Portable enhancement render smoke gate",
            completed.stdout,
        )

    def test_script_does_not_depend_on_ffprobe(self) -> None:
        script = SMOKE_SCRIPT.read_text(encoding="utf-8").lower()
        self.assertNotIn("ffprobe", script)
        self.assertIn("-map', '0:v:0'", script)
        self.assertIn("-map', '0:a:0'", script)


if __name__ == "__main__":
    unittest.main()
