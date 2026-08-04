from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError("feedback input must be UTF-8 without BOM")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError("feedback input must be a JSON object")
    return document


def _segments(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(segment) for chapter in plan.get("chapters", []) for segment in chapter.get("segments", [])]


def _interval(segment: dict[str, Any]) -> dict[str, float]:
    return {"in_sec": round(float(segment["in_sec"]), 6), "out_sec": round(float(segment["out_sec"]), 6)}


def _overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    if str(left["source"]).replace("\\", "/").lower() != str(right["source"]).replace("\\", "/").lower():
        return 0.0
    return max(0.0, min(float(left["out_sec"]), float(right["out_sec"])) - max(float(left["in_sec"]), float(right["in_sec"])))


def derive_feedback_facts(
    *,
    project: Path,
    candidate_path: Path,
    final_path: Path,
    output_path: Path,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    plans_root = (project / "work" / "plans").resolve()

    def confined(path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(plans_root)
        except ValueError as error:
            raise ValueError("feedback plans must stay under work/plans") from error
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        return resolved

    candidate_file = confined(candidate_path)
    final_file = confined(final_path)
    baseline_file = confined(baseline_path) if baseline_path else None
    output = output_path.resolve()
    try:
        output.relative_to((project / "work" / "qa").resolve())
    except ValueError as error:
        raise ValueError("feedback facts output must stay under work/qa") from error
    if output.exists():
        raise FileExistsError(output)
    candidate = _load(candidate_file)
    final = _load(final_file)
    baseline = _load(baseline_file) if baseline_file else None
    if candidate.get("project_id") != final.get("project_id"):
        raise ValueError("feedback plans have different project IDs")
    candidate_segments = _segments(candidate)
    final_segments = _segments(final)
    baseline_segments = _segments(baseline) if baseline else []
    matches: dict[int, int] = {}
    used_final: set[int] = set()
    for candidate_index, segment in enumerate(candidate_segments):
        ranked = sorted(
            ((-_overlap(segment, final_segment), final_index) for final_index, final_segment in enumerate(final_segments) if final_index not in used_final),
        )
        if ranked and ranked[0][0] < 0:
            final_index = ranked[0][1]
            matches[candidate_index] = final_index
            used_final.add(final_index)
    operations: list[dict[str, Any]] = []

    def add(kind: str, source: str, **fields: Any) -> None:
        operations.append({"operation_id": f"feedback-{len(operations) + 1:04d}", "type": kind, "source": source, **fields, "review_status": "pending"})

    for index, segment in enumerate(candidate_segments):
        if index not in matches:
            add("remove", str(segment["source"]), candidate=_interval(segment), candidate_index=index)
            continue
        final_index = matches[index]
        final_segment = final_segments[final_index]
        candidate_duration = float(segment["out_sec"]) - float(segment["in_sec"])
        final_duration = float(final_segment["out_sec"]) - float(final_segment["in_sec"])
        delta = final_duration - candidate_duration
        if abs(delta) > 0.001:
            add("extend" if delta > 0 else "shorten", str(segment["source"]), candidate=_interval(segment), final=_interval(final_segment), delta_sec=round(delta, 6), candidate_index=index, final_index=final_index)
        if final_index != index:
            add("reorder", str(segment["source"]), candidate=_interval(segment), final=_interval(final_segment), candidate_index=index, final_index=final_index)
    for final_index, segment in enumerate(final_segments):
        if final_index in used_final:
            continue
        restored = any(_overlap(segment, baseline_segment) > 0 for baseline_segment in baseline_segments)
        add("restore" if restored else "add", str(segment["source"]), final=_interval(segment), final_index=final_index)
    bindings = {
        "candidate": {"path": candidate_file.relative_to(project).as_posix(), "sha256": _sha256_file(candidate_file)},
        "final": {"path": final_file.relative_to(project).as_posix(), "sha256": _sha256_file(final_file)},
    }
    if baseline_file:
        bindings["baseline"] = {"path": baseline_file.relative_to(project).as_posix(), "sha256": _sha256_file(baseline_file)}
    counts = Counter(operation["type"] for operation in operations)
    result = {
        "schema_version": "1.0",
        "contract_version": "director-feedback-facts-v1",
        "status": "review_required",
        "project_id": str(candidate.get("project_id", "")),
        "bindings": bindings,
        "operations": operations,
        "metrics": {"candidate_segment_count": len(candidate_segments), "final_segment_count": len(final_segments), "operation_counts": dict(sorted(counts.items()))},
        "learning_policy": {"automatic_weight_update": False, "human_confirmation_required": True},
    }
    schema = _load(Path(__file__).with_name("schemas") / "director-feedback-facts.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(result))
    if errors:
        raise ValueError("feedback facts schema invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return result
