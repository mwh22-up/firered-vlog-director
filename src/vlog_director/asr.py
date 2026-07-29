from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_transcript(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        transcript = json.load(file)
    if "segments" not in transcript:
        raise ValueError("transcript must contain segments")
    return transcript


def transcribe_media(
    media_path: Path,
    *,
    provider: str = "auto",
    model_name: str = "base",
    language: str | None = "zh",
    device: str = "cpu",
    compute_type: str = "int8",
) -> dict[str, Any]:
    if provider == "none":
        return {
            "status": "disabled",
            "provider": "none",
            "model": None,
            "language": language,
            "segments": [],
            "words": [],
        }
    if provider not in {"auto", "faster-whisper"}:
        raise ValueError(f"unsupported ASR provider: {provider}")

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        if provider == "faster-whisper":
            raise RuntimeError(
                "faster-whisper is not installed; install the analysis extra first"
            ) from None
        return {
            "status": "unavailable",
            "provider": "faster-whisper",
            "model": model_name,
            "language": language,
            "segments": [],
            "words": [],
        }

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
    )
    raw_segments, info = model.transcribe(
        str(media_path),
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )

    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments, start=1):
        segment_words = []
        for word in segment.words or []:
            item = {
                "start_sec": round(float(word.start), 3),
                "end_sec": round(float(word.end), 3),
                "text": word.word,
                "probability": round(float(word.probability), 4),
            }
            segment_words.append(item)
            words.append(item)
        segments.append(
            {
                "id": f"asr-{index:04d}",
                "start_sec": round(float(segment.start), 3),
                "end_sec": round(float(segment.end), 3),
                "text": segment.text.strip(),
                "avg_logprob": round(float(segment.avg_logprob), 4),
                "no_speech_probability": round(
                    float(segment.no_speech_prob),
                    4,
                ),
                "words": segment_words,
            }
        )

    return {
        "status": "ready",
        "provider": "faster-whisper",
        "model": model_name,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 4),
        "duration_sec": round(float(info.duration), 3),
        "segments": segments,
        "words": words,
    }
