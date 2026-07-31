from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .protection import validate_protection
from .renderers import load_json, render_enhanced_video, stabilize_video
from .project import (
    guard_project_enhancement,
    guard_project_render,
    init_project,
    init_project_enhancement,
)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def _write_result(result: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if output is None:
        print(serialized)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialized + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vlog-director")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-protection")
    validate.add_argument("--moments", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    validate.add_argument("--policy", type=Path)
    validate.add_argument("--output", type=Path)

    init = subparsers.add_parser("init-project")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--project-id", required=True)

    guard = subparsers.add_parser("guard-render")
    guard.add_argument("--project", type=Path, required=True)
    guard.add_argument("--version", type=int, required=True)
    guard.add_argument("--policy", type=Path)

    init_enhancement = subparsers.add_parser("init-enhancement")
    init_enhancement.add_argument("--project", type=Path, required=True)
    init_enhancement.add_argument("--version", type=int, required=True)

    guard_enhancement = subparsers.add_parser("guard-enhancement")
    guard_enhancement.add_argument("--project", type=Path, required=True)
    guard_enhancement.add_argument("--version", type=int, required=True)

    stabilize = subparsers.add_parser("stabilize")
    stabilize.add_argument("--input", type=Path, required=True)
    stabilize.add_argument("--output", type=Path, required=True)
    stabilize.add_argument("--work-directory", type=Path, required=True)
    stabilize.add_argument("--strength", type=float, default=0.35)
    stabilize.add_argument("--max-crop-percent", type=float, default=8.0)

    render_enhancement = subparsers.add_parser("render-enhancement")
    render_enhancement.add_argument("--project", type=Path, required=True)
    render_enhancement.add_argument("--base-video", type=Path, required=True)
    render_enhancement.add_argument("--plan", type=Path, required=True)
    render_enhancement.add_argument("--output", type=Path, required=True)
    render_enhancement.add_argument("--qa-output", type=Path)

    qa_music = subparsers.add_parser("qa-music")
    qa_music.add_argument("--media", type=Path, required=True)
    qa_music.add_argument("--plan", type=Path, required=True)
    qa_music.add_argument("--output", type=Path, required=True)

    analyze_reference = subparsers.add_parser("analyze-reference")
    analyze_reference.add_argument("--input", type=Path, required=True)
    analyze_reference.add_argument("--source-id", required=True)
    analyze_reference.add_argument("--url", required=True)
    analyze_reference.add_argument("--work-directory", type=Path, required=True)
    analyze_reference.add_argument("--output", type=Path, required=True)
    analyze_reference.add_argument("--portable-output", type=Path)
    analyze_reference.add_argument("--transcript", type=Path)
    analyze_reference.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_reference.add_argument("--asr-model", default="base")
    analyze_reference.add_argument("--language", default="zh")
    analyze_reference.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_reference.add_argument("--visual-fps", type=float, default=2.0)
    analyze_reference.add_argument("--review-directory", type=Path)
    analyze_reference.add_argument("--review-event-limit", type=int, default=12)

    aggregate_reference = subparsers.add_parser("aggregate-reference")
    aggregate_reference.add_argument(
        "--analysis",
        type=Path,
        nargs="+",
        required=True,
    )
    aggregate_reference.add_argument("--profile", type=Path, nargs="*")
    aggregate_reference.add_argument("--output", type=Path, required=True)

    pack_reference = subparsers.add_parser("pack-reference-context")
    pack_reference.add_argument("--analysis", type=Path, required=True)
    pack_reference.add_argument("--output", type=Path, required=True)
    pack_reference.add_argument("--max-characters", type=int, default=180_000)

    aggregate_techniques = subparsers.add_parser("aggregate-techniques")
    aggregate_techniques.add_argument(
        "--study",
        type=Path,
        nargs="+",
        required=True,
    )
    aggregate_techniques.add_argument("--output", type=Path, required=True)
    aggregate_techniques.add_argument("--minimum-source-support", type=int)

    compare_revision = subparsers.add_parser("compare-revision")
    compare_revision.add_argument("--parent", type=Path, required=True)
    compare_revision.add_argument("--candidate", type=Path, required=True)
    compare_revision.add_argument("--minimum-change-ratio", type=float, default=0.08)
    compare_revision.add_argument("--output", type=Path)

    compile_revision_parser = subparsers.add_parser("compile-revision")
    compile_revision_parser.add_argument("--parent", type=Path, required=True)
    compile_revision_parser.add_argument("--profile", type=Path, required=True)
    compile_revision_parser.add_argument("--directives", type=Path, required=True)
    compile_revision_parser.add_argument("--output", type=Path, required=True)
    compile_revision_parser.add_argument("--report", type=Path)

    analyze_target = subparsers.add_parser("analyze-target")
    analyze_target.add_argument("--input", type=Path, required=True)
    analyze_target.add_argument("--source", required=True)
    analyze_target.add_argument("--work-directory", type=Path, required=True)
    analyze_target.add_argument("--output", type=Path, required=True)
    analyze_target.add_argument("--transcript", type=Path)
    analyze_target.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_target.add_argument("--asr-model", default="small")
    analyze_target.add_argument("--language", default="zh")
    analyze_target.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_target.add_argument("--visual-fps", type=float, default=2.0)

    analyze_project = subparsers.add_parser("analyze-project")
    analyze_project.add_argument("--project", type=Path, required=True)
    analyze_project.add_argument("--output-directory", type=Path, required=True)
    analyze_project.add_argument(
        "--asr-provider",
        choices=["auto", "none", "faster-whisper"],
        default="auto",
    )
    analyze_project.add_argument("--asr-model", default="small")
    analyze_project.add_argument("--language", default="zh")
    analyze_project.add_argument("--scene-threshold", type=float, default=0.22)
    analyze_project.add_argument("--visual-fps", type=float, default=2.0)

    direct_timeline_parser = subparsers.add_parser("direct-timeline")
    direct_timeline_parser.add_argument("--parent", type=Path, required=True)
    direct_timeline_parser.add_argument("--analysis", type=Path, nargs="*", default=[])
    direct_timeline_parser.add_argument("--analysis-directory", type=Path)
    direct_timeline_parser.add_argument("--profile", type=Path, required=True)
    direct_timeline_parser.add_argument("--technique-profile", type=Path)
    direct_timeline_parser.add_argument("--moments", type=Path, required=True)
    direct_timeline_parser.add_argument(
        "--feedback",
        type=Path,
        help="Optional explicit user shot decisions; these override reference priors.",
    )
    direct_timeline_parser.add_argument("--version", type=int, required=True)
    direct_timeline_parser.add_argument("--output-directory", type=Path, required=True)
    direct_timeline_parser.add_argument("--target-duration-sec", type=float)
    direct_timeline_parser.add_argument("--minimum-change-ratio", type=float, default=0.08)
    direct_timeline_parser.add_argument(
        "--variants",
        nargs="+",
        choices=["concise", "balanced", "immersive"],
        default=["concise", "balanced", "immersive"],
    )

    approve_timeline_parser = subparsers.add_parser("approve-timeline")
    approve_timeline_parser.add_argument("--candidate", type=Path, required=True)
    approve_timeline_parser.add_argument("--output", type=Path, required=True)
    approve_timeline_parser.add_argument("--receipt", type=Path, required=True)
    approve_timeline_parser.add_argument("--approved-by", required=True)

    plan_music = subparsers.add_parser("plan-music")
    plan_music.add_argument("--plan", type=Path, required=True)
    plan_music.add_argument("--profile", type=Path, required=True)
    plan_music.add_argument("--subtitles", type=Path)
    plan_music.add_argument("--dialogue-padding-sec", type=float, default=0.35)
    plan_music.add_argument("--output", type=Path, required=True)

    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "validate-protection":
        policy = _read_json(args.policy) if args.policy else None
        result = validate_protection(
            _read_json(args.moments),
            _read_json(args.plan),
            policy=policy,
        )
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-project":
        _write_result(init_project(args.root, args.project_id), None)
        return 0
    if args.command == "guard-render":
        policy = _read_json(args.policy) if args.policy else None
        result = guard_project_render(args.project, args.version, policy=policy)
        _write_result(result, None)
        return 0 if result["status"] == "passed" else 2
    if args.command == "init-enhancement":
        _write_result(init_project_enhancement(args.project, args.version), None)
        return 0
    if args.command == "guard-enhancement":
        result = guard_project_enhancement(args.project, args.version)
        _write_result(result, None)
        return 0 if result["status"] == "passed" else 2
    if args.command == "stabilize":
        stabilize_video(
            args.input,
            args.output,
            args.work_directory,
            strength=args.strength,
            max_crop_percent=args.max_crop_percent,
        )
        _write_result({"status": "ready", "output": str(args.output.resolve())}, None)
        return 0
    if args.command == "render-enhancement":
        from .enhancement import validate_enhancement_plan

        project = args.project.resolve()
        enhancement_plan = load_json(args.plan)
        edit_version = enhancement_plan.get("edit_plan_version")
        edit_plan_path = project / "work" / "plans" / f"edit_plan.v{edit_version}.json"
        if not edit_plan_path.is_file():
            raise FileNotFoundError(f"edit plan is missing: {edit_plan_path}")
        validation = validate_enhancement_plan(load_json(edit_plan_path), enhancement_plan)
        if validation["status"] != "passed":
            _write_result(validation, None)
            return 2
        render_enhanced_video(
            project,
            args.base_video.resolve(),
            enhancement_plan,
            args.output.resolve(),
        )
        from .audio_qa import analyze_music_mix, write_music_mix_qa

        qa_report = analyze_music_mix(args.output.resolve(), enhancement_plan)
        qa_output = args.qa_output or args.output.with_suffix(".music-mix-qa.json")
        write_music_mix_qa(qa_report, qa_output.resolve())
        result = {
            "status": "ready" if qa_report["status"] == "passed" else "blocked",
            "output": str(args.output.resolve()),
            "music_mix_qa": str(qa_output.resolve()),
            "qa_status": qa_report["status"],
        }
        _write_result(result, None)
        return 0 if qa_report["status"] == "passed" else 2
    if args.command == "qa-music":
        from .audio_qa import analyze_music_mix, write_music_mix_qa

        report = analyze_music_mix(args.media.resolve(), _read_json(args.plan))
        write_music_mix_qa(report, args.output.resolve())
        _write_result(report, None)
        return 0 if report["status"] == "passed" else 2
    if args.command == "analyze-reference":
        from .reference_learning import (
            analyze_reference,
            write_analysis,
            write_portable_analysis,
        )

        analysis = analyze_reference(
            args.input.resolve(),
            source_id=args.source_id,
            source_url=args.url,
            work_directory=args.work_directory.resolve(),
            transcript_path=args.transcript.resolve() if args.transcript else None,
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        write_analysis(analysis, args.output.resolve())
        if args.portable_output:
            write_portable_analysis(
                analysis,
                args.portable_output.resolve(),
            )
        review_events = 0
        if args.review_directory:
            from .review_pack import build_review_pack

            review = build_review_pack(
                args.input.resolve(),
                analysis,
                args.review_directory.resolve(),
                event_limit=args.review_event_limit,
            )
            review_events = len(review["events"])
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "shots": len(analysis["shots"]),
                "events": len(analysis["events"]),
                "asr_status": analysis["transcription"]["status"],
                "review_events": review_events,
            },
            None,
        )
        return 0
    if args.command == "analyze-target":
        from .reference_learning import analyze_reference, write_analysis

        analysis = analyze_reference(
            args.input.resolve(),
            source_id=Path(args.source).stem,
            source_url="local-target://" + args.source,
            work_directory=args.work_directory.resolve(),
            transcript_path=args.transcript.resolve() if args.transcript else None,
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        analysis["source"]["target_source"] = args.source
        analysis["source"]["aliases"] = [args.source, Path(args.source).name]
        write_analysis(analysis, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source": args.source,
                "shots": len(analysis["shots"]),
                "events": len(analysis["events"]),
                "transcript_status": analysis["transcription"].get("status"),
            },
            None,
        )
        return 0
    if args.command == "analyze-project":
        from .target_project import analyze_target_project

        result = analyze_target_project(
            args.project,
            args.output_directory.resolve(),
            asr_provider=args.asr_provider,
            asr_model=args.asr_model,
            language=args.language or None,
            scene_threshold=args.scene_threshold,
            visual_fps=args.visual_fps,
        )
        _write_result(result, None)
        return 0 if result["status"] == "ready" else 2
    if args.command == "direct-timeline":
        from datetime import datetime, timezone

        from .director_engine import direct_timeline, write_director_result
        from .technique_learning import load_technique_aggregate

        analysis_paths = list(args.analysis)
        if args.analysis_directory:
            analysis_paths.extend(
                sorted(args.analysis_directory.glob("target-analysis.*.json"))
            )
        result = direct_timeline(
            _read_json(args.parent),
            [_read_json(path) for path in analysis_paths],
            _read_json(args.profile),
            _read_json(args.moments),
            version=args.version,
            created_at=datetime.now(timezone.utc).isoformat(),
            target_duration_sec=args.target_duration_sec,
            minimum_change_ratio=args.minimum_change_ratio,
            variants=args.variants,
            technique_profile=(
                load_technique_aggregate(args.technique_profile)
                if args.technique_profile
                else None
            ),
            feedback_document=_read_json(args.feedback) if args.feedback else None,
        )
        write_director_result(result, args.output_directory.resolve())
        _write_result(
            {
                "status": result["status"],
                "recommended_variant": result.get("recommended_variant"),
                "technique_profile_id": result.get("technique_profile_id"),
                "output_directory": str(args.output_directory.resolve()),
                "missing_sources": result.get("missing_sources", []),
            },
            None,
        )
        return 0 if result["status"] in {"ready", "review_required"} else 2
    if args.command == "approve-timeline":
        from .approval import approve_timeline

        result = approve_timeline(
            args.candidate.resolve(),
            args.output.resolve(),
            args.receipt.resolve(),
            approved_by=args.approved_by,
        )
        _write_result(result, None)
        return 0
    if args.command == "compare-revision":
        from .revision import compare_revisions

        result = compare_revisions(
            _read_json(args.parent),
            _read_json(args.candidate),
            minimum_change_ratio=args.minimum_change_ratio,
        )
        _write_result(result, args.output)
        return 0 if result["status"] == "passed" else 2
    if args.command == "compile-revision":
        from .revision import compile_revision

        candidate, report = compile_revision(
            _read_json(args.parent),
            _read_json(args.profile),
            _read_json(args.directives),
        )
        _write_result(candidate, args.output)
        _write_result(report, args.report)
        return 0
    if args.command == "plan-music":
        from .music_direction import build_music_reference

        result = build_music_reference(
            _read_json(args.plan),
            _read_json(args.profile),
            _read_json(args.subtitles) if args.subtitles else None,
            dialogue_padding_sec=args.dialogue_padding_sec,
        )
        _write_result(result, args.output)
        return 0 if result["status"] in {"reference_ready", "no_music_suggestion"} else 2
    if args.command == "aggregate-reference":
        from .profile_aggregation import (
            aggregate_analyses,
            load_analysis,
            load_profile,
            write_aggregate,
        )

        profile = aggregate_analyses(
            [load_analysis(path) for path in args.analysis],
            [load_profile(path) for path in args.profile or []],
        )
        write_aggregate(profile, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source_count": profile["source_count"],
                "shared_rules": len(profile["shared_rules"]),
            },
            None,
        )
        return 0
    if args.command == "pack-reference-context":
        from .model_context import (
            build_reference_context_packet,
            write_reference_context_packet,
        )

        packet = build_reference_context_packet(
            _read_json(args.analysis),
            max_characters=args.max_characters,
        )
        characters = write_reference_context_packet(
            packet,
            args.output.resolve(),
        )
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "serialized_characters": characters,
                "maximum_characters": args.max_characters,
            },
            None,
        )
        return 0
    if args.command == "aggregate-techniques":
        from .technique_learning import (
            aggregate_technique_studies,
            load_technique_study,
            write_technique_aggregate,
        )

        aggregate = aggregate_technique_studies(
            [load_technique_study(path) for path in args.study],
            minimum_source_support=args.minimum_source_support,
        )
        write_technique_aggregate(aggregate, args.output.resolve())
        _write_result(
            {
                "status": "ready",
                "output": str(args.output.resolve()),
                "source_count": aggregate["source_count"],
                "stable_patterns": len(aggregate["stable_patterns"]),
            },
            None,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
