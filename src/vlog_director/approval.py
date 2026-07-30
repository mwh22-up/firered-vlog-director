from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
