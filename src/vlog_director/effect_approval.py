from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .effect_plan import canonical_effect_payload_sha256, validate_effect_plan
from .schema_validation import enhancement_schema_errors


REQUIRED_HUMAN_CHECKS = {"timing", "safe_zones", "visual_fit", "intensity"}


class EffectContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise EffectContractError("effect_artifact_bom", f"{label} must be UTF-8 without BOM")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EffectContractError("effect_artifact_json_invalid", f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise EffectContractError("effect_artifact_json_invalid", f"{label} must be a JSON object")
    return document


def _write_new_json(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


@lru_cache(maxsize=3)
def _validator(schema_name: str) -> Draft202012Validator:
    path = files("vlog_director.schemas").joinpath(schema_name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _schema_issues(document: Mapping[str, Any], schema_name: str) -> list[str]:
    errors = sorted(
        _validator(schema_name).iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )
    return [f"{error.json_path}: {error.message}" for error in errors]


def _confined(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    allowed = root.resolve()
    try:
        relative = resolved.relative_to(allowed)
    except ValueError as error:
        raise EffectContractError(
            "effect_artifact_path_invalid",
            f"{label} must stay below {allowed}",
        ) from error
    if resolved == allowed or not relative.parts:
        raise EffectContractError(
            "effect_artifact_path_invalid",
            f"{label} cannot equal its allowed root",
        )
    return resolved


def _project_path(project: Path, relative: Any, allowed: Path, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise EffectContractError("effect_artifact_path_invalid", f"{label} path is invalid")
    return _confined(project / relative, allowed, label)


def _base_media_path(project: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise EffectContractError("effect_base_media_path_invalid", "base media path is invalid")
    resolved = (project / relative).resolve()
    allowed_roots = ((project / "output").resolve(), (project / "work" / "proxy").resolve())
    if not any(resolved != root and resolved.is_relative_to(root) for root in allowed_roots):
        raise EffectContractError(
            "effect_base_media_path_invalid",
            "base media must stay below project/output or project/work/proxy",
        )
    return resolved


def _require_sha(path: Path, expected: Any, code: str, label: str) -> None:
    if not path.is_file() or _sha256_file(path) != expected:
        raise EffectContractError(code, f"{label} SHA-256 does not match the current file")


def _aware_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise EffectContractError("effect_human_review_invalid", "reviewed_at must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EffectContractError("effect_human_review_invalid", "reviewed_at is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectContractError("effect_human_review_invalid", "reviewed_at requires a timezone")


def _collect_contract(
    project: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    effect_plan_path = _confined(effect_plan_path, project / "work" / "effects", "effect plan")
    render_manifest_path = _confined(render_manifest_path, project / "work" / "effects", "render manifest")
    visual_qa_path = _confined(visual_qa_path, project / "work" / "qa" / "effects", "visual QA")
    human_review_path = _confined(human_review_path, project / "work" / "qa" / "effects", "human review")

    effect_plan = _load_json(effect_plan_path, "effect plan")
    edit_path = project / "work" / "plans" / f"edit_plan.v{effect_plan.get('edit_plan_version')}.json"
    edit_plan = _load_json(edit_path, "edit plan")
    edit_plan_sha256 = _canonical_sha256(edit_plan)
    validation = validate_effect_plan(
        edit_plan,
        effect_plan,
        edit_plan_sha256=edit_plan_sha256,
    )
    if validation["status"] != "passed":
        raise EffectContractError(
            "effect_plan_invalid",
            json.dumps(validation["issues"], ensure_ascii=False),
        )
    effect_plan_sha256 = _sha256_file(effect_plan_path)
    effect_payload_sha256 = canonical_effect_payload_sha256(effect_plan)
    expected_ids = [str(row["effect_id"]) for row in effect_plan["effects"]]
    if not expected_ids:
        raise EffectContractError("effect_plan_empty", "An empty effect plan cannot be approved")

    render = _load_json(render_manifest_path, "render manifest")
    if render.get("contract_version") != "hyperframes-render-manifest-v1" or render.get("status") != "rendered":
        raise EffectContractError("effect_render_manifest_invalid", "HyperFrames render manifest is not rendered")
    for field, expected in (
        ("project_id", effect_plan["project_id"]),
        ("edit_plan_version", effect_plan["edit_plan_version"]),
        ("edit_plan_sha256", edit_plan_sha256),
        ("effect_plan_sha256", effect_plan_sha256),
        ("effect_payload_sha256", effect_payload_sha256),
    ):
        if render.get(field) != expected:
            raise EffectContractError("effect_render_binding_mismatch", f"render manifest {field} changed")
    composition_manifest = _project_path(
        project,
        render.get("composition_manifest"),
        project / "work" / "effects",
        "composition manifest",
    )
    _require_sha(
        composition_manifest,
        render.get("composition_manifest_sha256"),
        "effect_composition_manifest_sha256_mismatch",
        "composition manifest",
    )
    render_rows = render.get("effects")
    if not isinstance(render_rows, list) or [str(row.get("effect_id")) for row in render_rows if isinstance(row, dict)] != expected_ids:
        raise EffectContractError("effect_render_set_mismatch", "rendered effect set or order changed")
    outputs: dict[str, Path] = {}
    plan_by_id = {str(row["effect_id"]): row for row in effect_plan["effects"]}
    for row in render_rows:
        effect_id = str(row["effect_id"])
        planned = plan_by_id[effect_id]
        expected_effect_duration = (
            float(planned["placement"]["end_sec"])
            - float(planned["placement"]["start_sec"])
        )
        rendered_duration = row.get("duration_sec")
        if (
            row.get("intent") != planned.get("intent")
            or isinstance(rendered_duration, bool)
            or not isinstance(rendered_duration, (int, float))
            or not math.isfinite(float(rendered_duration))
            or abs(float(rendered_duration) - expected_effect_duration) > 0.001
        ):
            raise EffectContractError(
                "effect_render_recipe_mismatch",
                f"{effect_id} render intent or duration differs from the approved effect plan",
            )
        composition = _project_path(
            project,
            row.get("composition"),
            project / "work" / "effects",
            f"{effect_id} composition",
        )
        _require_sha(
            composition,
            row.get("composition_sha256"),
            "effect_composition_sha256_mismatch",
            f"{effect_id} composition",
        )
        output = _project_path(
            project,
            row.get("output"),
            project / "work" / "effects",
            f"{effect_id} output",
        )
        _require_sha(
            output,
            row.get("output_sha256"),
            "effect_output_sha256_mismatch",
            f"{effect_id} output",
        )
        if output.stat().st_size != row.get("output_size_bytes"):
            raise EffectContractError("effect_output_size_mismatch", f"{effect_id} output size changed")
        outputs[effect_id] = output

    visual = _load_json(visual_qa_path, "effect visual QA")
    visual_schema = _schema_issues(visual, "effect-visual-qa.schema.json")
    if visual_schema:
        raise EffectContractError("effect_visual_qa_schema_invalid", "; ".join(visual_schema))
    render_manifest_sha256 = _sha256_file(render_manifest_path)
    for field, expected in (
        ("project_id", effect_plan["project_id"]),
        ("edit_plan_version", effect_plan["edit_plan_version"]),
        ("edit_plan_sha256", edit_plan_sha256),
        ("effect_plan_sha256", effect_plan_sha256),
        ("effect_payload_sha256", effect_payload_sha256),
        ("render_manifest_sha256", render_manifest_sha256),
    ):
        if visual.get(field) != expected:
            raise EffectContractError("effect_visual_binding_mismatch", f"visual QA {field} changed")
    base_media = _base_media_path(project, visual["base_media"]["path"])
    _require_sha(
        base_media,
        visual["base_media"]["sha256"],
        "effect_base_media_sha256_mismatch",
        "base media",
    )
    if base_media.stat().st_size != visual["base_media"]["size_bytes"]:
        raise EffectContractError("effect_base_media_size_mismatch", "base media size changed")
    visual_rows = visual["effects"]
    if [str(row["effect_id"]) for row in visual_rows] != expected_ids:
        raise EffectContractError("effect_visual_set_mismatch", "visual QA effect set or order changed")
    render_by_id = {str(row["effect_id"]): row for row in render_rows}
    for row in visual_rows:
        effect_id = str(row["effect_id"])
        if row["output_sha256"] != render_by_id[effect_id]["output_sha256"]:
            raise EffectContractError("effect_visual_output_mismatch", f"{effect_id} visual QA output changed")
        preview = _project_path(
            project,
            row["preview"]["path"],
            project / "work" / "qa" / "effects",
            f"{effect_id} preview",
        )
        _require_sha(preview, row["preview"]["sha256"], "effect_preview_sha256_mismatch", f"{effect_id} preview")
        roles = [str(frame["role"]) for frame in row["frames"]]
        if set(roles) != {"entry", "peak", "exit"}:
            raise EffectContractError("effect_visual_frames_invalid", f"{effect_id} requires entry, peak, and exit frames")
        for frame in row["frames"]:
            frame_path = _project_path(
                project,
                frame["path"],
                project / "work" / "qa" / "effects",
                f"{effect_id} {frame['role']} frame",
            )
            _require_sha(
                frame_path,
                frame["sha256"],
                "effect_frame_sha256_mismatch",
                f"{effect_id} {frame['role']} frame",
            )

    human = _load_json(human_review_path, "effect human review")
    human_schema = _schema_issues(human, "effect-human-review.schema.json")
    if human_schema:
        raise EffectContractError("effect_human_review_schema_invalid", "; ".join(human_schema))
    _aware_timestamp(human["reviewed_at"])
    visual_qa_sha256 = _sha256_file(visual_qa_path)
    for field, expected in (
        ("effect_plan_sha256", effect_plan_sha256),
        ("effect_payload_sha256", effect_payload_sha256),
        ("render_manifest_sha256", render_manifest_sha256),
        ("visual_qa_sha256", visual_qa_sha256),
        ("base_media_sha256", visual["base_media"]["sha256"]),
    ):
        if human.get(field) != expected:
            raise EffectContractError("effect_human_binding_mismatch", f"human review {field} changed")
    if [str(row["effect_id"]) for row in human["effects"]] != expected_ids:
        raise EffectContractError("effect_human_set_mismatch", "human-reviewed effect set or order changed")
    for row in human["effects"]:
        if row["decision"] != "accepted" or set(row["checks"]) != REQUIRED_HUMAN_CHECKS:
            raise EffectContractError("effect_human_review_incomplete", f"{row['effect_id']} is not fully accepted")

    return {
        "effect_plan": effect_plan,
        "render": render,
        "visual": visual,
        "human": human,
        "effect_plan_sha256": effect_plan_sha256,
        "effect_payload_sha256": effect_payload_sha256,
        "render_manifest_sha256": render_manifest_sha256,
        "visual_qa_sha256": visual_qa_sha256,
        "human_review_sha256": _sha256_file(human_review_path),
        "base_media_sha256": visual["base_media"]["sha256"],
        "effect_ids": expected_ids,
        "outputs": outputs,
    }


def build_effect_approval(
    project: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    project = project.resolve()
    output_path = _confined(output_path, project / "work" / "qa" / "effects", "effect approval")
    if output_path.exists():
        raise FileExistsError(output_path)
    contract = _collect_contract(
        project,
        effect_plan_path,
        render_manifest_path,
        visual_qa_path,
        human_review_path,
    )
    core = {
        "schema_version": "1.0",
        "contract_version": "effect-approval-v1",
        "status": "approved",
        "project_id": contract["effect_plan"]["project_id"],
        "edit_plan_version": contract["effect_plan"]["edit_plan_version"],
        "edit_plan_sha256": contract["effect_plan"]["edit_plan_sha256"],
        "effect_plan_sha256": contract["effect_plan_sha256"],
        "effect_payload_sha256": contract["effect_payload_sha256"],
        "render_manifest_sha256": contract["render_manifest_sha256"],
        "visual_qa_sha256": contract["visual_qa_sha256"],
        "human_review_sha256": contract["human_review_sha256"],
        "base_media_sha256": contract["base_media_sha256"],
        "effect_ids": contract["effect_ids"],
        "approved_by": contract["human"]["reviewer"],
        "approved_at": contract["human"]["reviewed_at"],
    }
    approval = {**core, "approval_sha256": _canonical_sha256(core)}
    schema_issues = _schema_issues(approval, "effect-approval.schema.json")
    if schema_issues:
        raise EffectContractError("effect_approval_schema_invalid", "; ".join(schema_issues))
    _write_new_json(output_path, approval)
    return approval


def validate_effect_approval(
    project: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
    visual_qa_path: Path,
    human_review_path: Path,
    approval_path: Path,
) -> dict[str, Any]:
    try:
        project = project.resolve()
        approval_path = _confined(approval_path, project / "work" / "qa" / "effects", "effect approval")
        approval = _load_json(approval_path, "effect approval")
        schema_issues = _schema_issues(approval, "effect-approval.schema.json")
        if schema_issues:
            raise EffectContractError("effect_approval_schema_invalid", "; ".join(schema_issues))
        contract = _collect_contract(
            project,
            effect_plan_path,
            render_manifest_path,
            visual_qa_path,
            human_review_path,
        )
        expected = {
            "project_id": contract["effect_plan"]["project_id"],
            "edit_plan_version": contract["effect_plan"]["edit_plan_version"],
            "edit_plan_sha256": contract["effect_plan"]["edit_plan_sha256"],
            "effect_plan_sha256": contract["effect_plan_sha256"],
            "effect_payload_sha256": contract["effect_payload_sha256"],
            "render_manifest_sha256": contract["render_manifest_sha256"],
            "visual_qa_sha256": contract["visual_qa_sha256"],
            "human_review_sha256": contract["human_review_sha256"],
            "base_media_sha256": contract["base_media_sha256"],
            "effect_ids": contract["effect_ids"],
            "approved_by": contract["human"]["reviewer"],
            "approved_at": contract["human"]["reviewed_at"],
        }
        for field, value in expected.items():
            if approval.get(field) != value:
                raise EffectContractError("effect_approval_binding_mismatch", f"approval {field} changed")
        core = {key: value for key, value in approval.items() if key != "approval_sha256"}
        if approval.get("approval_sha256") != _canonical_sha256(core):
            raise EffectContractError("effect_approval_sha256_mismatch", "approval canonical SHA-256 changed")
        return {
            "schema_version": "1.0",
            "status": "passed",
            "blocker_codes": [],
            "effect_count": len(contract["effect_ids"]),
            "approval_sha256": approval["approval_sha256"],
        }
    except EffectContractError as error:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "blocker_codes": [error.code],
            "issues": [{"code": error.code, "message": str(error)}],
        }
    except (FileNotFoundError, FileExistsError, OSError, ValueError) as error:
        return {
            "schema_version": "1.0",
            "status": "blocked",
            "blocker_codes": ["effect_approval_contract_invalid"],
            "issues": [{"code": "effect_approval_contract_invalid", "message": str(error)}],
        }


def _binding(project: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.resolve().relative_to(project.resolve()).as_posix(),
        "sha256": _sha256_file(path.resolve()),
    }


def apply_approved_effects(
    project: Path,
    enhancement_plan_path: Path,
    effect_plan_path: Path,
    render_manifest_path: Path,
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
    output_path = _confined(output_path, project / "work" / "enhancement", "enhancement output")
    if output_path.exists():
        raise FileExistsError(output_path)
    validation = validate_effect_approval(
        project,
        effect_plan_path,
        render_manifest_path,
        visual_qa_path,
        human_review_path,
        approval_path,
    )
    if validation["status"] != "passed":
        raise EffectContractError(
            validation["blocker_codes"][0],
            json.dumps(validation.get("issues", []), ensure_ascii=False),
        )
    contract = _collect_contract(
        project,
        effect_plan_path,
        render_manifest_path,
        visual_qa_path,
        human_review_path,
    )
    approval = _load_json(approval_path, "effect approval")
    enhancement = deepcopy(_load_json(enhancement_plan_path, "enhancement plan"))
    effect_plan = contract["effect_plan"]
    if enhancement.get("project_id") != effect_plan.get("project_id"):
        raise EffectContractError("effect_enhancement_project_mismatch", "enhancement project differs")
    if enhancement.get("edit_plan_version") != effect_plan.get("edit_plan_version"):
        raise EffectContractError("effect_enhancement_version_mismatch", "enhancement edit version differs")
    section = enhancement.setdefault(
        "illustration_motion",
        {"status": "planned", "items": [], "subtitle_safe_zone": True},
    )
    existing_ids = {str(row.get("id")) for row in section.get("items", []) if isinstance(row, dict)}
    render_by_id = {str(row["effect_id"]): row for row in contract["render"]["effects"]}
    plan_by_id = {str(row["effect_id"]): row for row in effect_plan["effects"]}
    for effect_id in contract["effect_ids"]:
        if effect_id in existing_ids:
            raise EffectContractError("duplicate_effect_overlay_id", f"overlay already exists: {effect_id}")
        effect = plan_by_id[effect_id]
        rendered = render_by_id[effect_id]
        section.setdefault("items", []).append(
            {
                "id": effect_id,
                "type": "hyperframes",
                "source": rendered["output"],
                "media_kind": "transparent_video",
                "source_sha256": rendered["output_sha256"],
                "effect_intent": effect["intent"],
                "approval_sha256": approval["approval_sha256"],
                "start_sec": effect["placement"]["start_sec"],
                "end_sec": effect["placement"]["end_sec"],
                "anchor": "center",
                "animation": "none",
                "scale_percent": 100,
                "margin_percent": 0,
            }
        )
    section["status"] = "ready"
    section["subtitle_safe_zone"] = True
    section["effect_evidence"] = {
        "contract_version": "effect-ready-evidence-v1",
        "effect_payload_sha256": contract["effect_payload_sha256"],
        "base_media_sha256": contract["base_media_sha256"],
        "effect_plan": _binding(project, effect_plan_path),
        "render_manifest": _binding(project, render_manifest_path),
        "visual_qa": _binding(project, visual_qa_path),
        "human_review": _binding(project, human_review_path),
        "approval": _binding(project, approval_path),
    }
    enhancement["version"] = int(enhancement.get("version", 1)) + 1
    schema_issues = enhancement_schema_errors(enhancement)
    if schema_issues:
        raise EffectContractError(
            "effect_enhancement_schema_invalid",
            "; ".join(f"{error.json_path}: {error.message}" for error in schema_issues),
        )
    _write_new_json(output_path, enhancement)
    return enhancement
