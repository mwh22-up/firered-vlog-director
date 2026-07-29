from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .protection import validate_protection


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
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
    validate.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "validate-protection":
        result = validate_protection(_read_json(args.moments), _read_json(args.plan))
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
