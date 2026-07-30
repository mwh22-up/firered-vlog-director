from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .reference_learning import analyze_reference, write_analysis


def analyze_target_project(
    project: Path,
    output_directory: Path,
    *,
    asr_provider: str = "auto",
    asr_model: str = "small",
    language: str | None = "zh",
    scene_threshold: float = 0.22,
    visual_fps: float = 2.0,
) -> dict[str, Any]:
    project = project.resolve()
    assets_path = project / "work" / "assets.json"
    if not assets_path.is_file():
        raise FileNotFoundError(
            f"target assets are missing: {assets_path}; run pipeline ingest first"
        )
    assets_document = json.loads(assets_path.read_text(encoding="utf-8-sig"))
    output_directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for asset in assets_document.get("assets", []):
        source_name = str(asset["source_relative"])
        asset_id = str(asset["asset_id"])
        media = Path(asset.get("proxy") or asset["source"]).resolve()
        transcript = project / "work" / "transcripts" / f"{asset_id}.json"
        output = output_directory / f"target-analysis.{Path(source_name).stem}.json"
        if output.is_file():
            results.append({"source": source_name, "output": str(output), "status": "cached"})
            continue
        try:
            analysis = analyze_reference(
                media,
                source_id=Path(source_name).stem,
                source_url="local-target://" + source_name,
                work_directory=output_directory / "features" / asset_id,
                transcript_path=transcript if transcript.is_file() else None,
                asr_provider=asr_provider,
                asr_model=asr_model,
                language=language,
                scene_threshold=scene_threshold,
                visual_fps=visual_fps,
            )
            analysis["source"]["target_source"] = f"raw/{source_name}"
            analysis["source"]["aliases"] = [source_name, f"raw/{source_name}"]
            write_analysis(analysis, output)
            results.append(
                {
                    "source": source_name,
                    "output": str(output),
                    "status": "ready",
                    "shots": len(analysis["shots"]),
                    "events": len(analysis["events"]),
                    "transcript_status": analysis["transcription"].get("status"),
                }
            )
        except Exception as exc:  # isolate one bad source
            failures.append({"source": source_name, "error": str(exc)})
    report = {
        "schema_version": "1.0",
        "status": "ready" if not failures else "partial",
        "project": str(project),
        "asset_count": len(assets_document.get("assets", [])),
        "analysis_count": len(results),
        "failure_count": len(failures),
        "analyses": results,
        "failures": failures,
    }
    (output_directory / "target-analysis-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
