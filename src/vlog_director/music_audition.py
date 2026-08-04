from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .ffmpeg import find_ffmpeg


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("music audition input must be an object")
    return document


def analyze_music_track(media: Path, *, executable: str = "ffmpeg", sample_rate: int = 22050) -> dict[str, Any]:
    ffmpeg = find_ffmpeg(executable)
    completed = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(media), "-t", "120", "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("music audition decode failed")
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    frame_size, hop = 2048, 512
    if samples.size < frame_size * 4:
        return {"tempo": {"bpm": None, "confidence": 0.0}, "speech_band_energy_ratio": 0.0, "beat_grid_sec": []}
    frame_count = 1 + (samples.size - frame_size) // hop
    frames = np.lib.stride_tricks.as_strided(samples, shape=(frame_count, frame_size), strides=(samples.strides[0] * hop, samples.strides[0])).copy()
    windowed = frames * np.hanning(frame_size)
    spectra = np.abs(np.fft.rfft(windowed, axis=1))
    flux = np.maximum(0.0, np.diff(spectra, axis=0)).sum(axis=1)
    flux = flux / max(float(np.max(flux)), 1e-12)
    envelope_rate = sample_rate / hop
    minimum_lag = max(1, round(envelope_rate * 60 / 200))
    maximum_lag = min(len(flux) - 1, round(envelope_rate * 60 / 50))
    bpm: float | None = None
    confidence = 0.0
    beat_grid: list[float] = []
    if maximum_lag > minimum_lag:
        autocorrelation = np.correlate(flux, flux, mode="full")[len(flux) - 1 :]
        region = autocorrelation[minimum_lag : maximum_lag + 1]
        best_lag = minimum_lag + int(np.argmax(region))
        bpm = round(60 * envelope_rate / best_lag, 3)
        confidence = round(float(region.max() / max(autocorrelation[0], 1e-12)), 4)
        offset_index = int(np.argmax(flux[: max(1, best_lag)]))
        duration = samples.size / sample_rate
        cursor = offset_index / envelope_rate
        while cursor <= duration and len(beat_grid) < 256:
            beat_grid.append(round(cursor, 4))
            cursor += best_lag / envelope_rate
    frequencies = np.fft.rfftfreq(frame_size, 1 / sample_rate)
    energy = np.square(spectra)
    speech_band = (frequencies >= 300) & (frequencies <= 3400)
    speech_ratio = float(energy[:, speech_band].sum() / max(energy.sum(), 1e-12))
    return {"tempo": {"bpm": bpm, "confidence": confidence}, "speech_band_energy_ratio": round(min(1.0, speech_ratio), 6), "beat_grid_sec": beat_grid}


def build_music_audition_report(
    *, project: Path, enhancement_plan_path: Path, rights_manifest_path: Path, output_path: Path, executable: str = "ffmpeg"
) -> dict[str, Any]:
    project = project.resolve()
    plan_path = enhancement_plan_path.resolve()
    rights_path = rights_manifest_path.resolve()
    output = output_path.resolve()
    for path, root in ((plan_path, project / "work" / "enhancement"), (rights_path, project / "assets" / "music")):
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError("music audition input escaped its allowed root") from error
        if not path.is_file():
            raise FileNotFoundError(path)
    try:
        output.relative_to((project / "work" / "qa").resolve())
    except ValueError as error:
        raise ValueError("music audition output must stay under work/qa") from error
    if output.exists():
        raise FileExistsError(output)
    plan = _load(plan_path)
    rights = _load(rights_path)
    rights_by_id = {str(asset.get("id")): asset for asset in rights.get("assets", []) if isinstance(asset, dict)}
    assets: list[dict[str, Any]] = []
    for track in plan.get("music", {}).get("tracks", []):
        track_id = str(track["id"])
        source = str(track["source"])
        media = (project / source).resolve()
        try:
            media.relative_to((project / "assets" / "music").resolve())
        except ValueError as error:
            raise ValueError("music track escaped assets/music") from error
        if not media.is_file():
            raise FileNotFoundError(media)
        rights_asset = rights_by_id.get(track_id)
        if rights_asset is None or rights_asset.get("sha256") != _sha(media):
            raise ValueError(f"music rights binding is invalid: {track_id}")
        analysis = analyze_music_track(media, executable=executable)
        assets.append({"id": track_id, "source": source, "sha256": _sha(media), "audition_status": "review_required", **analysis})
    if not assets:
        raise ValueError("music audition requires at least one selected track")
    report = {
        "schema_version": "1.0",
        "contract_version": "music-audition-report-v1",
        "status": "review_required",
        "project_id": str(plan.get("project_id", "")),
        "enhancement_plan_sha256": _sha(plan_path),
        "rights_manifest_sha256": _sha(rights_path),
        "blocking_items": ["human_listening_required"],
        "assets": assets,
        "human_review": {"status": "pending"},
        "speech_intelligibility": {"verified": False, "method": "spectral_masking_risk_only", "statement": "频谱遮蔽风险已计算，对白可懂度仍需人工试听确认。"},
    }
    schema = _load(Path(__file__).with_name("schemas") / "music-audition-report.schema.json")
    if list(Draft202012Validator(schema).iter_errors(report)):
        raise ValueError("music audition report schema invalid")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return report
