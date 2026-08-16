"""
tts.py
Converts script text to speech using edge-tts — a free, unlimited wrapper
around Microsoft Edge's online neural voices. No API key required.

Also produces a word-level timing file (.json) using edge-tts's built-in
word-boundary events, which we use later to burn synced captions onto
the video without needing a separate transcription pass.
"""
import asyncio
import json
from pathlib import Path

import edge_tts


async def _synthesize(text: str, voice: str, audio_out: Path, timing_out: Path):
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

    timing_out.write_text(json.dumps(word_boundaries, indent=2))


def synthesize_speech(text: str, voice: str, audio_out: str, timing_out: str) -> None:
    """Sync wrapper. audio_out should end in .mp3, timing_out in .json"""
    audio_out = Path(audio_out)
    timing_out = Path(timing_out)
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize(text, voice, audio_out, timing_out))


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
