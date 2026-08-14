from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


def canonical_plan_bytes(plan: dict[str, Any]) -> bytes:
    return json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def plan_sha256(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def approve_timeline(
    candidate_path: Path,
    output_path: Path,
    receipt_path: Path,
    *,
    approved_by: str,
) -> dict[str, Any]:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8-sig"))
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    version = int(candidate.get("version", 0))
    parent_version = candidate.get("parent_version")
    if version < 2 or parent_version is None or version <= int(parent_version):
        raise ValueError("only a versioned director revision can be approved")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema_version": "1.0",
        "status": "approved",
        "project_id": candidate.get("project_id"),
        "plan_version": version,
        "parent_version": parent_version,
        "plan_sha256": plan_sha256(candidate),
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "source_candidate": str(candidate_path.resolve()),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _validate_schema(document: dict[str, Any], schema_name: str, label: str) -> None:
    schema_path = Path(__file__).with_name("schemas") / schema_name
    schema = _load_object(schema_path, f"{label} schema")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document),
        key=lambda error: error.json_path,
    )
    if errors:
        raise ValueError(
            f"{label} schema invalid: "
            + "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        )


def _confined_file(project: Path, path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = (project / root).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {root.as_posix()}") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _confined_new_file(project: Path, path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = (project / root).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {root.as_posix()}") from error
    if resolved == allowed or resolved.exists():
        raise FileExistsError(resolved)
    return resolved


def _project_relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def approve_previewed_timeline(
    *,
    project: Path,
    candidate_path: Path,
    review_pack_path: Path,
    selection_path: Path,
    output_path: Path,
    receipt_path: Path,
    approved_by: str,
) -> dict[str, Any]:
    """Approve only a candidate selected from SHA-bound non-release previews."""
    project = project.resolve()
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    marker = _load_object(project / ".vlog-project.json", "project marker")
    raw_candidate = _confined_file(
        project,
        candidate_path,
        Path("work") / "director",
        "candidate",
    )
    candidate = _load_object(raw_candidate, "candidate")
    version = int(candidate.get("version", 0))
    parent_version = candidate.get("parent_version")
    if version < 2 or parent_version is None or version <= int(parent_version):
        raise ValueError("only a versioned director revision can be approved")
    proposal_root = Path("work") / "director" / f"v{version}-proposal"
    candidate_file = _confined_file(
        project,
        raw_candidate,
        proposal_root / "candidates",
        "candidate",
    )
    review_pack_file = _confined_file(
        project,
        review_pack_path,
        proposal_root,
        "candidate review pack",
    )
    selection_file = _confined_file(
        project,
        selection_path,
        proposal_root,
        "preview selection",
    )
    output = _confined_new_file(
        project,
        output_path,
        Path("work") / "plans",
        "approved plan output",
    )
    receipt = _confined_new_file(
        project,
        receipt_path,
        Path("work") / "qa",
        "approval receipt",
    )
    expected_receipt_name = f"{output.stem}.approval.json"
    if receipt.name != expected_receipt_name:
        raise ValueError(f"approval receipt must be named {expected_receipt_name}")

    review_pack = _load_object(review_pack_file, "candidate review pack")
    selection = _load_object(selection_file, "preview selection")
    _validate_schema(
        review_pack,
        "directed-candidate-review-pack.schema.json",
        "candidate review pack",
    )
    _validate_schema(
        selection,
        "directed-preview-selection.schema.json",
        "preview selection",
    )
    project_id = str(candidate.get("project_id", ""))
    if (
        marker.get("project_id") != project_id
        or review_pack.get("project_id") != project_id
        or selection.get("project_id") != project_id
        or int(review_pack.get("plan_version", 0)) != version
        or int(selection.get("plan_version", 0)) != version
    ):
        raise ValueError("candidate preview approval project or version binding does not match")
    labels = [item.get("label") for item in review_pack["candidates"]]
    candidate_digests = [
        item.get("candidate", {}).get("sha256") for item in review_pack["candidates"]
    ]
    if len(labels) != len(set(labels)) or len(candidate_digests) != len(set(candidate_digests)):
        raise ValueError("candidate review pack labels and candidate SHAs must be unique")
    review_pack_sha = _file_sha256(review_pack_file)
    if selection.get("review_pack_sha256") != review_pack_sha:
        raise ValueError("preview selection does not bind the candidate review pack")

    selected = [
        item
        for item in review_pack["candidates"]
        if item.get("label") == selection.get("selected_label")
    ]
    if len(selected) != 1:
        raise ValueError("preview selection label is not unique in the candidate review pack")
    selected_entry = selected[0]
    candidate_sha = _file_sha256(candidate_file)
    expected_candidate_binding = {
        "path": _project_relative(project, candidate_file),
        "sha256": candidate_sha,
    }
    if selected_entry.get("candidate") != expected_candidate_binding:
        raise ValueError("selected review-pack candidate does not match candidate input")
    expected_selection_bindings = {
        "selected_candidate_sha256": candidate_sha,
        "preview_media_sha256": selected_entry["preview_media"]["sha256"],
        "realized_timeline_sha256": selected_entry["realized_timeline"]["sha256"],
        "cut_qa_sha256": selected_entry["cut_qa"]["sha256"],
    }
    if any(selection.get(key) != value for key, value in expected_selection_bindings.items()):
        raise ValueError("preview selection evidence bindings do not match selected candidate")

    evidence_files: dict[str, Path] = {}
    for key in ("preview_media", "realized_timeline", "cut_qa"):
        binding = selected_entry[key]
        evidence_path = _confined_file(
            project,
            project / binding["path"],
            proposal_root / "previews" / candidate_sha,
            key.replace("_", " "),
        )
        if _file_sha256(evidence_path) != binding["sha256"]:
            raise ValueError(f"{key.replace('_', ' ')} changed after review-pack creation")
        evidence_files[key] = evidence_path

    timeline = _load_object(evidence_files["realized_timeline"], "preview realized timeline")
    if (
        timeline.get("contract_version") != "render-candidate-preview-v1"
        or timeline.get("status") != "review_required"
        or timeline.get("project_id") != project_id
        or int(timeline.get("version", 0)) != version
        or timeline.get("plan_sha256") != candidate_sha
        or timeline.get("candidate_sha256") != candidate_sha
        or timeline.get("media_quality") != "proxy"
        or timeline.get("non_release_marker")
        != {"applied": True, "text": "NON-RELEASE CANDIDATE"}
        or timeline.get("output_identity", {}).get("sha256")
        != selected_entry["preview_media"]["sha256"]
    ):
        raise ValueError("selected candidate timeline is not valid non-release preview evidence")
    cut_qa = _load_object(evidence_files["cut_qa"], "preview cut QA")
    _validate_schema(cut_qa, "directed-cut-qa.schema.json", "preview cut QA")
    if (
        cut_qa.get("project_id") != project_id
        or int(cut_qa.get("plan_version", 0)) != version
        or cut_qa.get("plan_sha256") != candidate_sha
        or cut_qa.get("realized_timeline_sha256")
        != selected_entry["realized_timeline"]["sha256"]
        or cut_qa.get("base_media", {}).get("sha256")
        != selected_entry["preview_media"]["sha256"]
    ):
        raise ValueError("selected candidate cut QA bindings do not match preview evidence")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    approval_receipt = {
        "schema_version": "1.0",
        "approval_contract_version": "previewed-timeline-approval-v1",
        "status": "approved",
        "project_id": project_id,
        "plan_version": version,
        "parent_version": parent_version,
        "plan_sha256": plan_sha256(candidate),
        "candidate_sha256": candidate_sha,
        "approved_by": approved_by.strip(),
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "source_candidate": _project_relative(project, candidate_file),
        "review_pack": {
            "path": _project_relative(project, review_pack_file),
            "sha256": review_pack_sha,
        },
        "human_selection": {
            "path": _project_relative(project, selection_file),
            "sha256": _file_sha256(selection_file),
            "selected_by": selection["selected_by"],
        },
        "preview_evidence": {
            key: selected_entry[key] for key in ("preview_media", "realized_timeline", "cut_qa")
        },
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(approval_receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return approval_receipt


def verify_approval(plan: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if receipt.get("status") != "approved":
        issues.append("approval status is not approved")
    if receipt.get("project_id") != plan.get("project_id"):
        issues.append("approval project_id does not match plan")
    if int(receipt.get("plan_version", 0)) != int(plan.get("version", 0)):
        issues.append("approval plan_version does not match plan")
    if receipt.get("plan_sha256") != plan_sha256(plan):
        issues.append("approved plan hash changed after approval")
    return {
        "status": "passed" if not issues else "blocked",
        "plan_sha256": plan_sha256(plan),
        "issues": issues,
    }
