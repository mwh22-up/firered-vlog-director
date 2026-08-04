from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from vlog_director.effect_plan import build_effect_plan
from vlog_director.hyperframes_effects import (
    build_hyperframes_compositions,
    render_hyperframes_compositions,
)


def canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hyperframes", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    args = parser.parse_args()
    hyperframes = str(Path(args.hyperframes).resolve())
    ffmpeg = str(Path(args.ffmpeg).resolve())
    ffprobe = str(Path(args.ffprobe).resolve())
    with tempfile.TemporaryDirectory(prefix="firered-hyperframes-smoke-") as temporary:
        project = Path(temporary) / "project"
        tool_directory = Path(temporary) / "tools"
        tool_directory.mkdir()
        shutil.copy2(ffmpeg, tool_directory / "ffmpeg.exe")
        shutil.copy2(ffprobe, tool_directory / "ffprobe.exe")
        os.environ["PATH"] = str(tool_directory) + os.pathsep + os.environ.get("PATH", "")
        (project / "work" / "plans").mkdir(parents=True)
        (project / "work" / "effects").mkdir(parents=True)
        edit_plan = {
            "schema_version": "1.0",
            "project_id": "hyperframes-ci-smoke",
            "version": 1,
            "chapters": [
                {
                    "id": "ch01",
                    "title": "",
                    "segments": [
                        {
                            "source": "raw/synthetic.mp4",
                            "in_sec": 0.0,
                            "out_sec": 2.0,
                            "story_role": "reaction",
                        }
                    ],
                }
            ],
        }
        edit_path = project / "work" / "plans" / "edit_plan.v1.json"
        edit_path.write_text(json.dumps(edit_plan), encoding="utf-8")
        effect_plan = build_effect_plan(
            edit_plan,
            edit_plan_sha256=canonical(edit_plan),
        )
        effect_path = project / "work" / "effects" / "effect_plan.v1.json"
        effect_path.write_text(json.dumps(effect_plan), encoding="utf-8")
        job = project / "work" / "effects" / "ci-smoke"
        build_hyperframes_compositions(
            project,
            effect_path,
            job,
            canvas_width=320,
            canvas_height=180,
        )
        rendered = render_hyperframes_compositions(
            project,
            effect_path,
            job / "composition-manifest.json",
            executable=hyperframes,
            quality="draft",
        )
        for effect in rendered["effects"]:
            media = project / effect["output"]
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-xerror",
                    "-v",
                    "error",
                    "-i",
                    str(media),
                    "-map",
                    "0:v:0",
                    "-vf",
                    "alphaextract,scale=320:180",
                    "-f",
                    "null",
                    "NUL",
                ],
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError("HyperFrames alpha smoke decode failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
