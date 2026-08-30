"""
tts.py
Converts script text to speech using edge-tts — a free, unlimited wrapper
around Microsoft Edge's online neural voices. No API key required.

Also produces a word-level timing file (.json), primarily from edge-tts's
built-in WordBoundary events -- used later to burn synced captions and, for
kids-channel content, to drive the mascot's mouth-flap timing.

FALLBACK: some neural voices (hi-IN-MadhurNeural among them, per user
reports) don't emit WordBoundary events at all, for any input -- this isn't
an error edge-tts surfaces, the stream just never contains that event type,
so it silently ends up with zero timing data. When that happens we fall
back to an estimated timing: words spread across the actual audio
duration, weighted by character count (longer words get proportionally
more time). It's an approximation, not real per-word alignment, but it
means captions and mouth-sync always have *something* to work with instead
of nothing.
"""
import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts


async def _synthesize(text: str, voice: str, audio_out: Path) -> list:
    communicate = edge_tts.Communicate(text, voice)
    word_boundaries = []

    with open(audio_out, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                word_boundaries.append({
                    "text": chunk["text"],
                    "offset_seconds": chunk["offset"] / 10_000_000,  # ticks -> sec
                    "duration_seconds": chunk["duration"] / 10_000_000,
                })

    return word_boundaries


def _get_audio_duration(audio_path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _estimate_word_timings(text: str, audio_out: Path) -> list:
    """Distributes words evenly across the real audio duration, weighted
    by character count, for voices that give us no WordBoundary events."""
    words = text.split()
    if not words:
        return []
    duration = _get_audio_duration(audio_out)
    weights = [len(w) for w in words]
    total_weight = sum(weights) or len(words)
    offset = 0.0
    timings = []
    for word, weight in zip(words, weights):
        word_duration = duration * (weight / total_weight)
        timings.append({
            "text": word,
            "offset_seconds": offset,
            "duration_seconds": word_duration,
        })
        offset += word_duration
    return timings


def synthesize_speech(text: str, voice: str, audio_out: str, timing_out: str) -> None:
    """Sync wrapper. audio_out should end in .mp3, timing_out in .json"""
    audio_out = Path(audio_out)
    timing_out = Path(timing_out)
    audio_out.parent.mkdir(parents=True, exist_ok=True)

    word_boundaries = asyncio.run(_synthesize(text, voice, audio_out))

    if not word_boundaries:
        print(f"WARNING: voice '{voice}' returned no WordBoundary events "
              f"from edge-tts; falling back to estimated word timings. "
              f"Captions/mouth-sync will be approximate rather than exact "
              f"for this voice.")
        word_boundaries = _estimate_word_timings(text, audio_out)

    timing_out.write_text(json.dumps(word_boundaries, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("text_file", help="Path to a .txt file with the script")
    parser.add_argument("voice", help="e.g. en-US-GuyNeural")
    parser.add_argument("audio_out")
    parser.add_argument("timing_out")
    args = parser.parse_args()

    script_text = Path(args.text_file).read_text()
    synthesize_speech(script_text, args.voice, args.audio_out, args.timing_out)
    print(f"Wrote {args.audio_out} and {args.timing_out}")
