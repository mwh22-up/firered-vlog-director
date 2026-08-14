from __future__ import annotations

import hashlib
import json
from copy import deepcopy
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


def _canonical_object_sha256(document: dict[str, Any]) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_matches(left: str, right: str) -> bool:
    left_path = Path(left)
    right_path = Path(right)
    return bool(
        {left.casefold(), left_path.name.casefold(), left_path.stem.casefold()}
        & {right.casefold(), right_path.name.casefold(), right_path.stem.casefold()}
    )


def _segment_output_duration(segment: dict[str, Any]) -> float:
    return (
        float(segment["out_sec"]) - float(segment["in_sec"])
    ) / float(segment.get("playback_rate", 1.0))


def _expected_rate_candidate(
    base_candidate: dict[str, Any],
    proposal: dict[str, Any],
    *,
    proposal_sha256: str,
    selected_rate: float,
) -> dict[str, Any]:
    if selected_rate not in {1.25, 1.5, 2.0}:
        raise ValueError("selected playback rate is outside the controlled candidate set")
    ranges = proposal.get("affected_ranges")
    if not isinstance(ranges, list) or len(ranges) != 1:
        raise ValueError("playback-rate proposal must contain exactly one affected range")
    affected = ranges[0]
    source = str(affected.get("source", ""))
    start = float(affected["start_sec"])
    end = float(affected["end_sec"])
    output = deepcopy(base_candidate)
    matches: list[tuple[int, int]] = []
    for chapter_index, chapter in enumerate(output.get("chapters", [])):
        for segment_index, segment in enumerate(chapter.get("segments", [])):
            if (
                _source_matches(str(segment.get("source", "")), source)
                and float(segment["in_sec"]) <= start + 1e-6
                and float(segment["out_sec"]) >= end - 1e-6
            ):
                matches.append((chapter_index, segment_index))
    if len(matches) != 1:
        raise ValueError("selected proposal does not map to exactly one base segment")
    chapter_index, segment_index = matches[0]
    original = output["chapters"][chapter_index]["segments"][segment_index]
    replacement: list[dict[str, Any]] = []
    if float(original["in_sec"]) < start - 1e-6:
        replacement.append({**deepcopy(original), "out_sec": start})
    replacement.append(
        {
            **deepcopy(original),
            "in_sec": start,
            "out_sec": end,
            "playback_rate": selected_rate,
            "playback_rate_audio_strategy": "atempo",
            "playback_rate_proposal_sha256": proposal_sha256,
        }
    )
    if end < float(original["out_sec"]) - 1e-6:
        replacement.append({**deepcopy(original), "in_sec": end})
    output["chapters"][chapter_index]["segments"][
        segment_index : segment_index + 1
    ] = replacement
    total_duration = 0.0
    for chapter in output.get("chapters", []):
        duration = sum(
            _segment_output_duration(segment)
            for segment in chapter.get("segments", [])
        )
        chapter["target_duration_sec"] = round(duration, 6)
        total_duration += duration
    output["brief"]["target_duration_sec"] = round(total_duration, 6)
    return output


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

    approved_candidate = candidate
    rate_approval: dict[str, Any] | None = None
    review_contract = review_pack.get("contract_version")
    if review_contract == "directed-candidate-review-pack-v2":
        if selection.get("contract_version") != "directed-preview-selection-v2":
            raise ValueError("playback-rate review pack requires a v2 preview selection")
        report_binding = review_pack["director_report"]
        director_report_file = _confined_file(
            project,
            project / report_binding["path"],
            proposal_root,
            "director report",
        )
        if _file_sha256(director_report_file) != report_binding["sha256"]:
            raise ValueError("director report changed after review-pack creation")
        director_report = _load_object(director_report_file, "director report")
        if (
            director_report.get("project_id") != project_id
            or int(director_report.get("plan_version", 0)) != version
        ):
            raise ValueError("director report project or version binding does not match")
        report_proposals = (
            director_report.get("technique_application", {})
            .get("candidate_applications", {})
            .get(selection["selected_label"], {})
            .get("preview_required_patterns", [])
        )
        report_by_sha = {
            _canonical_object_sha256(item): item
            for item in report_proposals
            if isinstance(item, dict)
        }
        packed_proposals = selected_entry.get("playback_rate_proposals", [])
        packed_by_sha = {
            str(item.get("proposal_sha256")): item
            for item in packed_proposals
            if isinstance(item, dict)
        }
        decisions = selection.get("playback_rate_decisions", [])
        decision_by_sha = {
            str(item.get("proposal_sha256")): item
            for item in decisions
            if isinstance(item, dict)
        }
        if (
            len(decision_by_sha) != len(decisions)
            or set(decision_by_sha) != set(packed_by_sha)
            or set(packed_by_sha) != set(report_by_sha)
        ):
            raise ValueError("playback-rate decisions must cover the exact proposal set")
        for proposal_sha, packed in packed_by_sha.items():
            if (
                packed.get("proposal") != report_by_sha[proposal_sha]
                or _canonical_object_sha256(packed["proposal"]) != proposal_sha
            ):
                raise ValueError("playback-rate proposal content or SHA binding changed")
        selected_rates = [
            (proposal_sha, decision)
            for proposal_sha, decision in decision_by_sha.items()
            if decision.get("decision") == "selected"
        ]
        if len(selected_rates) > 1:
            raise ValueError("only one playback-rate proposal may be selected per revision")
        if selected_rates:
            proposal_sha, decision = selected_rates[0]
            packed = packed_by_sha[proposal_sha]
            matching_rates = [
                row
                for row in packed["rate_candidates"]
                if float(row.get("playback_rate", 0))
                == float(decision["selected_rate"])
            ]
            if len(matching_rates) != 1:
                raise ValueError("selected playback-rate candidate is not unique")
            rate_entry = matching_rates[0]
            expected_decision = {
                "derived_candidate_sha256": rate_entry["derived_candidate"]["sha256"],
                "preview_media_sha256": rate_entry["preview_media"]["sha256"],
                "realized_timeline_sha256": rate_entry["realized_timeline"]["sha256"],
                "cut_qa_sha256": rate_entry["cut_qa"]["sha256"],
            }
            if any(decision.get(key) != value for key, value in expected_decision.items()):
                raise ValueError("selected playback-rate evidence bindings do not match")
            derived_binding = rate_entry["derived_candidate"]
            derived_file = _confined_file(
                project,
                project / derived_binding["path"],
                proposal_root / "rate-candidates" / candidate_sha / proposal_sha,
                "derived rate candidate",
            )
            if _file_sha256(derived_file) != derived_binding["sha256"]:
                raise ValueError("derived rate candidate changed after preview")
            derived_candidate = _load_object(derived_file, "derived rate candidate")
            expected_candidate = _expected_rate_candidate(
                candidate,
                packed["proposal"],
                proposal_sha256=proposal_sha,
                selected_rate=float(decision["selected_rate"]),
            )
            if derived_candidate != expected_candidate:
                raise ValueError("derived rate candidate is not the deterministic proposal result")
            rate_evidence_files: dict[str, Path] = {}
            derived_sha = derived_binding["sha256"]
            for key in ("preview_media", "realized_timeline", "cut_qa"):
                binding = rate_entry[key]
                path = _confined_file(
                    project,
                    project / binding["path"],
                    proposal_root / "previews" / derived_sha,
                    f"playback-rate {key.replace('_', ' ')}",
                )
                if _file_sha256(path) != binding["sha256"]:
                    raise ValueError(
                        f"playback-rate {key.replace('_', ' ')} changed after review"
                    )
                rate_evidence_files[key] = path
            rate_timeline = _load_object(
                rate_evidence_files["realized_timeline"],
                "playback-rate realized timeline",
            )
            if (
                rate_timeline.get("contract_version")
                != "render-candidate-preview-v1"
                or rate_timeline.get("candidate_sha256") != derived_sha
                or rate_timeline.get("plan_sha256") != derived_sha
                or rate_timeline.get("output_identity", {}).get("sha256")
                != rate_entry["preview_media"]["sha256"]
                or rate_timeline.get("av_sync", {}).get("status") != "passed"
                or rate_timeline.get("non_release_marker")
                != {"applied": True, "text": "NON-RELEASE CANDIDATE"}
            ):
                raise ValueError("selected playback-rate timeline evidence is invalid")
            rate_cut = _load_object(
                rate_evidence_files["cut_qa"], "playback-rate cut QA"
            )
            _validate_schema(rate_cut, "directed-cut-qa.schema.json", "playback-rate cut QA")
            if (
                rate_cut.get("plan_sha256") != derived_sha
                or rate_cut.get("realized_timeline_sha256")
                != rate_entry["realized_timeline"]["sha256"]
                or rate_cut.get("base_media", {}).get("sha256")
                != rate_entry["preview_media"]["sha256"]
            ):
                raise ValueError("selected playback-rate cut QA bindings do not match")
            approved_candidate = derived_candidate
            rate_approval = {
                "decision": "selected",
                "proposal_sha256": proposal_sha,
                "selected_rate": decision["selected_rate"],
                "derived_candidate": rate_entry["derived_candidate"],
                "preview_media": rate_entry["preview_media"],
                "realized_timeline": rate_entry["realized_timeline"],
                "cut_qa": rate_entry["cut_qa"],
                "ffmpeg_identity": rate_entry["ffmpeg_identity"],
                "av_sync": rate_entry["av_sync"],
            }
        else:
            rate_approval = {
                "decision": "rejected_all",
                "proposal_sha256s": sorted(decision_by_sha),
            }
    elif selection.get("contract_version") != "directed-preview-selection-v1":
        raise ValueError("v1 candidate review pack requires a v1 preview selection")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(approved_candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    approval_receipt = {
        "schema_version": "1.0",
        "approval_contract_version": (
            "previewed-timeline-approval-v2"
            if review_contract == "directed-candidate-review-pack-v2"
            else "previewed-timeline-approval-v1"
        ),
        "status": "approved",
        "project_id": project_id,
        "plan_version": version,
        "parent_version": parent_version,
        "plan_sha256": plan_sha256(approved_candidate),
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
    if rate_approval is not None:
        approval_receipt["director_report"] = review_pack["director_report"]
        approval_receipt["playback_rate_decision"] = rate_approval
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
