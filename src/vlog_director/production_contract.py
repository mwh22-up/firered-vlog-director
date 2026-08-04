from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from .approval import plan_sha256, verify_approval
from .enhancement import normalize_realized_timeline, validate_realized_timeline
from .ffmpeg import find_ffmpeg, probe_media
from .subtitle_layout_probe import inspect_ffmpeg_identity


CONTRACT_VERSION = "directed-base-contract-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _confined(project: Path, path: Path, root: str, label: str) -> Path:
    resolved = path.resolve()
    allowed = (project / root).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as error:
        raise ValueError(f"{label} must stay under {root}") from error
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved


def _relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def bind_directed_base(
    *,
    project: Path,
    edit_plan_path: Path,
    approval_path: Path,
    realized_timeline_path: Path,
    base_media_path: Path,
    output_path: Path,
    producer: Mapping[str, str],
    executable: str = "ffmpeg",
) -> dict[str, Any]:
    """Bind an externally rendered directed base into this repository's QA chain."""
    project = project.resolve()
    marker = _load_json(project / ".vlog-project.json", "project marker")
    edit_path = _confined(project, edit_plan_path, "work/plans", "edit plan")
    approval_file = _confined(project, approval_path, "work/qa", "approval receipt")
    timeline_path = _confined(project, realized_timeline_path, "work/qa", "realized timeline")
    output = output_path.resolve()
    allowed_output = (project / "work" / "qa").resolve()
    try:
        output.relative_to(allowed_output)
    except ValueError as error:
        raise ValueError("directed base contract output must stay under work/qa") from error
    if output == allowed_output or output.exists():
        raise FileExistsError(output)
    media = base_media_path.resolve()
    if not media.is_file():
        raise FileNotFoundError(media)

    edit_plan = _load_json(edit_path, "edit plan")
    approval = _load_json(approval_file, "approval receipt")
    approval_check = verify_approval(edit_plan, approval)
    if approval_check["status"] != "passed":
        raise ValueError("edit plan approval is invalid: " + "; ".join(approval_check["issues"]))
    timeline_document = _load_json(timeline_path, "realized timeline")
    timeline = normalize_realized_timeline(
        edit_plan,
        timeline_document,
        edit_plan_sha256=_sha256_file(edit_path),
    )
    timeline_issues = validate_realized_timeline(edit_plan, timeline)
    if timeline_issues:
        raise ValueError("realized timeline is invalid: " + json.dumps(timeline_issues, ensure_ascii=False))
    media_sha = _sha256_file(media)
    if timeline.get("base_sha256") and timeline["base_sha256"] != media_sha:
        raise ValueError("realized timeline base SHA-256 does not match media")
    if timeline.get("base_size_bytes") and timeline["base_size_bytes"] != media.stat().st_size:
        raise ValueError("realized timeline base size does not match media")

    ffmpeg = find_ffmpeg(executable)
    media_probe = probe_media(ffmpeg, media)
    if not media_probe["has_video"] or not media_probe["has_audio"]:
        raise ValueError("directed base must contain video and audio")
    if abs(float(media_probe["duration_sec"]) - float(timeline["duration_sec"])) > 0.15:
        raise ValueError("directed base duration does not match realized timeline")
    producer_document = {
        "repository": str(producer.get("repository", "")),
        "commit_sha": str(producer.get("commit_sha", "")).lower(),
        "contract": str(producer.get("contract", "")),
    }
    contract = {
        "schema_version": "1.0",
        "contract_version": CONTRACT_VERSION,
        "status": "ready",
        "project_id": str(marker.get("project_id", "")),
        "edit_plan": {
            "path": _relative(project, edit_path),
            "sha256": _sha256_file(edit_path),
            "canonical_sha256": plan_sha256(edit_plan),
        },
        "approval": {"path": _relative(project, approval_file), "sha256": _sha256_file(approval_file)},
        "realized_timeline": {
            "path": _relative(project, timeline_path),
            "sha256": _sha256_file(timeline_path),
            "duration_sec": round(float(timeline["duration_sec"]), 6),
        },
        "base_media": {
            "name": media.name,
            "sha256": media_sha,
            "size_bytes": media.stat().st_size,
            "duration_sec": round(float(media_probe["duration_sec"]), 6),
            "width": int(media_probe["width"]),
            "height": int(media_probe["height"]),
            "has_video": True,
            "has_audio": True,
        },
        "producer": producer_document,
        "ffmpeg_identity": inspect_ffmpeg_identity(ffmpeg),
    }
    schema_path = Path(__file__).with_name("schemas") / "directed-base-contract.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(contract), key=lambda error: error.json_path)
    if errors:
        raise ValueError("directed base contract schema invalid: " + "; ".join(f"{error.json_path}: {error.message}" for error in errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return contract
