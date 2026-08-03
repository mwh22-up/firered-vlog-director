from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


SAMPLE_RATE = 48_000
TRACKS = (
    {
        "id": "opening-hook",
        "filename": "nordic-v4-opening-hook.flac",
        "duration_sec": 13.0,
        "bpm": 88,
        "character": "pluck",
        "chords": ((50, 57, 62, 66), (47, 54, 59, 62), (43, 50, 55, 59), (45, 52, 57, 62)),
    },
    {
        "id": "snow-arrival-breath",
        "filename": "nordic-v4-snow-arrival.flac",
        "duration_sec": 11.2,
        "bpm": 82,
        "character": "felt",
        "chords": ((55, 62, 67, 71), (54, 57, 62, 66), (52, 59, 64, 67), (48, 55, 60, 64)),
    },
    {
        "id": "mountain-train-breath",
        "filename": "nordic-v4-mountain-train.flac",
        "duration_sec": 15.2,
        "bpm": 70,
        "character": "air",
        "chords": ((50, 57, 62, 66), (49, 52, 57, 61), (47, 54, 59, 62), (43, 50, 55, 59)),
    },
    {
        "id": "waterfall-transition",
        "filename": "nordic-v4-waterfall.flac",
        "duration_sec": 16.1,
        "bpm": 76,
        "character": "acoustic",
        "chords": ((48, 55, 59, 64), (47, 55, 59, 62), (45, 52, 55, 60), (41, 48, 52, 57)),
    },
    {
        "id": "closing-resolution",
        "filename": "nordic-v4-closing.flac",
        "duration_sec": 21.4,
        "bpm": 66,
        "character": "warm",
        "chords": ((43, 50, 55, 59), (42, 50, 54, 57), (40, 47, 52, 55), (48, 55, 59, 64), (43, 50, 55, 59)),
    },
)


def _frequency(midi_note: int) -> float:
    return 440.0 * math.pow(2.0, (midi_note - 69) / 12.0)


