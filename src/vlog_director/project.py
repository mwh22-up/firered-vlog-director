from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .enhancement import build_enhancement_plan, validate_enhancement_plan
from .protection import validate_protection

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PROJECT_DIRECTORIES = (
    "raw",
    "assets/music",
    "assets/illustrations",
    "assets/fonts",
    "work/proxy",
    "work/thumbnails",
    "work/transcripts",
    "work/analysis",
    "work/plans",
    "work/enhancement",
    "work/stabilized",
    "work/subtitles",
    "work/qa",
    "output/chapters",
)


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def init_project(projects_root: Path, project_id: str) -> dict[str, Any]:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError(
            "project_id must start with a letter or number and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        )

    root = projects_root.expanduser().resolve()
    project = (root / project_id).resolve()
    if project.parent != root:
        raise ValueError("project path must stay inside projects_root")

    created: list[str] = []
    project.mkdir(parents=True, exist_ok=True)
    for relative_directory in PROJECT_DIRECTORIES:
        directory = project / relative_directory
        if not directory.exists():
            directory.mkdir(parents=True)
            created.append(relative_directory)

    marker = project / ".vlog-project.json"
    if not marker.exists():
        _write_json(
            marker,
            {
                "schema_version": "1.0",
                "project_id": project_id,
                "layout": "firered-vlog-project-v1",
            },
        )
        created.append(marker.name)

    brief = project / "brief.yaml"
    if not brief.exists():
        brief.write_text(
            "project_id: " + project_id + "\n"
            "target_duration_sec: 90\n"
            "aspect_ratio: '9:16'\n"
            "mode: timeline\n"
            "keep_dialogue: true\n"
            "director_profile: null\n"
            "must_keep: []\n",
            encoding="utf-8",
        )
        created.append(brief.name)

    return {
        "status": "ready",
        "project_id": project_id,
        "project_path": str(project),
        "created": created,
    }


def guard_project_render(
    project: Path,
    version: int,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = project.expanduser().resolve()
    marker = project / ".vlog-project.json"
    moments_path = project / "work" / "analysis" / "moments.json"
    plan_path = project / "work" / "plans" / f"edit_plan.v{version}.json"
    output_path = project / "work" / "qa" / f"protection.v{version}.json"

    missing = [
        str(path)
        for path in (marker, moments_path, plan_path)
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError("required project files are missing: " + ", ".join(missing))

    result = validate_protection(
        _read_json(moments_path),
        _read_json(plan_path),
        policy=policy,
    )
    result["project_path"] = str(project)
    result["moments_path"] = str(moments_path)
    result["plan_path"] = str(plan_path)
    result["report_path"] = str(output_path)
    _write_json(output_path, result)
    return result


def init_project_enhancement(project: Path, edit_version: int) -> dict[str, Any]:
    project = project.expanduser().resolve()
    plan_path = project / "work" / "plans" / f"edit_plan.v{edit_version}.json"
    output_path = (
        project / "work" / "enhancement" / f"enhancement_plan.v{edit_version}.json"
    )
    if not plan_path.is_file():
        raise FileNotFoundError(f"edit plan is missing: {plan_path}")
    if output_path.exists():
        raise FileExistsError(f"enhancement plan already exists: {output_path}")

    edit_plan = _read_json(plan_path)
    result = build_enhancement_plan(edit_plan)
    validation = validate_enhancement_plan(edit_plan, result)
    if validation["status"] != "passed":
        raise RuntimeError(
            "generated enhancement plan failed its release contract: "
            + json.dumps(validation["issues"], ensure_ascii=False)
        )
    _write_json(output_path, result)
    return {
        "status": "ready",
        "project_path": str(project),
        "edit_plan_path": str(plan_path),
        "enhancement_plan_path": str(output_path),
    }


def guard_project_enhancement(project: Path, version: int) -> dict[str, Any]:
    project = project.expanduser().resolve()
    edit_path = project / "work" / "plans" / f"edit_plan.v{version}.json"
    enhancement_path = (
        project / "work" / "enhancement" / f"enhancement_plan.v{version}.json"
    )
    output_path = project / "work" / "qa" / f"enhancement.v{version}.json"

    missing = [str(path) for path in (edit_path, enhancement_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("required enhancement files are missing: " + ", ".join(missing))

    result = validate_enhancement_plan(
        _read_json(edit_path),
        _read_json(enhancement_path),
    )
    result["project_path"] = str(project)
    result["edit_plan_path"] = str(edit_path)
    result["enhancement_plan_path"] = str(enhancement_path)
    result["report_path"] = str(output_path)
    _write_json(output_path, result)
    return result
