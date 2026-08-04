from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(name: str) -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("schemas") / name).read_text(encoding="utf-8"))


def build_vlm_request(
    *,
    project_id: str,
    media_path: Path,
    shots: Sequence[Mapping[str, Any]],
    provider_name: str,
    model: str,
    provider_version: str,
    prompt: str,
) -> dict[str, Any]:
    media = media_path.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    request = {
        "schema_version": "1.0",
        "contract_version": "vlm-analysis-request-v1",
        "project_id": project_id,
        "media": {"name": media.name, "sha256": _sha256_file(media), "size_bytes": media.stat().st_size},
        "provider": {"name": provider_name, "model": model, "version": provider_version},
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "shots": [
            {
                "shot_id": str(shot["shot_id"]),
                "start_sec": float(shot["start_sec"]),
                "end_sec": float(shot["end_sec"]),
                "evidence_ids": [str(value) for value in shot.get("evidence_ids", [])],
            }
            for shot in shots
        ],
        "safety": {"may_approve_deletion": False, "may_approve_release": False},
    }
    errors = list(Draft202012Validator(_schema("vlm-analysis-request.schema.json")).iter_errors(request))
    if errors:
        raise ValueError("VLM request schema invalid")
    return request


def validate_vlm_evidence(request: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, Any]:
    errors = list(Draft202012Validator(_schema("vlm-analysis-evidence.schema.json")).iter_errors(evidence))
    issues: list[str] = [f"{error.json_path}: {error.message}" for error in errors]
    if evidence.get("request_sha256") != _canonical_sha256(request):
        issues.append("VLM evidence request SHA-256 changed")
    if evidence.get("media_sha256") != request.get("media", {}).get("sha256"):
        issues.append("VLM evidence media SHA-256 changed")
    if evidence.get("provider") != request.get("provider"):
        issues.append("VLM evidence provider identity changed")
    if evidence.get("prompt_sha256") != request.get("prompt_sha256"):
        issues.append("VLM evidence prompt SHA-256 changed")
    if evidence.get("project_id") != request.get("project_id"):
        issues.append("VLM evidence project ID changed")
    shot_ids = {str(shot.get("shot_id")) for shot in request.get("shots", [])}
    if any(str(event.get("shot_id")) not in shot_ids for event in evidence.get("events", [])):
        issues.append("VLM evidence references an unknown shot")
    return {"status": "passed" if not issues else "blocked", "issues": issues, "event_count": len(evidence.get("events", []))}


def vlm_events_to_candidate_moments(evidence: Mapping[str, Any], *, minimum_confidence: float = 0.75) -> list[dict[str, Any]]:
    """Convert model evidence into candidates only; never locked or approved moments."""
    if evidence.get("status") != "evidence_ready":
        return []
    return [
        {
            "id": f"vlm-{event['evidence_id']}",
            "shot_id": event["shot_id"],
            "keep_level": "candidate",
            "type": event["event_type"],
            "reason": event["description"],
            "confidence": float(event["confidence"]),
            "evidence_ids": [event["evidence_id"]],
        }
        for event in evidence.get("events", [])
        if float(event.get("confidence", 0.0)) >= minimum_confidence
    ]


def canonical_request_sha256(request: Mapping[str, Any]) -> str:
    return _canonical_sha256(request)
