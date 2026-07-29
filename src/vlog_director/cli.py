from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .protection import validate_protection
from .renderers import load_json, render_enhanced_video, stabilize_video
from .project import (
    guard_project_enhancement,
    guard_project_render,
    init_project,
    init_project_enhancement,
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vlog-director")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-protection")
    validate.add_argument("--moments", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--policy", type=Path)
    validate.add_argument("--output", type=Path)

    init = subparsers.add_parser("init-project")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--project-id", required=True)

    guard = subparsers.add_parser("guard-render")
    guard.add_argument("--project", type=Path, required=True)
    guard.add_argument("--version", type=int, required=True)
    guard.add_argument("--policy", type=Path)

    init_enhancement = subparsers.add_parser("init-enhancement")
    init_enhancement.add_argument("--project", type=Path, required=True)
    init_enhancement.add_argument("--version", type=int, required=True)

    guard_enhancement = subparsers.add_parser("guard-enhancement")
    guard_enhancement.add_argument("--project", type=Path, required=True)
    guard_enhancement.add_argument("--version", type=int, required=True)

    stabilize = subparsers.add_parser("stabilize")
    stabilize.add_argument("--input", type=Path, required=True)
    stabilize.add_argument("--output", type=Path, required=True)
    stabilize.add_argument("--work-directory", type=Path, required=True)
    stabilize.add_argument("--strength", type=float, default=0.35)
    stabilize.add_argument("--max-crop-percent", type=float, default=8.0)

    render_enhancement = subparsers.add_parser("render-enhancement")
    render_enhancement.add_argument("--project", type=Path, required=True)
    render_enhancement.add_argument("--base-video", type=Path, required=True)
    render_enhancement.add_argument("--plan", type=Path, required=True)
    render_enhancement.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "validate-protection":
        policy = _read_json(args.policy) if args.policy else None
        result = validate_protection(
            _read_json(args.moments),
            _read_json(args.plan),
            policy=policy,
        )
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-project":
        _write_result(init_project(args.root, args.project_id), None)
        return 0
    if args.command == "guard-render":
        policy = _read_json(args.policy) if args.policy else None
        result = guard_project_render(args.project, args.version, policy=policy)
        _write_result(result, None)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-enhancement":
        _write_result(init_project_enhancement(args.project, args.version), None)
        return 0
    if args.command == "guard-enhancement":
        result = guard_project_enhancement(args.project, args.version)
        _write_result(result, None)
        return 0 if result["status"] == "passed" else 2
    if args.command == "stabilize":
        stabilize_video(
            args.input,
            args.output,
            args.work_directory,
            strength=args.strength,
            max_crop_percent=args.max_crop_percent,
        )
        _write_result({"status": "ready", "output": str(args.output.resolve())}, None)
        return 0
    if args.command == "render-enhancement":
        render_enhanced_video(
            args.project.resolve(),
            args.base_video.resolve(),
            load_json(args.plan),
            args.output.resolve(),
        )
        _write_result({"status": "ready", "output": str(args.output.resolve())}, None)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