def _pan_gains(pan: float) -> tuple[float, float]:
    angle = (max(-1.0, min(1.0, pan)) + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _add_note(
    mix: np.ndarray,
    *,
    start_sec: float,
    duration_sec: float,
    midi_note: int,
    amplitude: float,
    pan: float,
    instrument: str,
) -> None:
    start = max(0, round(start_sec * SAMPLE_RATE))
    end = min(len(mix), start + max(1, round(duration_sec * SAMPLE_RATE)))
    if end <= start:
        return
    time = np.arange(end - start, dtype=np.float64) / SAMPLE_RATE
    frequency = _frequency(midi_note)
    phase = (midi_note * 0.173 + start_sec * 0.071) % (2.0 * math.pi)

    if instrument == "pad":
        attack = np.minimum(1.0, time / min(1.4, duration_sec * 0.3))
        release = np.minimum(1.0, (duration_sec - time) / min(1.8, duration_sec * 0.35))
        envelope = np.sin(np.minimum(1.0, attack) * math.pi / 2.0) ** 2
        envelope *= np.sin(np.minimum(1.0, np.maximum(0.0, release)) * math.pi / 2.0) ** 2
        vibrato = 0.0022 * np.sin(2.0 * math.pi * 0.18 * time + phase)
        waveform = (
            np.sin(2.0 * math.pi * frequency * time + phase + vibrato)
            + 0.19 * np.sin(2.0 * math.pi * frequency * 2.0 * time + 0.3)
            + 0.08 * np.sin(2.0 * math.pi * frequency * 3.0 * time + 1.1)
        )
    elif instrument == "felt":
        attack = 1.0 - np.exp(-90.0 * time)
        envelope = attack * (0.72 * np.exp(-2.2 * time) + 0.28 * np.exp(-0.28 * time))
        envelope *= np.minimum(1.0, np.maximum(0.0, duration_sec - time) / 0.32)
        waveform = (
            np.sin(2.0 * math.pi * frequency * time + phase)
            + 0.31 * np.sin(2.0 * math.pi * frequency * 2.0 * time + 0.4)
            + 0.13 * np.sin(2.0 * math.pi * frequency * 3.0 * time + 1.3)
        )
    else:
        attack = 1.0 - np.exp(-150.0 * time)
        envelope = attack * np.exp(-3.3 * time / max(0.35, duration_sec))
        envelope *= np.minimum(1.0, np.maximum(0.0, duration_sec - time) / 0.18)
        waveform = (
            np.sin(2.0 * math.pi * frequency * time + phase)
            + 0.38 * np.sin(2.0 * math.pi * frequency * 2.0 * time + 0.2)
            + 0.17 * np.sin(2.0 * math.pi * frequency * 3.0 * time + 0.9)
            + 0.07 * np.sin(2.0 * math.pi * frequency * 4.0 * time + 1.6)
        )

    left, right = _pan_gains(pan)
    signal = (waveform * envelope * amplitude).astype(np.float32)
    mix[start:end, 0] += signal * left
    mix[start:end, 1] += signal * right


def _soft_texture(length: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 1.0, length + 256).astype(np.float32)
    smooth = np.cumsum(noise, dtype=np.float64)
    smooth[128:] -= smooth[:-128]
    smooth = (smooth[255:] / 128.0)[:length].astype(np.float32)
    slow = np.sin(2.0 * math.pi * 0.09 * np.arange(length) / SAMPLE_RATE + seed)
    return smooth * (0.35 + 0.15 * slow.astype(np.float32))


def _compose(track: dict[str, object], seed: int) -> np.ndarray:
    duration = float(track["duration_sec"])
    length = round(duration * SAMPLE_RATE)
    mix = np.zeros((length, 2), dtype=np.float32)
    beat = 60.0 / float(track["bpm"])
    chord_span = beat * 4.0
    chords = tuple(track["chords"])
    character = str(track["character"])

    chord_start = 0.0
    chord_index = 0
    while chord_start < duration:
        chord = chords[chord_index % len(chords)]
        pad_level = 0.024 if character == "air" else 0.017
        for note_index, note in enumerate(chord):
            _add_note(
                mix,
                start_sec=chord_start,
                duration_sec=min(duration - chord_start, chord_span + 1.1),
                midi_note=int(note),
                amplitude=pad_level,
                pan=-0.48 + note_index * 0.32,
                instrument="pad",
            )

        steps = 2 if character == "air" else 4
        for step in range(steps):
            note_index = (step * 2 + chord_index) % len(chord)
            note = int(chord[note_index]) + (12 if step % 2 else 0)
            note_start = chord_start + step * chord_span / steps
            if note_start >= duration:
                break
            instrument = "felt" if character in {"felt", "air", "warm"} else "pluck"
            level = 0.055 if character != "air" else 0.035
            _add_note(
                mix,
                start_sec=note_start,
                duration_sec=min(2.6, duration - note_start),
                midi_note=note,
                amplitude=level,
                pan=-0.32 if step % 2 == 0 else 0.32,
                instrument=instrument,
            )

        if character in {"pluck", "acoustic"}:
            for pulse in range(8):
                pulse_start = chord_start + pulse * beat / 2.0
                if pulse_start >= duration:
                    break
                _add_note(
                    mix,
                    start_sec=pulse_start,
                    duration_sec=min(0.8, duration - pulse_start),
                    midi_note=int(chord[pulse % len(chord)]) + 12,
                    amplitude=0.026 if pulse % 2 else 0.038,
                    pan=-0.52 + (pulse % 4) * 0.34,
                    instrument="pluck",
                )

        chord_start += chord_span
        chord_index += 1

    texture = _soft_texture(length, seed)
    texture_level = 0.0045 if character == "air" else 0.0022
    mix[:, 0] += texture * texture_level
    mix[:, 1] += np.roll(texture, 173) * texture_level

    dry = mix.copy()
    for delay_sec, gain, crossfeed in ((0.19, 0.18, True), (0.37, 0.11, False), (0.61, 0.07, True)):
        delay = round(delay_sec * SAMPLE_RATE)
        if crossfeed:
            mix[delay:, 0] += dry[:-delay, 1] * gain
            mix[delay:, 1] += dry[:-delay, 0] * gain
        else:
            mix[delay:] += dry[:-delay] * gain

    fade = min(round(0.65 * SAMPLE_RATE), length // 3)
    curve = np.sin(np.linspace(0.0, math.pi / 2.0, fade, dtype=np.float32)) ** 2
    mix[:fade] *= curve[:, None]
    mix[-fade:] *= curve[::-1, None]
    mix -= np.mean(mix, axis=0, keepdims=True)
    mix = np.tanh(mix * 1.25)
    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix *= 0.56 / peak
    return mix


def _write_flac(mix: np.ndarray, output: Path, ffmpeg: str) -> None:
    rng = np.random.default_rng(20260803)
    dither = (rng.random(mix.shape) - rng.random(mix.shape)) / 65536.0
    pcm = np.clip(mix + dither, -1.0, 1.0)
    payload = (pcm * 32767.0).astype("<i2").tobytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-map_metadata",
            "-1",
            "-c:a",
            "flac",
            "-compression_level",
            "8",
            str(output),
        ],
        input=payload,
        check=True,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the project-original Nordic v4 score.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg-executable", default="ffmpeg")
    args = parser.parse_args()

    generator_path = Path(__file__).resolve()
    ffmpeg_version = subprocess.run(
        [args.ffmpeg_executable, "-version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    assets = []
    for index, track in enumerate(TRACKS, start=1):
        output = args.output_dir / str(track["filename"])
        _write_flac(_compose(track, 20260803 + index), output, args.ffmpeg_executable)
        assets.append(
            {
                "id": track["id"],
                "path": output.name,
                "duration_sec": track["duration_sec"],
                "sample_rate_hz": SAMPLE_RATE,
                "channels": 2,
                "sha256": _sha256(output),
                "size_bytes": output.stat().st_size,
                "generation": {
                    "bpm": track["bpm"],
                    "character": track["character"],
                    "generator": "scripts/generate-nordic-v4-score.py",
                    "seed": 20260803 + index,
                    "chords_midi": track["chords"],
                },
            }
        )

    manifest = {
        "schema_version": "1.0",
        "document_type": "project_original_music_assets",
        "project_id": "nordic-130-144",
        "version": 4,
        "status": "generated_pending_audition_and_rights_approval",
        "usage_rights": {
            "basis": "project_original_procedural_synthesis",
            "third_party_recordings": False,
            "third_party_samples": False,
            "third_party_midi": False,
            "external_models": False,
            "statement": (
                "Generated locally from the committed synthesis source specifically for this "
                "project; no downloaded music, source recording, or third-party sample is used."
            ),
        },
        "rights_approval": {
            "status": "pending_user_confirmation",
            "rights_holder": None,
            "approved_by": None,
            "approved_at": None,
            "required_scope": ["synchronize", "modify", "render", "distribute_with_project"],
        },
        "generation_environment": {
            "generator": "scripts/generate-nordic-v4-score.py",
            "generator_sha256": _sha256(generator_path),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "ffmpeg": ffmpeg_version,
            "command": (
                "python scripts/generate-nordic-v4-score.py --output-dir "
                "research-artifacts/nordic-130-144/project/assets/music"
            ),
        },
        "assets": assets,
        "created_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = args.output_dir / "music-assets.v4.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
