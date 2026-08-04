from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _schema(name: str) -> dict[str, Any]:
    return _load(Path(__file__).with_name("schemas") / name, name)


def _confined(project: Path, path: Path, root: str, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to((project / root).resolve())
    except ValueError as error:
        raise ValueError(f"{label} must stay under {root}") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def approve_release(
    *, project: Path, media_path: Path, enhancement_plan_path: Path,
    directed_base_contract_path: Path, visual_qa_path: Path,
    human_review_path: Path, output_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    media = _confined(project, media_path, "output", "release media")
    plan_path = _confined(project, enhancement_plan_path, "work/enhancement", "enhancement plan")
    base_contract_path = _confined(project, directed_base_contract_path, "work/qa", "directed base contract")
    visual_path = _confined(project, visual_qa_path, "work/qa/release-visual", "release visual QA")
    review_path = _confined(project, human_review_path, "work/qa/release-visual", "release human review")
    output = output_path.resolve()
    try:
        output.relative_to((project / "work" / "qa" / "release-approval").resolve())
    except ValueError as error:
        raise ValueError("release approval output must stay under work/qa/release-approval") from error
    if output.exists():
        raise FileExistsError(output)
    marker = _load(project / ".vlog-project.json", "project marker")
    plan = _load(plan_path, "enhancement plan")
    base_contract = _load(base_contract_path, "directed base contract")
    visual = _load(visual_path, "release visual QA")
    review = _load(review_path, "release human review")
    review_errors = list(Draft202012Validator(_schema("release-human-review.schema.json"), format_checker=FormatChecker()).iter_errors(review))
    if review_errors:
        raise ValueError("release human review schema invalid")
    media_sha = _sha(media)
    if visual.get("status") not in {"passed", "warning"} or visual.get("blocking_count") != 0:
        raise ValueError("release visual QA has blockers")
    visual_bindings = visual.get("bindings", {})
    if visual_bindings.get("media", {}).get("sha256") != media_sha:
        raise ValueError("release visual QA media SHA-256 changed")
    if visual_bindings.get("enhancement_plan", {}).get("sha256") != _sha(plan_path):
        raise ValueError("release visual QA enhancement plan SHA-256 changed")
    if visual_bindings.get("directed_base_contract", {}).get("sha256") != _sha(base_contract_path):
        raise ValueError("release visual QA directed base contract SHA-256 changed")
    if base_contract.get("status") != "ready" or base_contract.get("project_id") != marker.get("project_id"):
        raise ValueError("directed base contract is not ready for this project")
    if int(base_contract.get("edit_plan", {}).get("path", "v0.json").split(".v")[-1].split(".")[0]) != int(plan.get("edit_plan_version", 0)):
        raise ValueError("directed base contract edit version changed")
    expected_review_bindings = {"media_sha256": media_sha, "enhancement_plan_sha256": _sha(plan_path), "visual_qa_sha256": _sha(visual_path)}
    if review.get("bindings") != expected_review_bindings:
        raise ValueError("release human review bindings changed")
    if review.get("status") != "approved" or any(value != "approved" for value in review.get("decisions", {}).values()):
        raise ValueError("release human review did not approve every required decision")
    if review.get("project_id") != marker.get("project_id"):
        raise ValueError("release human review project changed")
    result = {
        "schema_version": "1.0",
        "contract_version": "release-approval-v1",
        "status": "approved",
        "project_id": str(marker.get("project_id")),
        "media": {"path": media.relative_to(project).as_posix(), "sha256": media_sha, "size_bytes": media.stat().st_size},
        "enhancement_plan": {"path": plan_path.relative_to(project).as_posix(), "sha256": _sha(plan_path)},
        "directed_base_contract": {"path": base_contract_path.relative_to(project).as_posix(), "sha256": _sha(base_contract_path)},
        "visual_qa": {"path": visual_path.relative_to(project).as_posix(), "sha256": _sha(visual_path)},
        "human_review": {"path": review_path.relative_to(project).as_posix(), "sha256": _sha(review_path)},
        "approved_by": str(review["reviewed_by"]),
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    errors = list(Draft202012Validator(_schema("release-approval.schema.json"), format_checker=FormatChecker()).iter_errors(result))
    if errors:
        raise ValueError("release approval schema invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return result
