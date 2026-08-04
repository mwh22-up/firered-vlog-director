from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .subtitle_approval import validate_subtitle_approval
from .subtitle_readability import (
    canonical_subtitle_payload_digest,
    canonical_subtitle_style_digest,
    canonical_verified_cue_set_digest,
)

REQUIRED_MUSIC_RIGHTS_SCOPES = frozenset(
    {
        "synchronize",
        "modify",
        "render",
        "distribute_with_project",
    }
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUBTITLE_READY_EVIDENCE_VERSION = "subtitle-ready-evidence-v1"
SUBTITLE_EVIDENCE_BINDING_NAMES = (
    "readability",
    "layout",
    "visual",
    "human_review",
    "approval",
)
SUBTITLE_EVIDENCE_DIGEST_NAMES = (
    "subtitle_payload_sha256",
    "subtitle_style_sha256",
    "verified_cue_set_sha256",
)
SUBTITLE_READY_EVIDENCE_FIELDS = frozenset(
    {
        "contract_version",
        *SUBTITLE_EVIDENCE_BINDING_NAMES,
        *SUBTITLE_EVIDENCE_DIGEST_NAMES,
    }
)


def _issue(code: str, subject_id: str, message: str) -> dict[str, Any]:
    return {
        "severity": "error",
        "code": code,
        "subject_id": subject_id,
        "message": message,
    }


def _warning(code: str, subject_id: str, message: str) -> dict[str, Any]:
    return {
        "severity": "warning",
        "code": code,
        "subject_id": subject_id,
        "message": message,
    }


def _unsafe_relative_path(value: str) -> bool:
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    return (
        not value.strip()
        or "\x00" in value
        or bool(windows_path.drive)
        or windows_path.is_absolute()
        or posix_path.is_absolute()
        or ".." in windows_path.parts
        or ".." in posix_path.parts
    )


def _resolve_confined_file(
    base: Path,
    value: Any,
    root: Path,
    subject_id: str,
    issues: list[dict[str, Any]],
) -> Path | None:
    if not isinstance(value, str) or _unsafe_relative_path(value):
        issues.append(
            _issue(
                "enhancement_asset_path_invalid",
                subject_id,
                "Enhancement asset paths must be non-empty project-relative paths "
                "without traversal, drive prefixes, or UNC roots.",
            )
        )
        return None

    try:
        resolved_root = root.resolve()
        resolved = (base / value).resolve()
        resolved.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        issues.append(
            _issue(
                "enhancement_asset_path_outside_root",
                subject_id,
                f"Enhancement asset must stay inside {resolved_root if 'resolved_root' in locals() else root}.",
            )
        )
        return None
    if not resolved.is_file():
        issues.append(
            _issue(
                "enhancement_asset_missing",
                subject_id,
                "Enhancement asset does not exist or is not a regular file.",
            )
        )
        return None
    return resolved


def _load_json_document(
    path: Path,
    subject_id: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        issues.append(
            _issue(
                "enhancement_asset_json_invalid",
                subject_id,
                "Enhancement asset metadata must be valid UTF-8 JSON without a BOM.",
            )
        )
        return None
    if not isinstance(document, dict):
        issues.append(
            _issue(
                "enhancement_asset_json_invalid",
                subject_id,
                "Enhancement asset metadata must be a JSON object.",
            )
        )
        return None
    return document


def _sha256_file(path: Path, cache: dict[Path, str]) -> str:
    cached = cache.get(path)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    result = digest.hexdigest()
    cache[path] = result
    return result


def _validate_overlays(
    project: Path,
    enhancement_plan: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    section = enhancement_plan.get("illustration_motion", {})
    items = section.get("items", [])
    if not isinstance(items, list):
        return
    assets_root = project / "assets"
    effect_items: list[dict[str, Any]] = []
    hash_cache: dict[Path, str] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        subject_id = str(item.get("id") or f"overlay-{index}")
        if item.get("type") == "hyperframes":
            effect_items.append(item)
            source = _resolve_confined_file(
                project,
                item.get("source"),
                project / "work" / "effects",
                subject_id,
                issues,
            )
            if source is not None and _sha256_file(source, hash_cache) != item.get("source_sha256"):
                issues.append(
                    _issue(
                        "effect_output_sha256_mismatch",
                        subject_id,
                        "HyperFrames overlay SHA-256 differs from the approved output.",
                    )
                )
        else:
            _resolve_confined_file(
                project,
                item.get("source"),
                assets_root,
                subject_id,
                issues,
            )

    if not effect_items:
        return
    evidence = section.get("effect_evidence")
    if not isinstance(evidence, dict) or evidence.get("contract_version") != "effect-ready-evidence-v1":
        issues.append(
            _issue(
                "effect_ready_evidence_missing",
                "illustration_motion",
                "HyperFrames overlays require CLI-generated effect-ready evidence.",
            )
        )
        return
    required_bindings = {
        "effect_plan": project / "work" / "effects",
        "render_manifest": project / "work" / "effects",
        "visual_qa": project / "work" / "qa" / "effects",
        "human_review": project / "work" / "qa" / "effects",
        "approval": project / "work" / "qa" / "effects",
    }
    resolved: dict[str, Path] = {}
    for name, allowed_root in required_bindings.items():
        binding = evidence.get(name)
        if not isinstance(binding, dict):
            issues.append(
                _issue(
                    "effect_ready_evidence_invalid",
                    name,
                    "Effect evidence binding is missing.",
                )
            )
            continue
        path = _resolve_confined_file(
            project,
            binding.get("path"),
            allowed_root,
            name,
            issues,
        )
        if path is None:
            continue
        if _sha256_file(path, hash_cache) != binding.get("sha256"):
            issues.append(
                _issue(
                    "effect_ready_evidence_sha256_mismatch",
                    name,
                    "Effect evidence file SHA-256 changed.",
                )
            )
            continue
        resolved[name] = path
    if len(resolved) != len(required_bindings):
        return
    from .effect_approval import validate_effect_approval

    approval_validation = validate_effect_approval(
        project,
        resolved["effect_plan"],
        resolved["render_manifest"],
        resolved["visual_qa"],
        resolved["human_review"],
        resolved["approval"],
    )
    if approval_validation["status"] != "passed":
        for code in approval_validation.get("blocker_codes", ["effect_approval_invalid"]):
            issues.append(
                _issue(
                    str(code),
                    "illustration_motion",
                    "HyperFrames approval no longer matches its evidence chain.",
                )
            )
        return
    approval_document = _load_json_document(resolved["approval"], "effect approval", issues)
    if approval_document is None:
        return
    expected_approval = approval_document.get("approval_sha256")
    expected_payload = approval_document.get("effect_payload_sha256")
    if evidence.get("effect_payload_sha256") != expected_payload:
        issues.append(
            _issue(
                "effect_ready_payload_mismatch",
                "illustration_motion",
                "Enhancement effect payload differs from the approved payload.",
            )
        )
    if evidence.get("base_media_sha256") != approval_document.get("base_media_sha256"):
        issues.append(
            _issue(
                "effect_ready_base_media_mismatch",
                "illustration_motion",
                "Enhancement effect evidence is bound to a different base edit.",
            )
        )
    approval_ids = set(approval_document.get("effect_ids", []))
    item_ids = {str(item.get("id")) for item in effect_items}
    if item_ids != approval_ids:
        issues.append(
            _issue(
                "effect_ready_set_mismatch",
                "illustration_motion",
                "Enhancement HyperFrames item set differs from the approved effect set.",
            )
        )
    for item in effect_items:
        if item.get("approval_sha256") != expected_approval:
            issues.append(
                _issue(
                    "effect_item_approval_mismatch",
                    str(item.get("id")),
                    "HyperFrames item is not bound to the current approval.",
                )
            )


def _music_manifest_assets(
    project: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], Path | None]]:
    raw_assets = manifest.get("assets")
    if not isinstance(raw_assets, list):
        issues.append(
            _issue(
                "music_manifest_assets_invalid",
                "music",
                "The rights manifest must contain an assets array.",
            )
        )
        return {}

    assets: dict[str, tuple[dict[str, Any], Path | None]] = {}
    for index, asset in enumerate(raw_assets, start=1):
        if not isinstance(asset, dict):
            issues.append(
                _issue(
                    "music_manifest_asset_invalid",
                    f"manifest-asset-{index}",
                    "Each rights manifest asset must be an object.",
                )
            )
            continue
        asset_id = str(asset.get("id") or "")
        subject_id = asset_id or f"manifest-asset-{index}"
        if not asset_id or asset_id in assets:
            issues.append(
                _issue(
                    "music_manifest_asset_id_invalid",
                    subject_id,
                    "Rights manifest asset IDs must be non-empty and unique.",
                )
            )
            continue
        asset_path = _resolve_confined_file(
            manifest_path.parent,
            asset.get("path"),
            project / "assets",
            subject_id,
            issues,
        )
        assets[asset_id] = (asset, asset_path)
    return assets


def _validate_music_rights(
    manifest: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    approval = manifest.get("rights_approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        issues.append(
            _issue(
                "music_rights_not_approved",
                "music",
                "Ready music requires rights_approval.status to be approved.",
            )
        )
        return

    missing_metadata = [
        field
        for field in ("rights_holder", "approved_by", "approved_at")
        if not isinstance(approval.get(field), str) or not approval[field].strip()
    ]
    if missing_metadata:
        issues.append(
            _issue(
                "music_rights_metadata_missing",
                "music",
                "Approved music rights require non-empty "
                + ", ".join(missing_metadata)
                + ".",
            )
        )

    scopes = approval.get("scopes", approval.get("required_scope"))
    scope_values = {
        value for value in scopes if isinstance(value, str)
    } if isinstance(scopes, list) else set()
    missing_scopes = sorted(REQUIRED_MUSIC_RIGHTS_SCOPES - scope_values)
    if missing_scopes:
        issues.append(
            _issue(
                "music_rights_scope_incomplete",
                "music",
                "Approved music rights are missing scopes: "
                + ", ".join(missing_scopes)
                + ".",
            )
        )


def _music_audition_assets(
    tracks: list[dict[str, Any]],
    report: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    status = report.get("status")
    if not isinstance(status, str) or not status.strip():
        issues.append(
            _issue(
                "music_audition_report_invalid",
                "music",
                "The audition report requires a non-empty status.",
            )
        )
    if not isinstance(report.get("blocking_items"), list):
        issues.append(
            _issue(
                "music_audition_report_invalid",
                "music",
                "The audition report requires a blocking_items array.",
            )
        )

    raw_assets = report.get("assets")
    audition_assets: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_assets, list):
        issues.append(
            _issue(
                "music_audition_report_invalid",
                "music",
                "The audition report requires an assets array.",
            )
        )
        return audition_assets
    for index, asset in enumerate(raw_assets, start=1):
        if not isinstance(asset, dict):
            issues.append(
                _issue(
                    "music_audition_asset_invalid",
                    f"audition-asset-{index}",
                    "Each audition asset must be an object.",
                )
            )
            continue
        asset_id = asset.get("id")
        subject_id = str(asset_id or f"audition-asset-{index}")
        if (
            not isinstance(asset_id, str)
            or not asset_id.strip()
            or asset_id in audition_assets
        ):
            issues.append(
                _issue(
                    "music_audition_asset_id_invalid",
                    subject_id,
                    "Audition asset IDs must be non-empty and unique.",
                )
            )
            continue
        audition_status = asset.get("audition_status")
        if not isinstance(audition_status, str) or not audition_status.strip():
            issues.append(
                _issue(
                    "music_audition_asset_invalid",
                    asset_id,
                    "Each audition asset requires a non-empty audition_status.",
                )
            )
        audition_assets[asset_id] = asset

    for index, track in enumerate(tracks, start=1):
        track_id = str(track.get("id") or f"music-{index}")
        if track_id not in audition_assets:
            issues.append(
                _issue(
                    "music_track_audition_missing",
                    track_id,
                    "Every selected music track must exist in the audition report.",
                )
            )
    return audition_assets


def _validate_music_audition(
    tracks: list[dict[str, Any]],
    report: dict[str, Any],
    audition_assets: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if report.get("status") != "passed":
        issues.append(
            _issue(
                "music_audition_not_passed",
                "music",
                "Ready music requires an audition report with status passed.",
            )
        )
    blocking_items = report.get("blocking_items")
    if not isinstance(blocking_items, list) or blocking_items:
        issues.append(
            _issue(
                "music_audition_blocked",
                "music",
                "Ready music requires an empty audition blocking_items array.",
            )
        )

    for index, track in enumerate(tracks, start=1):
        track_id = str(track.get("id") or f"music-{index}")
        audition = audition_assets.get(track_id)
        if audition is not None and audition.get("audition_status") != "passed":
            issues.append(
                _issue(
                    "music_track_audition_not_passed",
                    track_id,
                    "Every selected music track must have audition_status passed.",
                )
            )


def _validate_music(
    project: Path,
    music: dict[str, Any],
    issues: list[dict[str, Any]],
    hash_cache: dict[Path, str],
    *,
    require_ready: bool,
) -> None:
    raw_tracks = music.get("tracks")
    tracks: list[dict[str, Any]] = []
    track_ids: set[str] = set()
    if isinstance(raw_tracks, list):
        for index, track in enumerate(raw_tracks, start=1):
            if not isinstance(track, dict):
                issues.append(
                    _issue(
                        "music_track_invalid",
                        f"music-{index}",
                        "Each selected music track must be an object.",
                    )
                )
                continue
            tracks.append(track)
            track_id = track.get("id")
            if not isinstance(track_id, str) or not track_id.strip():
                issues.append(
                    _issue(
                        "music_track_id_invalid",
                        f"music-{index}",
                        "Selected music track IDs must be non-empty strings.",
                    )
                )
            elif track_id in track_ids:
                issues.append(
                    _issue(
                        "music_track_id_duplicate",
                        track_id,
                        "Selected music track IDs must be unique.",
                    )
                )
            else:
                track_ids.add(track_id)
    if not tracks:
        issues.append(
            _issue(
                "ready_music_empty",
                "music",
                "An audition or ready music section must contain at least one selected track.",
            )
        )

    track_paths: dict[int, Path | None] = {}
    for index, track in enumerate(tracks, start=1):
        track_id = str(track.get("id") or f"music-{index}")
        track_paths[index] = _resolve_confined_file(
            project,
            track.get("source"),
            project / "assets",
            track_id,
            issues,
        )

    manifest_path = _resolve_confined_file(
        project,
        music.get("rights_manifest"),
        project,
        "music.rights_manifest",
        issues,
    )
    audition_path = _resolve_confined_file(
        project,
        music.get("audition_report"),
        project,
        "music.audition_report",
        issues,
    )
    manifest = (
        _load_json_document(manifest_path, "music.rights_manifest", issues)
        if manifest_path is not None
        else None
    )
    report = (
        _load_json_document(audition_path, "music.audition_report", issues)
        if audition_path is not None
        else None
    )

    manifest_assets: dict[str, tuple[dict[str, Any], Path | None]] = {}
    if manifest is not None:
        if require_ready:
            _validate_music_rights(manifest, issues)
        manifest_assets = _music_manifest_assets(
            project,
            manifest_path,
            manifest,
            issues,
        )
    if report is not None:
        audition_assets = _music_audition_assets(tracks, report, issues)
        if require_ready:
            _validate_music_audition(
                tracks,
                report,
                audition_assets,
                issues,
            )

    for index, track in enumerate(tracks, start=1):
        track_id = str(track.get("id") or f"music-{index}")
        manifest_asset = manifest_assets.get(track_id)
        if manifest_asset is None:
            if manifest is not None:
                issues.append(
                    _issue(
                        "music_manifest_track_missing",
                        track_id,
                        "Selected music track is missing from the rights manifest.",
                    )
                )
            continue
        asset, manifest_asset_path = manifest_asset
        track_path = track_paths[index]
        if (
            track_path is not None
            and manifest_asset_path is not None
            and track_path != manifest_asset_path
        ):
            issues.append(
                _issue(
                    "music_manifest_track_path_mismatch",
                    track_id,
                    "Selected music source does not match the manifest asset path.",
                )
            )
            continue
        if track_path is None:
            continue

        expected_size = asset.get("size_bytes")
        if (
            not isinstance(expected_size, int)
            or isinstance(expected_size, bool)
            or track_path.stat().st_size != expected_size
        ):
            issues.append(
                _issue(
                    "music_asset_size_mismatch",
                    track_id,
                    "Music asset size does not match the rights manifest.",
                )
            )
        expected_sha256 = asset.get("sha256")
        try:
            actual_sha256 = _sha256_file(track_path, hash_cache)
        except OSError:
            issues.append(
                _issue(
                    "enhancement_asset_unreadable",
                    track_id,
                    "Music asset could not be read for SHA-256 validation.",
                )
            )
        else:
            if (
                not isinstance(expected_sha256, str)
                or not SHA256_PATTERN.fullmatch(expected_sha256)
                or actual_sha256 != expected_sha256
            ):
                issues.append(
                    _issue(
                        "music_asset_sha256_mismatch",
                        track_id,
                        "Music asset SHA-256 does not match the rights manifest.",
                    )
                )


def subtitle_ready_evidence_contract_issues(evidence: Any) -> list[str]:
    """Return structural evidence-contract defects without trusting status fields."""
    if not isinstance(evidence, dict):
        return ["evidence must be an object"]
    issues: list[str] = []
    unknown = sorted(set(evidence) - SUBTITLE_READY_EVIDENCE_FIELDS)
    missing = sorted(SUBTITLE_READY_EVIDENCE_FIELDS - set(evidence))
    if unknown:
        issues.append(f"unknown fields: {unknown}")
    if missing:
        issues.append(f"missing fields: {missing}")
    if evidence.get("contract_version") != SUBTITLE_READY_EVIDENCE_VERSION:
        issues.append("contract_version is unsupported")
    for field in SUBTITLE_EVIDENCE_DIGEST_NAMES:
        value = evidence.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            issues.append(f"{field} must be a lowercase SHA-256")
    for name in SUBTITLE_EVIDENCE_BINDING_NAMES:
        binding = evidence.get(name)
        if not isinstance(binding, dict):
            issues.append(f"{name} must be a path/SHA binding")
            continue
        if set(binding) != {"path", "sha256"}:
            issues.append(f"{name} binding fields must be exactly path and sha256")
        value = binding.get("path")
        if (
            not isinstance(value, str)
            or _unsafe_relative_path(value)
            or PurePosixPath(value).parts[:2] != ("work", "qa")
        ):
            issues.append(f"{name}.path must be a portable work/qa path")
        sha256 = binding.get("sha256")
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            issues.append(f"{name}.sha256 must be a lowercase SHA-256")
    return issues


def _validate_ready_subtitle_evidence(
    project: Path,
    subtitles: dict[str, Any],
    source_path: Path,
    source: dict[str, Any],
    issues: list[dict[str, Any]],
    hash_cache: dict[Path, str],
) -> None:
    evidence = subtitles.get("evidence")
    if evidence is None:
        issues.append(
            _issue(
                "subtitle_ready_evidence_legacy",
                "subtitles.evidence",
                "Legacy ready subtitles have no hash-bound readability, layout, visual, human-review, and approval evidence.",
            )
        )
        return
    contract_issues = subtitle_ready_evidence_contract_issues(evidence)
    if contract_issues:
        issues.append(
            _issue(
                "subtitle_ready_evidence_invalid",
                "subtitles.evidence",
                "Ready subtitle evidence contract is invalid: "
                + "; ".join(contract_issues),
            )
        )
        if not SUBTITLE_READY_EVIDENCE_FIELDS.issubset(evidence) or any(
            not isinstance(evidence.get(name), dict)
            or not {"path", "sha256"}.issubset(evidence[name])
            for name in SUBTITLE_EVIDENCE_BINDING_NAMES
        ):
            return

    try:
        computed_digests = {
            "subtitle_payload_sha256": canonical_subtitle_payload_digest(source),
            "subtitle_style_sha256": canonical_subtitle_style_digest(
                subtitles.get("style", {})
            ),
            "verified_cue_set_sha256": canonical_verified_cue_set_digest(
                source.get("cues", [])
            ),
        }
    except (TypeError, ValueError) as error:
        issues.append(
            _issue(
                "subtitle_ready_digest_invalid",
                "subtitles.evidence",
                f"Ready subtitle source/style cannot be canonically bound: {error}",
            )
        )
        return
    digest_issue_codes = {
        "subtitle_payload_sha256": "subtitle_payload_sha256_mismatch",
        "subtitle_style_sha256": "subtitle_style_sha256_mismatch",
        "verified_cue_set_sha256": "subtitle_verified_cue_set_sha256_mismatch",
    }
    for field, actual in computed_digests.items():
        if evidence.get(field) != actual:
            issues.append(
                _issue(
                    digest_issue_codes[field],
                    f"subtitles.evidence.{field}",
                    f"Ready subtitle {field} does not match current content.",
                )
            )

    resolved: dict[str, Path] = {}
    binding_failed = False
    for name in SUBTITLE_EVIDENCE_BINDING_NAMES:
        binding = evidence[name]
        subject_id = f"subtitles.evidence.{name}"
        bound_path = _resolve_confined_file(
            project,
            binding["path"],
            project / "work" / "qa",
            subject_id,
            issues,
        )
        if bound_path is None:
            binding_failed = True
            continue
        resolved[name] = bound_path
        try:
            actual_sha256 = _sha256_file(bound_path, hash_cache)
        except OSError:
            binding_failed = True
            issues.append(
                _issue(
                    "enhancement_asset_unreadable",
                    subject_id,
                    "Subtitle QA evidence could not be read for SHA-256 validation.",
                )
            )
            continue
        if actual_sha256 != binding["sha256"]:
            binding_failed = True
            issues.append(
                _issue(
                    "subtitle_evidence_sha256_mismatch",
                    subject_id,
                    "Subtitle QA evidence SHA-256 does not match the ready contract.",
                )
            )
    if binding_failed or len(resolved) != len(SUBTITLE_EVIDENCE_BINDING_NAMES):
        return

    try:
        approval_result = validate_subtitle_approval(
            subtitle_source_path=source_path,
            plan_style=subtitles.get("style", {}),
            readability_qa_path=resolved["readability"],
            layout_qa_path=resolved["layout"],
            visual_qa_path=resolved["visual"],
            human_review_path=resolved["human_review"],
            approval_path=resolved["approval"],
        )
    except (KeyError, OSError, TypeError, ValueError) as error:
        approval_issues = [str(error)]
    else:
        approval_issues = [str(item) for item in approval_result.get("issues", [])]
        if approval_result.get("status") != "passed" and not approval_issues:
            approval_issues = ["approval validation did not pass"]
    if approval_issues:
        issues.append(
            _issue(
                "subtitle_approval_invalid",
                "subtitles.evidence.approval",
                "Ready subtitle approval is stale or invalid: "
                + "; ".join(approval_issues[:8]),
            )
        )


def _subtitle_cue_projection(cues: list[Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for cue in cues:
        if not isinstance(cue, dict):
            projected.append({})
            continue
        item = {
            field: cue.get(field)
            for field in ("start_sec", "end_sec", "text", "review_status")
        }
        for field in (
            "cue_id",
            "segment_id",
            "chapter_id",
            "position",
        ):
            if field in cue:
                item[field] = cue.get(field)
        projected.append(item)
    return projected


def _validate_subtitles(
    project: Path,
    subtitles: dict[str, Any],
    issues: list[dict[str, Any]],
    hash_cache: dict[Path, str],
    *,
    require_ready: bool,
) -> None:
    plan_coverage = subtitles.get("coverage", {}).get("status")
    if require_ready and plan_coverage != "verified":
        issues.append(
            _issue(
                "subtitle_plan_coverage_unverified",
                "subtitles",
                "Ready subtitles require verified plan coverage.",
            )
        )
    elif not require_ready and plan_coverage not in {"pending", "verified"}:
        issues.append(
            _issue(
                "subtitle_review_coverage_invalid",
                "subtitles",
                "Review subtitles require pending or verified plan coverage.",
            )
        )
    source_path = _resolve_confined_file(
        project,
        subtitles.get("source"),
        project / "work" / "subtitles",
        "subtitles.source",
        issues,
    )
    expected_sha256 = subtitles.get("source_sha256")
    if not isinstance(expected_sha256, str) or not SHA256_PATTERN.fullmatch(
        expected_sha256
    ):
        issues.append(
            _issue(
                "subtitle_source_sha256_invalid",
                "subtitles.source",
                "Review and ready subtitles require a lowercase 64-character source_sha256.",
            )
        )
    if source_path is None:
        return

    try:
        actual_sha256 = _sha256_file(source_path, hash_cache)
    except OSError:
        issues.append(
            _issue(
                "enhancement_asset_unreadable",
                "subtitles.source",
                "Subtitle source could not be read for SHA-256 validation.",
            )
        )
        return
    if isinstance(expected_sha256, str) and actual_sha256 != expected_sha256:
        issues.append(
            _issue(
                "subtitle_source_sha256_mismatch",
                "subtitles.source",
                "Subtitle source SHA-256 does not match source_sha256.",
            )
        )

    source = _load_json_document(source_path, "subtitles.source", issues)
    if source is None:
        return
    expected_source_status = "ready" if require_ready else "review_required"
    if source.get("status") != expected_source_status:
        issues.append(
            _issue(
                (
                    "subtitle_source_not_ready"
                    if require_ready
                    else "subtitle_source_not_reviewable"
                ),
                "subtitles.source",
                f"Subtitle source status must be {expected_source_status}.",
            )
        )
    source_coverage = source.get("coverage", {}).get("status")
    if require_ready and source_coverage != "verified":
        issues.append(
            _issue(
                "subtitle_source_coverage_unverified",
                "subtitles.source",
                "Ready subtitles require verified source coverage.",
            )
        )
    elif not require_ready and source_coverage not in {"pending", "verified"}:
        issues.append(
            _issue(
                "subtitle_source_review_coverage_invalid",
                "subtitles.source",
                "Review subtitle sources require pending or verified coverage.",
            )
        )

    source_cues = source.get("cues")
    plan_cues = subtitles.get("cues")
    if not isinstance(source_cues, list) or not isinstance(plan_cues, list):
        issues.append(
            _issue(
                "subtitle_source_cues_invalid",
                "subtitles.source",
                "Subtitle source and plan cues must both be arrays.",
            )
        )
        return
    if not source_cues or not plan_cues:
        issues.append(
            _issue(
                "ready_subtitles_empty" if require_ready else "review_subtitles_empty",
                "subtitles",
                "Review and ready subtitle source and plan must contain cues.",
            )
        )
    allowed_review_statuses = (
        {"verified"} if require_ready else {"review_required", "verified"}
    )
    if any(
        not isinstance(cue, dict)
        or cue.get("review_status") not in allowed_review_statuses
        for cue in source_cues
    ):
        issues.append(
            _issue(
                (
                    "subtitle_source_cue_unverified"
                    if require_ready
                    else "subtitle_source_cue_status_invalid"
                ),
                "subtitles.source",
                "Source subtitle cue review_status cannot render in this mode.",
            )
        )
    if any(
        not isinstance(cue, dict)
        or cue.get("review_status") not in allowed_review_statuses
        for cue in plan_cues
    ):
        issues.append(
            _issue(
                (
                    "subtitle_plan_cue_unverified"
                    if require_ready
                    else "subtitle_plan_cue_status_invalid"
                ),
                "subtitles",
                "Rendered subtitle cue review_status cannot render in this mode.",
            )
        )
    if _subtitle_cue_projection(source_cues) != _subtitle_cue_projection(plan_cues):
        issues.append(
            _issue(
                "subtitle_source_plan_mismatch",
                "subtitles",
                "Rendered subtitle cues must exactly match the source cue projection.",
            )
        )
    if require_ready:
        _validate_ready_subtitle_evidence(
            project,
            subtitles,
            source_path,
            source,
            issues,
            hash_cache,
        )
    else:
        issues.append(
            _warning(
                "subtitle_review_not_release_ready",
                "subtitles",
                "Review subtitles may render in preview, but unresolved readability/layout/approval evidence is not release-ready.",
            )
        )


def validate_enhancement_assets(
    project: Path,
    enhancement_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    project = Path(project).resolve()
    issues: list[dict[str, Any]] = []
    hash_cache: dict[Path, str] = {}
    _validate_overlays(project, enhancement_plan, issues)

    music = enhancement_plan.get("music", {})
    if isinstance(music, dict) and music.get("status") in {"audition", "ready"}:
        _validate_music(
            project,
            music,
            issues,
            hash_cache,
            require_ready=music.get("status") == "ready",
        )

    subtitles = enhancement_plan.get("subtitles", {})
    if isinstance(subtitles, dict) and subtitles.get("status") in {"review", "ready"}:
        _validate_subtitles(
            project,
            subtitles,
            issues,
            hash_cache,
            require_ready=subtitles.get("status") == "ready",
        )
    return issues
