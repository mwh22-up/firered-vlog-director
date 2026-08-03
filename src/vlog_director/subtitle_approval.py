from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .subtitle_readability import (
    canonical_subtitle_payload_digest,
    canonical_subtitle_style_digest,
    canonical_verified_cue_set_digest,
)


APPROVAL_SCHEMA_VERSION = "1.0"
APPROVAL_VERSION = "subtitle-approval-v1"
SHA256_LENGTH = 64
HUMAN_CHECKS = frozenset(
    {
        "audio_text_accuracy",
        "timing_and_cut_boundaries",
        "readability",
        "layout_and_safe_area",
        "visual_evidence_review",
    }
)
READY_APPROVAL_FIELDS = frozenset(
    {
        "status",
        "approval_sha256",
        "review_source_sha256",
        "subtitle_payload_sha256",
        "subtitle_style_sha256",
        "verified_cue_set_sha256",
        "readability_qa_sha256",
        "layout_qa_sha256",
        "visual_qa_sha256",
        "human_review_sha256",
        "approved_by",
        "approved_at",
    }
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    payload = resolved.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without a BOM")
    try:
        text = payload.decode("utf-8")
        document = json.loads(text, parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("approval binding value is not canonical JSON") from error
    return hashlib.sha256(payload).hexdigest()


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    output = Path(path).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    output.write_text(payload, encoding="utf-8", newline="\n")


@lru_cache(maxsize=6)
def _runtime_validator(schema_name: str) -> Draft202012Validator:
    schema_path = files("vlog_director.schemas").joinpath(schema_name)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_issues(document: Mapping[str, Any], schema_name: str) -> list[str]:
    errors = sorted(
        _runtime_validator(schema_name).iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric and not bool")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _aware_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty timestamp")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _source_cues(source: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    raw_cues = source.get("cues")
    if not isinstance(raw_cues, list) or not raw_cues:
        raise ValueError("subtitle source must contain at least one verified cue")
    cues: list[dict[str, Any]] = []
    cue_ids: list[str] = []
    for raw in raw_cues:
        if not isinstance(raw, dict):
            raise ValueError("subtitle source cues must be objects")
        cue_id = raw.get("cue_id")
        if not isinstance(cue_id, str) or not cue_id.strip():
            raise ValueError("subtitle source cues require stable cue_id values")
        if cue_id in cue_ids:
            raise ValueError(f"duplicate subtitle cue_id: {cue_id}")
        if raw.get("review_status") != "verified":
            raise ValueError(f"subtitle cue is not verified: {cue_id}")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"subtitle cue text is empty: {cue_id}")
        start = _finite_number(raw.get("start_sec"), f"{cue_id}.start_sec")
        end = _finite_number(raw.get("end_sec"), f"{cue_id}.end_sec")
        if start < 0 or end <= start:
            raise ValueError(f"subtitle cue timing is invalid: {cue_id}")
        position = raw.get("position")
        if position is not None and position not in {"top_center", "bottom_center"}:
            raise ValueError(f"subtitle cue position is invalid: {cue_id}")
        cues.append(raw)
        cue_ids.append(cue_id)
    return cues, cue_ids


def _source_contract(
    source_path: Path,
    plan_style: Mapping[str, Any],
    *,
    approval_sha256: str | None = None,
) -> dict[str, Any]:
    source = _load_json(source_path, "subtitle source")
    project_id = source.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("subtitle source requires project_id")
    if source.get("coverage", {}).get("status") != "verified":
        raise ValueError("subtitle source coverage must be verified")
    cues, cue_ids = _source_cues(source)
    source_file_sha256 = _sha256_file(source_path)
    status = source.get("status")
    if status == "ready":
        envelope = source.get("approval")
        if not isinstance(envelope, dict):
            raise ValueError("ready subtitle source requires approval binding")
        unknown = sorted(set(envelope) - READY_APPROVAL_FIELDS)
        missing = sorted(READY_APPROVAL_FIELDS - set(envelope))
        if unknown or missing:
            raise ValueError(
                "ready subtitle approval binding fields are invalid: "
                f"unknown={unknown}, missing={missing}"
            )
        if approval_sha256 is not None and envelope.get("approval_sha256") != approval_sha256:
            raise ValueError("ready subtitle source approval SHA-256 changed")
        contract_source_sha256 = envelope.get("review_source_sha256")
        if not _is_sha256(contract_source_sha256):
            raise ValueError("ready subtitle source review SHA-256 is invalid")
    elif status in {"review", "review_required"}:
        envelope = None
        contract_source_sha256 = source_file_sha256
    else:
        raise ValueError("subtitle source status must be review_required, review, or ready")
    if not isinstance(plan_style, Mapping):
        raise ValueError("subtitle plan style must be an object")
    style = dict(plan_style)
    json.dumps(style, allow_nan=False)
    return {
        "document": source,
        "status": status,
        "project_id": project_id,
        "cues": cues,
        "cue_ids": cue_ids,
        "source_file_sha256": source_file_sha256,
        "contract_source_sha256": contract_source_sha256,
        "payload_sha256": canonical_subtitle_payload_digest(source),
        "style_sha256": canonical_subtitle_style_digest(style),
        "verified_cue_set_sha256": canonical_verified_cue_set_digest(cues),
        "style": style,
        "approval_envelope": envelope,
    }


def _layout_style_sha256(style: Mapping[str, Any], cue: Mapping[str, Any]) -> str:
    effective = dict(style)
    effective["position"] = cue.get("position", style.get("position", "bottom_center"))
    return _canonical_sha256(effective)


def _same_cue_set(actual: Any, expected: list[str]) -> bool:
    return (
        isinstance(actual, list)
        and all(isinstance(item, str) and item for item in actual)
        and len(actual) == len(expected)
        and set(actual) == set(expected)
    )


def _collect_contract(
    *,
    subtitle_source_path: Path,
    plan_style: Mapping[str, Any],
    readability_qa_path: Path,
    layout_qa_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approved_by: str,
    approval_sha256: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    try:
        source = _source_contract(
            subtitle_source_path,
            plan_style,
            approval_sha256=approval_sha256,
        )
    except (OSError, ValueError) as error:
        return {}, [str(error)]

    try:
        readability = _load_json(readability_qa_path, "readability QA")
        layout = _load_json(layout_qa_path, "layout QA")
        visual = _load_json(visual_qa_path, "visual QA")
        human = _load_json(human_review_path, "human review")
    except (OSError, ValueError) as error:
        return source, [str(error)]

    readability_schema_issues = _schema_issues(
        readability,
        "subtitle-readability-qa.schema.json",
    )
    if readability_schema_issues:
        issues.append(
            "readability QA schema invalid: " + "; ".join(readability_schema_issues)
        )
    layout_schema_issues = _schema_issues(
        layout,
        "subtitle-layout-qa.schema.json",
    )
    if layout_schema_issues:
        issues.append("layout QA schema invalid: " + "; ".join(layout_schema_issues))
    visual_schema_issues = _schema_issues(
        visual,
        "subtitle-visual-qa.schema.json",
    )
    if visual_schema_issues:
        issues.append("visual QA schema invalid: " + "; ".join(visual_schema_issues))
    human_schema_issues = _schema_issues(
        human,
        "subtitle-human-review.schema.json",
    )
    if human_schema_issues:
        issues.append("human review schema invalid: " + "; ".join(human_schema_issues))

    source_sha = source["contract_source_sha256"]
    cue_ids = source["cue_ids"]
    project_id = source["project_id"]
    readability_sha = _sha256_file(readability_qa_path)
    layout_sha = _sha256_file(layout_qa_path)
    visual_sha = _sha256_file(visual_qa_path)
    human_sha = _sha256_file(human_review_path)

    if readability.get("project_id") != project_id:
        issues.append("readability QA project_id does not match subtitle source")
    if readability.get("mode") != "release":
        issues.append("readability QA must use release mode")
    if readability.get("status") != "passed" or readability.get("release_ready") is not True:
        issues.append("readability release QA must be passed and release_ready")
    if readability.get("blocker_count") != 0:
        issues.append("readability release QA retains blockers")
    if readability.get("subtitle_source_sha256") != source_sha:
        issues.append("readability QA subtitle source SHA-256 mismatch")
    if readability.get("subtitle_payload_sha256") != source["payload_sha256"]:
        issues.append("readability QA subtitle payload SHA-256 mismatch")
    if not _same_cue_set(readability.get("cue_ids"), cue_ids):
        issues.append("readability QA cue set does not match subtitle source")
    realized_timeline_sha = readability.get("realized_timeline_sha256")
    if not _is_sha256(realized_timeline_sha):
        issues.append("readability QA realized timeline SHA-256 is invalid")
    policy_version = readability.get("policy_version")
    if not isinstance(policy_version, str) or not policy_version:
        issues.append("readability QA policy version is invalid")

    layout_bindings = layout.get("bindings")
    layout_bindings = layout_bindings if isinstance(layout_bindings, dict) else {}
    if layout.get("project_id") != project_id:
        issues.append("layout QA project_id does not match subtitle source")
    if layout.get("status") != "passed" or layout.get("mode") != "release":
        issues.append("layout release QA must be passed in release mode")
    if layout.get("probe_mode") != "real_libass":
        issues.append("layout release QA must use real libass measurement")
    if layout.get("blocker_codes") not in ([], tuple()):
        issues.append("layout release QA retains blockers")
    if layout_bindings.get("subtitle_source_sha256") != source_sha:
        issues.append("layout QA subtitle source SHA-256 mismatch")
    if layout_bindings.get("realized_timeline_sha256") != realized_timeline_sha:
        issues.append("layout QA realized timeline SHA-256 mismatch")
    if layout_bindings.get("readability_qa_sha256") != readability_sha:
        issues.append("layout QA readability QA SHA-256 mismatch")
    if layout_bindings.get("readability_policy_sha256") != readability.get(
        "policy_sha256"
    ):
        issues.append("layout QA readability policy SHA-256 mismatch")
    if layout_bindings.get("readability_policy_version") != policy_version:
        issues.append("layout QA readability policy version mismatch")
    layout_summary = layout.get("summary")
    layout_summary = layout_summary if isinstance(layout_summary, dict) else {}
    if layout_summary.get("cue_count") != len(cue_ids):
        issues.append("layout QA cue count does not match subtitle source")
    if layout_summary.get("real_layout_verified_count") != len(cue_ids):
        issues.append("layout QA does not verify every subtitle cue")
    layout_cues = layout.get("cues")
    if not isinstance(layout_cues, list) or not _same_cue_set(
        [item.get("cue_id") for item in layout_cues if isinstance(item, dict)],
        cue_ids,
    ):
        issues.append("layout QA cue set does not match subtitle source")
    else:
        source_by_id = {cue["cue_id"]: cue for cue in source["cues"]}
        for item in layout_cues:
            cue_id = item["cue_id"]
            cue = source_by_id[cue_id]
            expected_text_sha = hashlib.sha256(
                str(cue["text"]).encode("utf-8")
            ).hexdigest()
            if item.get("text_sha256") != expected_text_sha:
                issues.append(f"layout QA text SHA-256 mismatch: {cue_id}")
            if item.get("style_sha256") != _layout_style_sha256(source["style"], cue):
                issues.append(f"layout QA style SHA-256 mismatch: {cue_id}")
            if item.get("position") != cue.get(
                "position", source["style"].get("position", "bottom_center")
            ):
                issues.append(f"layout QA position mismatch: {cue_id}")
            if (
                item.get("real_layout_verified") is not True
                or item.get("inside_safe_area") is not True
                or item.get("clipped") is not False
                or item.get("blocker_codes") not in ([], tuple())
            ):
                issues.append(f"layout QA cue is not release safe: {cue_id}")

    visual_bindings = visual.get("bindings")
    visual_bindings = visual_bindings if isinstance(visual_bindings, dict) else {}
    machine_passed = visual.get("machine_status") == "passed"
    if visual.get("project_id") != project_id:
        issues.append("visual QA project_id does not match subtitle source")
    if visual.get("status") != "review_required" or not machine_passed:
        issues.append("visual QA machine evidence must pass while human review remains required")
    if visual.get("scope") != "all":
        issues.append("visual QA must cover scope=all")
    if visual.get("release_ready") is not False:
        issues.append("visual QA must not fabricate release approval")
    if visual.get("human_review", {}).get("status") != "pending":
        issues.append("visual QA human review status must remain pending")
    if visual.get("blockers") not in ([], tuple()):
        issues.append("visual QA retains machine blockers")
    if visual.get("missing_cue_ids") not in ([], tuple()):
        issues.append("visual QA has missing subtitle cues")
    if visual.get("unrendered_due_to_scope_cue_ids") not in ([], tuple()):
        issues.append("all-scope visual QA left cues unrendered")
    if visual.get("cue_count") != len(cue_ids):
        issues.append("visual QA cue count does not match subtitle source")
    if visual.get("actual_rendered_cue_count") != len(cue_ids):
        issues.append("visual QA did not render every subtitle cue")
    if not _same_cue_set(visual.get("cue_ids"), cue_ids):
        issues.append("visual QA cue set does not match subtitle source")
    if not _same_cue_set(visual.get("rendered_cue_ids"), cue_ids):
        issues.append("visual QA rendered cue set does not match subtitle source")
    if visual_bindings.get("subtitle_source_sha256") != source_sha:
        issues.append("visual QA subtitle source SHA-256 mismatch")
    if visual_bindings.get("realized_timeline_sha256") != realized_timeline_sha:
        issues.append("visual QA realized timeline SHA-256 mismatch")
    if visual_bindings.get("readability_policy_version") != policy_version:
        issues.append("visual QA readability policy version mismatch")
    layout_probe_version = layout.get("probe_version")
    if visual_bindings.get("layout_probe_version") != layout_probe_version:
        issues.append("visual QA layout probe version mismatch")
    visual_qa_version = visual.get("qa_version")
    if not isinstance(visual_qa_version, str) or not visual_qa_version:
        issues.append("visual QA version is invalid")

    expected_human = {
        "project_id": project_id,
        "subtitle_source_sha256": source_sha,
        "subtitle_payload_sha256": source["payload_sha256"],
        "subtitle_style_sha256": source["style_sha256"],
        "verified_cue_set_sha256": source["verified_cue_set_sha256"],
        "readability_qa_sha256": readability_sha,
        "layout_qa_sha256": layout_sha,
        "visual_qa_sha256": visual_sha,
    }
    if human.get("status") != "approved":
        issues.append("human review status is not approved")
    checks = human.get("checks")
    if not isinstance(checks, dict) or set(checks) != HUMAN_CHECKS or any(
        value != "approved" for value in checks.values()
    ):
        issues.append("human review checks are not all approved")
    for field, expected in expected_human.items():
        if human.get(field) != expected:
            issues.append(f"human review {field} mismatch")
    if not _same_cue_set(human.get("cue_ids"), cue_ids):
        issues.append("human review cue set does not match subtitle source")
    reviewer = str(approved_by).strip()
    if not reviewer:
        issues.append("approved_by is required")
    elif human.get("approved_by") != reviewer:
        issues.append("human review approved_by does not match requested approver")
    try:
        human_approved_at = _aware_datetime(human.get("approved_at"), "human review approved_at")
    except ValueError as error:
        issues.append(str(error))
        human_approved_at_value = ""
    else:
        human_approved_at_value = human["approved_at"]

    expected = {
        **source,
        "readability": readability,
        "layout": layout,
        "visual": visual,
        "human": human,
        "readability_qa_sha256": readability_sha,
        "layout_qa_sha256": layout_sha,
        "visual_qa_sha256": visual_sha,
        "human_review_sha256": human_sha,
        "realized_timeline_sha256": realized_timeline_sha,
        "readability_policy_version": policy_version,
        "layout_probe_version": layout_probe_version,
        "visual_qa_version": visual_qa_version,
        "human_review_approved_at": human_approved_at_value,
        "approved_by": reviewer,
    }
    return expected, issues


def build_subtitle_approval(
    review_source_path: Path,
    plan_style: Mapping[str, Any],
    readability_qa_path: Path,
    layout_qa_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approved_by: str,
    output_path: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build an approval only from an independently authored human review record."""

    expected, issues = _collect_contract(
        subtitle_source_path=review_source_path,
        plan_style=plan_style,
        readability_qa_path=readability_qa_path,
        layout_qa_path=layout_qa_path,
        visual_qa_path=visual_qa_path,
        human_review_path=human_review_path,
        approved_by=approved_by,
    )
    if expected.get("status") == "ready":
        issues.append("a new approval must be built from the review source, not a ready envelope")
    approved_at = created_at or datetime.now(UTC).isoformat()
    try:
        approval_time = _aware_datetime(approved_at, "approval approved_at")
        human_time = _aware_datetime(
            expected.get("human_review_approved_at"),
            "human review approved_at",
        )
    except ValueError as error:
        issues.append(str(error))
    else:
        if approval_time < human_time:
            issues.append("approval timestamp cannot precede the human review")
    if issues:
        raise ValueError("subtitle approval blocked: " + "; ".join(issues))

    approval = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "document_type": "subtitle_approval",
        "approval_version": APPROVAL_VERSION,
        "status": "approved",
        "project_id": expected["project_id"],
        "review_source_sha256": expected["contract_source_sha256"],
        "subtitle_payload_sha256": expected["payload_sha256"],
        "subtitle_style_sha256": expected["style_sha256"],
        "verified_cue_set_sha256": expected["verified_cue_set_sha256"],
        "readability_qa_sha256": expected["readability_qa_sha256"],
        "layout_qa_sha256": expected["layout_qa_sha256"],
        "visual_qa_sha256": expected["visual_qa_sha256"],
        "human_review_sha256": expected["human_review_sha256"],
        "realized_timeline_sha256": expected["realized_timeline_sha256"],
        "readability_policy_version": expected["readability_policy_version"],
        "layout_probe_version": expected["layout_probe_version"],
        "visual_qa_version": expected["visual_qa_version"],
        "cue_ids": list(expected["cue_ids"]),
        "approved_by": expected["approved_by"],
        "approved_at": approved_at,
        "human_review_approved_at": expected["human_review_approved_at"],
    }
    schema_issues = _schema_issues(approval, "subtitle-approval.schema.json")
    if schema_issues:
        raise ValueError("subtitle approval schema invalid: " + "; ".join(schema_issues))
    if output_path is not None:
        _write_new_json(output_path, approval)
    return approval


def validate_subtitle_approval(
    subtitle_source_path: Path,
    plan_style: Mapping[str, Any],
    readability_qa_path: Path,
    layout_qa_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approval_path: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    try:
        approval = _load_json(approval_path, "subtitle approval")
        approval_sha = _sha256_file(approval_path)
    except (OSError, ValueError) as error:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "blocking_count": 1,
            "issues": [str(error)],
        }
    schema_issues = _schema_issues(approval, "subtitle-approval.schema.json")
    issues.extend("approval schema invalid: " + value for value in schema_issues)
    approver = approval.get("approved_by")
    expected, contract_issues = _collect_contract(
        subtitle_source_path=subtitle_source_path,
        plan_style=plan_style,
        readability_qa_path=readability_qa_path,
        layout_qa_path=layout_qa_path,
        visual_qa_path=visual_qa_path,
        human_review_path=human_review_path,
        approved_by=str(approver or ""),
        approval_sha256=approval_sha,
    )
    issues.extend(contract_issues)
    comparisons = {
        "project_id": expected.get("project_id"),
        "review_source_sha256": expected.get("contract_source_sha256"),
        "subtitle_payload_sha256": expected.get("payload_sha256"),
        "subtitle_style_sha256": expected.get("style_sha256"),
        "verified_cue_set_sha256": expected.get("verified_cue_set_sha256"),
        "readability_qa_sha256": expected.get("readability_qa_sha256"),
        "layout_qa_sha256": expected.get("layout_qa_sha256"),
        "visual_qa_sha256": expected.get("visual_qa_sha256"),
        "human_review_sha256": expected.get("human_review_sha256"),
        "realized_timeline_sha256": expected.get("realized_timeline_sha256"),
        "readability_policy_version": expected.get("readability_policy_version"),
        "layout_probe_version": expected.get("layout_probe_version"),
        "visual_qa_version": expected.get("visual_qa_version"),
        "human_review_approved_at": expected.get("human_review_approved_at"),
    }
    for field, expected_value in comparisons.items():
        if approval.get(field) != expected_value:
            issues.append(f"approval {field} mismatch")
    if not _same_cue_set(approval.get("cue_ids"), expected.get("cue_ids", [])):
        issues.append("approval cue set does not match verified subtitle cues")
    envelope = expected.get("approval_envelope")
    if isinstance(envelope, dict):
        envelope_expected = {
            "status": "approved",
            "approval_sha256": approval_sha,
            "review_source_sha256": approval.get("review_source_sha256"),
            "subtitle_payload_sha256": approval.get("subtitle_payload_sha256"),
            "subtitle_style_sha256": approval.get("subtitle_style_sha256"),
            "verified_cue_set_sha256": approval.get("verified_cue_set_sha256"),
            "readability_qa_sha256": approval.get("readability_qa_sha256"),
            "layout_qa_sha256": approval.get("layout_qa_sha256"),
            "visual_qa_sha256": approval.get("visual_qa_sha256"),
            "human_review_sha256": approval.get("human_review_sha256"),
            "approved_by": approval.get("approved_by"),
            "approved_at": approval.get("approved_at"),
        }
        if envelope != envelope_expected:
            issues.append("ready subtitle approval envelope does not match approval")
    return {
        "schema_version": "1.0",
        "status": "blocked" if issues else "passed",
        "blocking_count": len(issues),
        "issues": issues,
        "approval_sha256": approval_sha,
        "subtitle_payload_sha256": expected.get("payload_sha256"),
        "subtitle_style_sha256": expected.get("style_sha256"),
        "verified_cue_set_sha256": expected.get("verified_cue_set_sha256"),
    }


def create_ready_subtitle_source(
    review_source_path: Path,
    approval_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    review_path = Path(review_source_path).resolve()
    approval_resolved = Path(approval_path).resolve()
    output_resolved = Path(output_path).resolve()
    if output_resolved in {review_path, approval_resolved}:
        raise ValueError("ready subtitle output must not overwrite approval inputs")
    source = _load_json(review_path, "subtitle review source")
    approval = _load_json(approval_resolved, "subtitle approval")
    schema_issues = _schema_issues(approval, "subtitle-approval.schema.json")
    if schema_issues:
        raise ValueError("subtitle approval schema invalid: " + "; ".join(schema_issues))
    if source.get("status") not in {"review", "review_required"}:
        raise ValueError("ready subtitle source can only be created from a review source")
    if source.get("coverage", {}).get("status") != "verified":
        raise ValueError("subtitle review source coverage must be verified")
    cues, cue_ids = _source_cues(source)
    comparisons = {
        "project_id": source.get("project_id"),
        "review_source_sha256": _sha256_file(review_path),
        "subtitle_payload_sha256": canonical_subtitle_payload_digest(source),
        "verified_cue_set_sha256": canonical_verified_cue_set_digest(cues),
    }
    for field, expected in comparisons.items():
        if approval.get(field) != expected:
            raise ValueError(f"subtitle approval {field} does not match review source")
    if not _same_cue_set(approval.get("cue_ids"), cue_ids):
        raise ValueError("subtitle approval cue set does not match review source")
    approval_sha = _sha256_file(approval_resolved)
    ready = deepcopy(source)
    ready["document_type"] = "subtitle_ready_source"
    ready["status"] = "ready"
    ready["coverage"] = {**ready.get("coverage", {}), "status": "verified"}
    ready["approval"] = {
        "status": "approved",
        "approval_sha256": approval_sha,
        "review_source_sha256": approval["review_source_sha256"],
        "subtitle_payload_sha256": approval["subtitle_payload_sha256"],
        "subtitle_style_sha256": approval["subtitle_style_sha256"],
        "verified_cue_set_sha256": approval["verified_cue_set_sha256"],
        "readability_qa_sha256": approval["readability_qa_sha256"],
        "layout_qa_sha256": approval["layout_qa_sha256"],
        "visual_qa_sha256": approval["visual_qa_sha256"],
        "human_review_sha256": approval["human_review_sha256"],
        "approved_by": approval["approved_by"],
        "approved_at": approval["approved_at"],
    }
    _write_new_json(output_resolved, ready)
    return ready


__all__ = [
    "APPROVAL_SCHEMA_VERSION",
    "APPROVAL_VERSION",
    "build_subtitle_approval",
    "create_ready_subtitle_source",
    "validate_subtitle_approval",
]
