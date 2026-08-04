from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


JOB_RUNTIME_VERSION = "1.0"
JOB_IDENTIFIER = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{12}$")
SUPPORTED_OPERATIONS = frozenset(
    {
        "analyze-reference",
        "analyze-target",
        "audition-music",
        "qa-effects",
        "qa-release-visual",
        "render-enhancement",
        "render-effects",
    }
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
JobHandler = Callable[[Mapping[str, Any], Callable[[], bool]], Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label} must be UTF-8 without BOM")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ValueError(f"{label} must be a JSON object")
    return document


def _write_json_atomic(path: Path, document: Mapping[str, Any], *, new: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if new and path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(
                document,
                output,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        if new and path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_status(path: Path, status: str, **fields: Any) -> None:
    _write_json_atomic(
        path,
        {
            "runtime_version": JOB_RUNTIME_VERSION,
            "document_type": "durable_job_status",
            "status": status,
            "updated_at": _utc_now(),
            **fields,
        },
    )


def _new_job_directory(project: Path, job_type: str) -> Path:
    root = project.resolve() / "work" / "jobs" / job_type
    root.mkdir(parents=True, exist_ok=True)
    for _ in range(32):
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
        candidate = root / identifier
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate.resolve()
    raise FileExistsError("unable to allocate a unique durable job directory")


def _validated_job(job_spec: Path, spec: Mapping[str, Any]) -> tuple[Path, Path]:
    required = {"runtime_version", "operation", "project", "job_type", "output_directory", "arguments"}
    unknown = sorted(set(spec) - required)
    missing = sorted(required - set(spec))
    if unknown or missing:
        raise ValueError(f"durable job fields are invalid: unknown={unknown}, missing={missing}")
    if spec.get("runtime_version") != JOB_RUNTIME_VERSION:
        raise ValueError("durable job runtime version is unsupported")
    operation = str(spec.get("operation"))
    job_type = str(spec.get("job_type"))
    if operation not in SUPPORTED_OPERATIONS or job_type != operation:
        raise ValueError("durable job operation is not supported")
    if not isinstance(spec.get("arguments"), dict):
        raise ValueError("durable job arguments must be an object")
    project = Path(str(spec["project"])).resolve()
    jobs_root = (project / "work" / "jobs" / job_type).resolve()
    try:
        relative = job_spec.relative_to(jobs_root)
    except ValueError as error:
        raise ValueError("durable job spec escaped its project job root") from error
    if len(relative.parts) != 2 or relative.parts[1] != "job.json" or not JOB_IDENTIFIER.fullmatch(relative.parts[0]):
        raise ValueError("durable job spec must be <unique-id>/job.json")
    job_directory = job_spec.parent.resolve()
    if Path(str(spec["output_directory"])).resolve() != job_directory:
        raise ValueError("durable job output_directory must equal its immutable job directory")
    return project, job_directory


def _default_handlers() -> dict[str, JobHandler]:
    def render_effects(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .hyperframes_effects import render_hyperframes_compositions

        return render_hyperframes_compositions(
            Path(str(arguments["project"])),
            Path(str(arguments["plan"])),
            Path(str(arguments["composition_manifest"])),
            executable=str(arguments.get("hyperframes_executable", "hyperframes")),
            quality=str(arguments.get("quality", "standard")),
        )

    def qa_effects(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .effect_visual_qa import qa_hyperframes_effects

        return qa_hyperframes_effects(
            Path(str(arguments["project"])),
            Path(str(arguments["plan"])),
            Path(str(arguments["render_manifest"])),
            Path(str(arguments["base_video"])),
            Path(str(arguments["output_directory"])),
            executable=str(arguments.get("ffmpeg_executable", "ffmpeg")),
            layout_qa_path=(Path(str(arguments["layout_qa"])) if arguments.get("layout_qa") else None),
            protected_regions_path=(Path(str(arguments["protected_regions"])) if arguments.get("protected_regions") else None),
        )

    def analyze(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .reference_learning import analyze_reference, write_analysis, write_portable_analysis

        output = Path(str(arguments["output"])).resolve()
        portable_raw = arguments.get("portable_output")
        portable = Path(str(portable_raw)).resolve() if portable_raw else None
        conflicts = [path for path in (output, portable) if path is not None and path.exists()]
        if conflicts:
            raise FileExistsError("analysis output already exists: " + ", ".join(str(path) for path in conflicts))
        result = analyze_reference(
            Path(str(arguments["input"])).resolve(),
            source_id=str(arguments["source_id"]),
            source_url=str(arguments["source_url"]),
            work_directory=Path(str(arguments["work_directory"])).resolve(),
            transcript_path=(Path(str(arguments["transcript"])).resolve() if arguments.get("transcript") else None),
            asr_provider=str(arguments.get("asr_provider", "auto")),
            asr_model=str(arguments.get("asr_model", "small")),
            language=(str(arguments["language"]) if arguments.get("language") else None),
            scene_threshold=float(arguments.get("scene_threshold", 0.22)),
            visual_fps=float(arguments.get("visual_fps", 2.0)),
            audio_window_sec=float(arguments.get("audio_window_sec", 0.5)),
        )
        if arguments.get("target_source"):
            target_source = str(arguments["target_source"])
            result["source"]["target_source"] = target_source
            result["source"]["aliases"] = [target_source, Path(target_source).name]
        if cancelled():
            raise RuntimeError("durable job cancellation requested before evidence write")
        write_analysis(result, output)
        if portable is not None:
            write_portable_analysis(result, portable)
        review_events = 0
        if arguments.get("review_directory"):
            review_directory = Path(str(arguments["review_directory"])).resolve()
            if review_directory.exists() and any(review_directory.iterdir()):
                raise FileExistsError("analysis review directory is not empty")
            from .review_pack import build_review_pack

            review = build_review_pack(
                Path(str(arguments["input"])).resolve(),
                result,
                review_directory,
                event_limit=int(arguments.get("review_event_limit", 12)),
            )
            review_events = len(review["events"])
        return {
            "status": "ready",
            "output": str(output),
            "portable_output": str(portable) if portable is not None else None,
            "shot_count": len(result.get("shots", [])),
            "event_count": len(result.get("events", [])),
            "review_events": review_events,
        }

    def render_enhancement_job(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .enhancement_runtime import render_enhancement

        return render_enhancement(
            project=Path(str(arguments["project"])),
            base_video=Path(str(arguments["base_video"])),
            plan_path=Path(str(arguments["plan"])),
            output=Path(str(arguments["output"])),
            qa_output=(Path(str(arguments["qa_output"])) if arguments.get("qa_output") else None),
            ffmpeg_executable=str(arguments.get("ffmpeg_executable", "ffmpeg")),
            realized_timeline_path=(Path(str(arguments["realized_timeline"])) if arguments.get("realized_timeline") else None),
            mode=str(arguments.get("mode", "preview")),
            video_preset=str(arguments.get("video_preset", "medium")),
            video_crf=int(arguments.get("video_crf", 18)),
        )

    def qa_release_visual_job(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .release_visual_qa import qa_release_visual

        return qa_release_visual(
            project=Path(str(arguments["project"])),
            media_path=Path(str(arguments["media"])),
            enhancement_plan_path=Path(str(arguments["enhancement_plan"])),
            output_directory=Path(str(arguments["output_directory"])),
            realized_timeline_path=(Path(str(arguments["realized_timeline"])) if arguments.get("realized_timeline") else None),
            directed_base_contract_path=(Path(str(arguments["directed_base_contract"])) if arguments.get("directed_base_contract") else None),
            executable=str(arguments.get("ffmpeg_executable", "ffmpeg")),
        )

    def audition_music_job(arguments: Mapping[str, Any], cancelled: Callable[[], bool]) -> Mapping[str, Any]:
        if cancelled():
            return {"status": "cancelled"}
        from .music_audition import build_music_audition_report

        return build_music_audition_report(
            project=Path(str(arguments["project"])),
            enhancement_plan_path=Path(str(arguments["enhancement_plan"])),
            rights_manifest_path=Path(str(arguments["rights_manifest"])),
            output_path=Path(str(arguments["output"])),
            executable=str(arguments.get("ffmpeg_executable", "ffmpeg")),
        )

    return {
        "render-effects": render_effects,
        "qa-effects": qa_effects,
        "qa-release-visual": qa_release_visual_job,
        "render-enhancement": render_enhancement_job,
        "analyze-reference": analyze,
        "analyze-target": analyze,
        "audition-music": audition_music_job,
    }


def submit_durable_job(
    *,
    project: Path,
    operation: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported durable operation: {operation}")
    project = project.resolve()
    job_directory = _new_job_directory(project, operation)
    spec_path = job_directory / "job.json"
    status_path = job_directory / "status.json"
    worker_log_path = job_directory / "worker.log"
    spec = {
        "runtime_version": JOB_RUNTIME_VERSION,
        "operation": operation,
        "job_type": operation,
        "project": str(project),
        "output_directory": str(job_directory),
        "arguments": dict(arguments),
    }
    _write_json_atomic(spec_path, spec, new=True)
    _write_status(status_path, "queued", job_spec=str(spec_path))
    command = [sys.executable, "-m", "vlog_director.durable_jobs", "--job-spec", str(spec_path)]
    worker_log = worker_log_path.open("x", encoding="utf-8", newline="\n")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": worker_log,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    except Exception as error:
        _write_status(
            status_path,
            "failed",
            job_spec=str(spec_path),
            error_type=type(error).__name__,
            error_message=str(error),
            exit_code=1,
        )
        raise
    finally:
        worker_log.close()
    return {
        "status": "queued",
        "pid": process.pid,
        "job_spec": str(spec_path),
        "job_status": str(status_path),
        "worker_log": str(worker_log_path),
        "output_directory": str(job_directory),
    }


def request_job_cancel(job_directory: Path) -> dict[str, Any]:
    directory = job_directory.resolve()
    spec_path = directory / "job.json"
    spec = _read_json(spec_path, "durable job spec")
    _validated_job(spec_path, spec)
    status = _read_json(directory / "status.json", "durable job status")
    if status.get("status") in TERMINAL_STATUSES:
        raise ValueError("terminal durable jobs cannot be cancelled")
    marker = directory / "cancel.json"
    _write_json_atomic(
        marker,
        {"runtime_version": JOB_RUNTIME_VERSION, "requested_at": _utc_now()},
        new=True,
    )
    return {"status": "cancel_requested", "job": str(directory)}


def run_durable_job(job_spec: Path, *, handlers: Mapping[str, JobHandler] | None = None) -> dict[str, Any]:
    spec_path = job_spec.resolve()
    spec = _read_json(spec_path, "durable job spec")
    _, job_directory = _validated_job(spec_path, spec)
    status_path = job_directory / "status.json"
    status = _read_json(status_path, "durable job status")
    if status.get("status") != "queued":
        raise ValueError("durable job must be queued and cannot be replayed")
    for conflict in (job_directory / "claim.json", job_directory / "result.json"):
        if conflict.exists():
            raise FileExistsError(conflict)
    _write_json_atomic(
        job_directory / "claim.json",
        {"runtime_version": JOB_RUNTIME_VERSION, "claimed_at": _utc_now()},
        new=True,
    )
    _write_status(status_path, "running", job_spec=str(spec_path), worker_pid=os.getpid())

    def cancelled() -> bool:
        return (job_directory / "cancel.json").is_file()

    try:
        if cancelled():
            _write_status(status_path, "cancelled", job_spec=str(spec_path), exit_code=3)
            return {"status": "cancelled"}
        selected = dict(handlers or _default_handlers())
        handler = selected.get(str(spec["operation"]))
        if handler is None:
            raise ValueError("durable job handler is unavailable")
        result = dict(handler(spec["arguments"], cancelled))
        if cancelled() or result.get("status") == "cancelled":
            _write_status(status_path, "cancelled", job_spec=str(spec_path), exit_code=3)
            return {"status": "cancelled"}
        _write_json_atomic(job_directory / "result.json", result, new=True)
    except Exception as error:
        _write_status(
            status_path,
            "failed",
            job_spec=str(spec_path),
            error_type=type(error).__name__,
            error_message=str(error),
            exit_code=1,
        )
        raise
    _write_status(
        status_path,
        "completed",
        job_spec=str(spec_path),
        result=str(job_directory / "result.json"),
        exit_code=0,
    )
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(description="Internal durable production worker")
    parser.add_argument("--job-spec", type=Path, required=True)
    arguments = parser.parse_args()
    run_durable_job(arguments.job_spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
