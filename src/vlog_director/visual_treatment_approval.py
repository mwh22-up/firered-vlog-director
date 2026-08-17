from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .schema_validation import enhancement_schema_errors
from .visual_treatments import canonical_treatment_payload_sha256


REQUIRED_CHECKS = {"exposure", "color", "detail", "composition"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def canonical_enhancement_treatments_sha256(treatments: Any) -> str:
    return _canonical_sha256(treatments)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _write_new(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _confined(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {allowed}") from error
    if resolved == allowed or not relative.parts:
        raise ValueError(f"{label} cannot equal its allowed root")
    return resolved


@lru_cache(maxsize=4)
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("vlog_director.schemas").joinpath(name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_errors(document: Mapping[str, Any], name: str) -> list[str]:
    errors = sorted(
        _validator(name).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


def _timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("reviewed_at must be a timezone-aware timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reviewed_at must include a timezone")


def _binding(project: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(project.resolve()).as_posix(),
        "sha256": _sha256_file(path.resolve()),
    }


def _collect(
    project: Path,
    plan_path: Path,
    preview_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    plan_path = _confined(plan_path, project / "work" / "treatments", "treatment plan")
    preview_manifest_path = _confined(
        preview_manifest_path,
        project / "work" / "proxy" / "treatments",
        "preview manifest",
    )
    visual_qa_path = _confined(
        visual_qa_path,
        project / "work" / "qa" / "treatments",
        "visual QA",
    )
    human_review_path = _confined(
        human_review_path,
        project / "work" / "qa" / "treatments",
        "human review",
    )
    plan = _load_json(plan_path, "treatment plan")
    preview = _load_json(preview_manifest_path, "preview manifest")
    visual = _load_json(visual_qa_path, "visual QA")
    human = _load_json(human_review_path, "human review")
    for document, name in (
        (preview, "visual-treatment-preview-manifest.schema.json"),
        (visual, "visual-treatment-visual-qa.schema.json"),
        (human, "visual-treatment-human-review.schema.json"),
    ):
        errors = _schema_errors(document, name)
        if errors:
            raise ValueError("; ".join(errors))
    if visual["status"] != "passed" or visual["blocker_count"] != 0:
        raise ValueError("blocked visual QA cannot be approved")
    plan_sha = _sha256_file(plan_path)
    payload_sha = canonical_treatment_payload_sha256(plan)
    preview_sha = _sha256_file(preview_manifest_path)
    visual_sha = _sha256_file(visual_qa_path)
    base_sha = str(preview["base_media"]["sha256"])
    for document, expected in (
        (
            preview,
            {
                "plan_sha256": plan_sha,
                "treatment_payload_sha256": payload_sha,
            },
        ),
        (
            visual,
            {
                "plan_sha256": plan_sha,
                "treatment_payload_sha256": payload_sha,
                "preview_manifest_sha256": preview_sha,
                "base_media_sha256": base_sha,
            },
        ),
        (
            human,
            {
                "plan_sha256": plan_sha,
                "treatment_payload_sha256": payload_sha,
                "preview_manifest_sha256": preview_sha,
                "visual_qa_sha256": visual_sha,
                "base_media_sha256": base_sha,
            },
        ),
    ):
        for field, value in expected.items():
            if document.get(field) != value:
                raise ValueError(f"visual treatment evidence binding changed: {field}")
    _timestamp(human["reviewed_at"])
    expected_ids = [str(row["proposal_id"]) for row in plan["proposals"]]
    if [str(row["proposal_id"]) for row in preview["previews"]] != expected_ids:
        raise ValueError("preview proposal set or order changed")
    if [str(row["proposal_id"]) for row in visual["proposals"]] != expected_ids:
        raise ValueError("visual QA proposal set or order changed")
    if [str(row["proposal_id"]) for row in human["proposals"]] != expected_ids:
        raise ValueError("human review proposal set or order changed")
    for row in human["proposals"]:
        if set(row["checks"]) != REQUIRED_CHECKS:
            raise ValueError(f"human review checks incomplete: {row['proposal_id']}")
    accepted = [
        str(row["proposal_id"])
        for row in human["proposals"]
        if row["decision"] == "accepted"
    ]
    if not accepted:
        raise ValueError("at least one visual treatment proposal must be accepted")
    return {
        "plan": plan,
        "preview": preview,
        "visual": visual,
        "human": human,
        "plan_sha256": plan_sha,
        "payload_sha256": payload_sha,
        "preview_sha256": preview_sha,
        "visual_sha256": visual_sha,
        "human_sha256": _sha256_file(human_review_path),
        "base_sha256": base_sha,
        "accepted": accepted,
    }


def build_visual_treatment_approval(
    project: Path,
    plan_path: Path,
    preview_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    output_path = _confined(
        output_path,
        project / "work" / "qa" / "treatments",
        "visual treatment approval",
    )
    contract = _collect(
        project,
        plan_path,
        preview_manifest_path,
        visual_qa_path,
        human_review_path,
    )
    core = {
        "schema_version": "1.0",
        "contract_version": "visual-treatment-approval-v1",
        "status": "approved",
        "project_id": contract["plan"]["project_id"],
        "edit_plan_version": contract["plan"]["edit_plan_version"],
        "plan_sha256": contract["plan_sha256"],
        "treatment_payload_sha256": contract["payload_sha256"],
        "preview_manifest_sha256": contract["preview_sha256"],
        "visual_qa_sha256": contract["visual_sha256"],
        "human_review_sha256": contract["human_sha256"],
        "base_media_sha256": contract["base_sha256"],
        "accepted_proposal_ids": contract["accepted"],
        "approved_by": contract["human"]["reviewer"],
        "approved_at": contract["human"]["reviewed_at"],
    }
    approval = {**core, "approval_sha256": _canonical_sha256(core)}
    errors = _schema_errors(approval, "visual-treatment-approval.schema.json")
    if errors:
        raise ValueError("; ".join(errors))
    _write_new(output_path, approval)
    return approval


def validate_visual_treatment_approval(
    project: Path,
    plan_path: Path,
    preview_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approval_path: Path,
) -> dict[str, Any]:
    try:
        project = project.resolve()
        approval_path = _confined(
            approval_path,
            project / "work" / "qa" / "treatments",
            "visual treatment approval",
        )
        approval = _load_json(approval_path, "visual treatment approval")
        errors = _schema_errors(approval, "visual-treatment-approval.schema.json")
        if errors:
            raise ValueError("; ".join(errors))
        contract = _collect(
            project,
            plan_path,
            preview_manifest_path,
            visual_qa_path,
            human_review_path,
        )
        expected = {
            "project_id": contract["plan"]["project_id"],
            "edit_plan_version": contract["plan"]["edit_plan_version"],
            "plan_sha256": contract["plan_sha256"],
            "treatment_payload_sha256": contract["payload_sha256"],
            "preview_manifest_sha256": contract["preview_sha256"],
            "visual_qa_sha256": contract["visual_sha256"],
            "human_review_sha256": contract["human_sha256"],
            "base_media_sha256": contract["base_sha256"],
            "accepted_proposal_ids": contract["accepted"],
            "approved_by": contract["human"]["reviewer"],
            "approved_at": contract["human"]["reviewed_at"],
        }
        for field, value in expected.items():
            if approval.get(field) != value:
                raise ValueError(f"approval binding changed: {field}")
        core = {key: value for key, value in approval.items() if key != "approval_sha256"}
        if approval["approval_sha256"] != _canonical_sha256(core):
            raise ValueError("approval canonical SHA-256 changed")
        return {
            "schema_version": "1.0",
            "status": "passed",
            "blocker_codes": [],
            "accepted_proposal_ids": contract["accepted"],
        }
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "blocker_codes": ["visual_treatment_approval_invalid"],
            "issues": [
                {"code": "visual_treatment_approval_invalid", "message": str(error)}
            ],
        }


def apply_approved_visual_treatments(
    project: Path,
    enhancement_plan_path: Path,
    plan_path: Path,
    preview_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approval_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    enhancement_plan_path = _confined(
        enhancement_plan_path,
        project / "work" / "enhancement",
        "enhancement plan",
    )
    output_path = _confined(
        output_path,
        project / "work" / "enhancement",
        "enhancement output",
    )
    validation = validate_visual_treatment_approval(
        project,
        plan_path,
        preview_manifest_path,
        visual_qa_path,
        human_review_path,
        approval_path,
    )
    if validation["status"] != "passed":
        raise ValueError(json.dumps(validation["issues"], ensure_ascii=False))
    contract = _collect(
        project,
        plan_path,
        preview_manifest_path,
        visual_qa_path,
        human_review_path,
    )
    approval = _load_json(approval_path, "visual treatment approval")
    enhancement = deepcopy(_load_json(enhancement_plan_path, "enhancement plan"))
    if enhancement.get("project_id") != contract["plan"].get("project_id"):
        raise ValueError("enhancement project differs from treatment plan")
    if enhancement.get("edit_plan_version") != contract["plan"].get("edit_plan_version"):
        raise ValueError("enhancement edit version differs from treatment plan")
    treatments = {
        str(row["segment_id"]): row
        for row in enhancement.get("video_treatments", [])
        if isinstance(row, dict)
    }
    proposals = {
        str(row["proposal_id"]): row for row in contract["plan"]["proposals"]
    }
    for proposal_id in contract["accepted"]:
        proposal = proposals[proposal_id]
        segment_id = str(proposal["segment_id"])
        if segment_id not in treatments:
            raise ValueError(f"enhancement is missing treatment for {segment_id}")
        visual = treatments[segment_id].setdefault("visual", {})
        for field, value in proposal["changes"].items():
            visual[field] = deepcopy(value)
    enhancement["version"] = int(enhancement.get("version", 1)) + 1
    enhancement["music"]["status"] = "disabled"
    enhancement["music"]["tracks"] = []
    enhancement["music"]["ducking"]["enabled"] = False
    enhancement["visual_treatment_evidence"] = {
        "contract_version": "visual-treatment-ready-evidence-v1",
        "base_media_sha256": contract["base_sha256"],
        "treatment_payload_sha256": canonical_enhancement_treatments_sha256(
            enhancement["video_treatments"]
        ),
        "plan": _binding(project, plan_path),
        "preview_manifest": _binding(project, preview_manifest_path),
        "visual_qa": _binding(project, visual_qa_path),
        "human_review": _binding(project, human_review_path),
        "approval": _binding(project, approval_path),
        "approval_sha256": approval["approval_sha256"],
        "accepted_proposal_ids": contract["accepted"],
    }
    errors = enhancement_schema_errors(enhancement)
    if errors:
        raise ValueError(
            "; ".join(f"{error.json_path}: {error.message}" for error in errors)
        )
    _write_new(output_path, enhancement)
    return enhancement


__all__ = [
    "apply_approved_visual_treatments",
    "build_visual_treatment_approval",
    "canonical_enhancement_treatments_sha256",
    "validate_visual_treatment_approval",
]
