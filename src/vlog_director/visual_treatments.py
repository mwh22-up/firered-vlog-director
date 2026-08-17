from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .timeline import flatten_edit_plan


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _contains_non_finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_non_finite(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_non_finite(item) for item in value)
    return False


@lru_cache(maxsize=2)
def _validator(schema_name: str) -> Draft202012Validator:
    path = files("vlog_director.schemas").joinpath(schema_name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_errors(document: Mapping[str, Any], schema_name: str) -> list[str]:
    errors = sorted(
        _validator(schema_name).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


@dataclass(frozen=True)
class VisualTreatmentPolicy:
    policy_version: str = "visual-treatment-policy-v1"
    luma_target: float = 0.50
    luma_dark_threshold: float = 0.42
    luma_bright_threshold: float = 0.60
    contrast_low_threshold: float = 0.15
    saturation_low_threshold: float = 0.14
    saturation_high_threshold: float = 0.68
    max_brightness_adjustment: float = 0.12
    allow_auto_denoise: bool = True
    allow_auto_sharpen: bool = True
    allow_auto_reframe: bool = False

    def __post_init__(self) -> None:
        if self.policy_version != "visual-treatment-policy-v1":
            raise ValueError("unsupported visual treatment policy version")
        for field_name in (
            "luma_target",
            "luma_dark_threshold",
            "luma_bright_threshold",
            "contrast_low_threshold",
            "saturation_low_threshold",
            "saturation_high_threshold",
            "max_brightness_adjustment",
        ):
            value = getattr(self, field_name)
            if not _is_number(value) or not 0 <= float(value) <= 1:
                raise ValueError(f"{field_name} must be a finite number between 0 and 1")
        if self.max_brightness_adjustment > 0.25:
            raise ValueError("max_brightness_adjustment exceeds renderer range")
        if self.luma_dark_threshold >= self.luma_bright_threshold:
            raise ValueError("dark threshold must be below bright threshold")
        if self.saturation_low_threshold >= self.saturation_high_threshold:
            raise ValueError("low saturation threshold must be below high threshold")
        for field_name in (
            "allow_auto_denoise",
            "allow_auto_sharpen",
            "allow_auto_reframe",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be boolean")
        if self.allow_auto_reframe:
            raise ValueError("automatic reframe is disabled until protected regions are measured")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_visual_treatment_analysis(
    edit_plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    schema_errors = _schema_errors(analysis, "visual-treatment-analysis.schema.json")
    if schema_errors or _contains_non_finite(analysis):
        detail = schema_errors or ["non-finite numeric value"]
        issues.append(
            {
                "code": "visual_analysis_schema_invalid",
                "message": "; ".join(detail),
            }
        )
    expected_sha = _canonical_sha256(edit_plan)
    if analysis.get("project_id") != edit_plan.get("project_id"):
        issues.append(
            {
                "code": "visual_analysis_project_mismatch",
                "message": "analysis project does not match edit plan",
            }
        )
    if analysis.get("edit_plan_version") != edit_plan.get("version"):
        issues.append(
            {
                "code": "visual_analysis_version_mismatch",
                "message": "analysis edit plan version changed",
            }
        )
    if analysis.get("edit_plan_sha256") != expected_sha:
        issues.append(
            {
                "code": "visual_analysis_edit_sha_mismatch",
                "message": "analysis edit plan SHA-256 changed",
            }
        )
    timeline_ids = [str(row["segment_id"]) for row in flatten_edit_plan(dict(edit_plan))]
    rows = analysis.get("segments")
    analysis_ids = (
        [str(row.get("segment_id")) for row in rows if isinstance(row, Mapping)]
        if isinstance(rows, list)
        else []
    )
    if len(analysis_ids) != len(set(analysis_ids)) or set(analysis_ids) != set(timeline_ids):
        issues.append(
            {
                "code": "visual_analysis_segment_set_mismatch",
                "message": "analysis must cover every edit segment exactly once",
            }
        )
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            start = row.get("start_sec")
            end = row.get("end_sec")
            samples = row.get("sample_times_sec")
            if (
                _is_number(start)
                and _is_number(end)
                and isinstance(samples, list)
                and any(
                    not _is_number(value)
                    or float(value) < float(start)
                    or float(value) > float(end)
                    for value in samples
                )
            ):
                issues.append(
                    {
                        "code": "visual_analysis_sample_out_of_segment",
                        "message": f"sample escaped segment {row.get('segment_id')}",
                    }
                )
    return {
        "schema_version": "1.0",
        "status": "blocked" if issues else "passed",
        "blocker_codes": list(dict.fromkeys(row["code"] for row in issues)),
        "issues": issues,
    }


def _proposal_changes(
    metrics: Mapping[str, Any],
    policy: VisualTreatmentPolicy,
) -> tuple[dict[str, Any], list[str], float, str]:
    changes: dict[str, Any] = {}
    reasons: list[str] = []
    luma = float(metrics["luma_mean"])
    if luma < policy.luma_dark_threshold and float(metrics["clipped_white_ratio"]) < 0.02:
        adjustment = min(policy.max_brightness_adjustment, (policy.luma_target - luma) * 0.45)
        changes["brightness"] = round(adjustment, 4)
        reasons.append("underexposed_relative_to_policy")
    elif luma > policy.luma_bright_threshold and float(metrics["clipped_black_ratio"]) < 0.02:
        adjustment = min(policy.max_brightness_adjustment, (luma - policy.luma_target) * 0.35)
        changes["brightness"] = round(-adjustment, 4)
        reasons.append("overbright_relative_to_policy")

    contrast = float(metrics["contrast_std"])
    if contrast < policy.contrast_low_threshold:
        changes["contrast"] = round(min(1.22, 1.0 + (policy.contrast_low_threshold - contrast) * 1.5), 4)
        reasons.append("low_contrast")

    saturation = float(metrics["saturation_mean"])
    if saturation < policy.saturation_low_threshold:
        changes["saturation"] = round(min(1.20, 1.0 + (policy.saturation_low_threshold - saturation)), 4)
        reasons.append("low_saturation")
    elif saturation > policy.saturation_high_threshold:
        changes["saturation"] = 0.90
        reasons.append("excessive_saturation")

    motion = float(metrics["motion"])
    noise = float(metrics["temporal_noise"])
    sharpness = float(metrics["sharpness"])
    if policy.allow_auto_denoise and noise > 0.075 and motion < 0.06:
        changes["denoise"] = {
            "mode": "hqdn3d",
            "luma_spatial": 1.8,
            "chroma_spatial": 1.2,
            "luma_temporal": 2.4,
            "chroma_temporal": 1.8,
        }
        reasons.append("measured_static_noise")
    if policy.allow_auto_sharpen and sharpness < 0.045 and motion < 0.05 and noise < 0.06:
        changes["sharpen"] = {"mode": "unsharp", "amount": 0.28}
        reasons.append("low_detail_low_motion")

    confidence = 0.78 if reasons else 0.0
    risk = "medium" if changes else "low"
    if (
        float(metrics["clipped_black_ratio"]) > 0.04
        or float(metrics["clipped_white_ratio"]) > 0.02
    ):
        risk = "high"
        confidence = min(confidence, 0.62)
        reasons.append("existing_luma_clipping")
    return changes, list(dict.fromkeys(reasons)), round(confidence, 4), risk


def canonical_treatment_payload_sha256(plan: Mapping[str, Any]) -> str:
    payload = {
        "project_id": plan.get("project_id"),
        "edit_plan_version": plan.get("edit_plan_version"),
        "edit_plan_sha256": plan.get("edit_plan_sha256"),
        "realized_timeline_sha256": plan.get("realized_timeline_sha256"),
        "base_media_sha256": plan.get("base_media_sha256"),
        "analysis": plan.get("analysis"),
        "policy": plan.get("policy"),
        "proposals": plan.get("proposals"),
    }
    return _canonical_sha256(payload)


def build_visual_treatment_plan(
    edit_plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    *,
    analysis_path: str,
    analysis_sha256: str,
    policy: VisualTreatmentPolicy | None = None,
) -> dict[str, Any]:
    validation = validate_visual_treatment_analysis(edit_plan, analysis)
    if validation["status"] != "passed":
        raise ValueError(json.dumps(validation["issues"], ensure_ascii=False))
    if not isinstance(analysis_sha256, str) or len(analysis_sha256) != 64:
        raise ValueError("analysis SHA-256 is invalid")
    active_policy = policy or VisualTreatmentPolicy()
    by_segment = {str(row["segment_id"]): row for row in analysis["segments"]}
    proposals: list[dict[str, Any]] = []
    for timeline_row in flatten_edit_plan(dict(edit_plan)):
        segment_id = str(timeline_row["segment_id"])
        row = by_segment[segment_id]
        changes, reasons, confidence, risk = _proposal_changes(row["metrics"], active_policy)
        if not changes:
            continue
        proposal_seed = {
            "segment_id": segment_id,
            "changes": changes,
            "metrics": row["metrics"],
            "policy_version": active_policy.policy_version,
        }
        proposals.append(
            {
                "proposal_id": f"vt-{_canonical_sha256(proposal_seed)[:16]}",
                "segment_id": segment_id,
                "evidence_ids": [
                    f"visual-analysis:{segment_id}:metrics",
                    f"realized-timeline:{segment_id}",
                ],
                "confidence": confidence,
                "risk": risk,
                "reason_codes": reasons,
                "changes": changes,
                "status": "review_required",
                "review_required": True,
            }
        )
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "contract_version": "visual-treatment-plan-v1",
        "project_id": str(edit_plan["project_id"]),
        "edit_plan_version": int(edit_plan["version"]),
        "edit_plan_sha256": _canonical_sha256(edit_plan),
        "realized_timeline_sha256": str(analysis["realized_timeline_sha256"]),
        "base_media_sha256": str(analysis["base_media"]["sha256"]),
        "analysis": {"path": analysis_path, "sha256": analysis_sha256},
        "policy": active_policy.to_dict(),
        "proposals": proposals,
    }
    plan["treatment_payload_sha256"] = canonical_treatment_payload_sha256(plan)
    schema_errors = _schema_errors(plan, "visual-treatment-plan.schema.json")
    if schema_errors:
        raise ValueError("; ".join(schema_errors))
    return plan


def validate_visual_treatment_plan(
    edit_plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    schema_errors = _schema_errors(plan, "visual-treatment-plan.schema.json")
    if schema_errors or _contains_non_finite(plan):
        issues.append(
            {
                "code": "visual_plan_schema_invalid",
                "message": "; ".join(schema_errors or ["non-finite numeric value"]),
            }
        )
    expected_edit_sha = _canonical_sha256(edit_plan)
    if plan.get("edit_plan_sha256") != expected_edit_sha:
        issues.append(
            {
                "code": "visual_plan_edit_sha_mismatch",
                "message": "visual treatment plan edit SHA-256 changed",
            }
        )
    if plan.get("project_id") != edit_plan.get("project_id"):
        issues.append({"code": "visual_plan_project_mismatch", "message": "project changed"})
    if plan.get("base_media_sha256") != analysis.get("base_media", {}).get("sha256"):
        issues.append(
            {
                "code": "visual_plan_base_media_mismatch",
                "message": "base media identity changed",
            }
        )
    if plan.get("realized_timeline_sha256") != analysis.get("realized_timeline_sha256"):
        issues.append(
            {
                "code": "visual_plan_timeline_mismatch",
                "message": "realized timeline identity changed",
            }
        )
    if plan.get("treatment_payload_sha256") != canonical_treatment_payload_sha256(plan):
        issues.append(
            {
                "code": "visual_plan_payload_sha_mismatch",
                "message": "visual treatment payload changed",
            }
        )
    segment_ids = {str(row["segment_id"]) for row in flatten_edit_plan(dict(edit_plan))}
    proposal_ids: list[str] = []
    for row in plan.get("proposals", []):
        if not isinstance(row, Mapping):
            continue
        proposal_ids.append(str(row.get("proposal_id")))
        if str(row.get("segment_id")) not in segment_ids:
            issues.append(
                {
                    "code": "visual_plan_unknown_segment",
                    "message": f"unknown segment: {row.get('segment_id')}",
                }
            )
        forbidden = set(row.get("changes", {})) & {"speed", "reframe", "stabilization", "continuity"}
        if forbidden:
            issues.append(
                {
                    "code": "visual_plan_unsupported_change",
                    "message": "unsupported changes: " + ", ".join(sorted(forbidden)),
                }
            )
    if len(proposal_ids) != len(set(proposal_ids)):
        issues.append(
            {"code": "visual_plan_duplicate_proposal", "message": "proposal IDs must be unique"}
        )
    return {
        "schema_version": "1.0",
        "status": "blocked" if issues else "passed",
        "blocker_codes": list(dict.fromkeys(row["code"] for row in issues)),
        "issues": issues,
    }


__all__ = [
    "VisualTreatmentPolicy",
    "build_visual_treatment_plan",
    "canonical_treatment_payload_sha256",
    "validate_visual_treatment_analysis",
    "validate_visual_treatment_plan",
]
