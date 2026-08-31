
"""
tts.py

Converts script text to speech using edge-tts.

Also produces word-level timing data used by:
    - synced captions
    - mascot mouth-flap timing
    - animation timing

TIMING STRATEGY
---------------
1. Prefer native WordBoundary events from edge-tts.
2. Validate the native timing data.
3. If the voice does not provide usable WordBoundary events, estimate
   timings from the REAL generated audio duration.
4. Estimated timings are sentence-aware and weighted by word length.

IMPORTANT:
The timing JSON remains a PLAIN LIST for compatibility with the existing
assemble_video.py, generate_kids_video.py and check_timing.py.

Example:

[
    {
        "text": "Step",
        "offset_seconds": 0.0,
        "duration_seconds": 0.21
    }
]

Some Edge neural voices do not return WordBoundary events. This is not
treated as a fatal error.
"""

import asyncio
import json
import re
import subprocess
from pathlib import Path

import edge_tts


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum number of native boundaries required before trusting the data.
MIN_VALID_BOUNDARIES = 3

# Native timing coverage must reach at least this percentage of the
# narration's words before we trust it.
MIN_BOUNDARY_COVERAGE = 0.70


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _split_words(text: str) -> list:
    """
    Split narration into spoken words.

    Whitespace is intentionally used because it preserves the narration's
    natural word order.
    """
    return [
        word
        for word in text.split()
        if word.strip()
    ]


def _clean_word_for_weight(word: str) -> str:
    """
    Remove punctuation before calculating timing weight.
    """
    cleaned = re.sub(
        r"[^\w'-]",
        "",
        word,
        flags=re.UNICODE,
    )

    return cleaned or word


def _count_words(text: str) -> int:
    return len(_split_words(text))


# ---------------------------------------------------------------------------
# Edge-TTS synthesis
# ---------------------------------------------------------------------------

async def _synthesize(
    text: str,
    voice: str,
    audio_out: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list:
    """
    Generate audio and collect native WordBoundary events.

    Returns a plain list of timing dictionaries.
    """

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        pitch=pitch,
    )

    word_boundaries = []

    with open(audio_out, "wb") as audio_file:

        async for chunk in communicate.stream():

            chunk_type = chunk.get("type")

            # ---------------------------------------------------------------
            # Audio data
            # ---------------------------------------------------------------

            if chunk_type == "audio":

                data = chunk.get("data")

                if data:
                    audio_file.write(data)

            # ---------------------------------------------------------------
            # Native WordBoundary metadata
            # ---------------------------------------------------------------

            elif chunk_type == "WordBoundary":

                try:

                    word = str(
                        chunk.get("text", "")
                    ).strip()

                    if not word:
                        continue

                    offset_seconds = (
                        float(chunk["offset"])
                        / 10_000_000
                    )

                    duration_seconds = (
                        float(chunk["duration"])
                        / 10_000_000
                    )

                    if offset_seconds < 0:
                        continue

                    if duration_seconds <= 0:
                        continue

                    word_boundaries.append(
                        {
                            "text": word,
                            "offset_seconds": offset_seconds,
                            "duration_seconds": duration_seconds,
                        }
                    )

                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    # Bad metadata should never destroy otherwise valid
                    # generated audio.
                    continue

    return word_boundaries


# ---------------------------------------------------------------------------
# Audio duration
# ---------------------------------------------------------------------------

def _get_audio_duration(audio_path: Path) -> float:
    """
    Get the actual generated audio duration using ffprobe.
    """

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    value = result.stdout.strip()

    if not value:
        raise RuntimeError(
            f"ffprobe returned no duration for {audio_path}"
        )

    duration = float(value)

    if duration <= 0:
        raise RuntimeError(
            f"Invalid audio duration: {duration}"
        )

    return duration


# ---------------------------------------------------------------------------
# Native timing validation
# ---------------------------------------------------------------------------

def _native_timings_are_valid(
    text: str,
    timings: list,
    audio_duration: float,
) -> bool:
    """
    Check whether native WordBoundary metadata is sufficiently complete
    and internally sane.

    We intentionally do not require perfect one-to-one matching because
    Edge-TTS metadata behavior differs between voices.
    """

    if not timings:
        return False

    if len(timings) < MIN_VALID_BOUNDARIES:
        return False

    expected_words = _count_words(text)

    if expected_words <= 0:
        return False

    coverage = len(timings) / expected_words

    if coverage < MIN_BOUNDARY_COVERAGE:
        return False

    previous_end = 0.0
    valid_entries = 0

    for item in timings:

        try:
            start = float(
                item["offset_seconds"]
            )

            duration = float(
                item["duration_seconds"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        end = start + duration

        # Basic validity.
        if start < 0:
            continue

        if duration <= 0:
            continue

        # Allow a small amount of metadata drift.
        if start > audio_duration + 0.5:
            continue

        if end > audio_duration + 1.0:
            continue

        # Word boundaries should move forward through time.
        if start + 0.001 < previous_end:
            continue

        previous_end = end
        valid_entries += 1

    return valid_entries >= MIN_VALID_BOUNDARIES


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

def _split_into_timing_segments(text: str) -> list:
    """
    Split narration into natural sentence segments.

    This makes estimated timing substantially better than simply spreading
    every word across the entire audio duration.
    """

    segments = re.findall(
        r"[^.!?]+(?:[.!?]+|$)",
        text,
        flags=re.UNICODE,
    )

    segments = [
        segment.strip()
        for segment in segments
        if segment.strip()
    ]

    if not segments:
        return [text.strip()]

    return segments


# ---------------------------------------------------------------------------
# Word timing weights
# ---------------------------------------------------------------------------

def _sentence_weights(sentence: str) -> list:
    """
    Calculate approximate speech-time weights for words.

    Longer words receive slightly more time.

    The exponent deliberately keeps the difference moderate. Speech speed
    is NOT directly proportional to character count.
    """

    words = _split_words(sentence)

    if not words:
        return []

    weights = []

    for word in words:

        clean = _clean_word_for_weight(word)

        # Sub-linear character weighting.
        weight = max(
            1.0,
            len(clean) ** 0.70,
        )

        # Small pause adjustments for punctuation.
        if word.endswith((",", ";", ":")):
            weight *= 1.08

        if word.endswith((".", "!", "?")):
            weight *= 1.15

        weights.append(weight)

    return weights


# ---------------------------------------------------------------------------
# Estimated word timings
# ---------------------------------------------------------------------------

def _estimate_word_timings(
    text: str,
    audio_out: Path,
) -> list:
    """
    Estimate word timings from the REAL audio duration.

    Process:

        REAL audio duration
                ↓
        sentence allocation
                ↓
        word-length weighting
                ↓
        punctuation adjustment
                ↓
        word-level timings

    This is an approximation, but it is substantially more useful than
    having no timing data.
    """

    words = _split_words(text)

    if not words:
        return []

    duration = _get_audio_duration(
        audio_out
    )

    if duration <= 0:
        return []

    sentences = _split_into_timing_segments(
        text
    )

    sentence_word_counts = [
        len(_split_words(sentence))
        for sentence in sentences
    ]

    total_words = sum(
        sentence_word_counts
    )

    if total_words <= 0:
        return []

    # ---------------------------------------------------------------
    # Give each sentence a timing weight.
    #
    # Sentences ending with strong punctuation get a small additional
    # allowance to represent natural speech pauses.
    # ---------------------------------------------------------------

    sentence_weights = []

    for sentence, count in zip(
        sentences,
        sentence_word_counts,
    ):

        punctuation_bonus = 1.0

        stripped = sentence.rstrip()

        if stripped.endswith(
            (".", "!", "?")
        ):
            punctuation_bonus = 1.10

        sentence_weights.append(
            max(
                1.0,
                count * punctuation_bonus,
            )
        )

    total_sentence_weight = sum(
        sentence_weights
    )

    timings = []

    global_offset = 0.0

    # ---------------------------------------------------------------
    # Allocate audio duration sentence-by-sentence.
    # ---------------------------------------------------------------

    for sentence, sentence_weight in zip(
        sentences,
        sentence_weights,
    ):

        sentence_words = _split_words(
            sentence
        )

        if not sentence_words:
            continue

        sentence_duration = (
            duration
            * sentence_weight
            / total_sentence_weight
        )

        weights = _sentence_weights(
            sentence
        )

        total_weight = (
            sum(weights)
            or len(sentence_words)
        )

        local_offset = global_offset

        # -----------------------------------------------------------
        # Allocate sentence duration between its words.
        # -----------------------------------------------------------

        for word, weight in zip(
            sentence_words,
            weights,
        ):

            word_duration = (
                sentence_duration
                * weight
                / total_weight
            )

            timings.append(
                {
                    "text": word,
                    "offset_seconds": local_offset,
                    "duration_seconds": word_duration,
                }
            )

            local_offset += word_duration

        global_offset += sentence_duration

    # ---------------------------------------------------------------
    # Make the final word end exactly at the audio duration.
    # ---------------------------------------------------------------

    if timings:

        final = timings[-1]

        final_end = (
            final["offset_seconds"]
            + final["duration_seconds"]
        )

        correction = duration - final_end

        if correction > 0:
            final["duration_seconds"] += correction

    return timings


# ---------------------------------------------------------------------------
# Main synthesis function
# ---------------------------------------------------------------------------

def synthesize_speech(
    text: str,
    voice: str,
    audio_out: str,
    timing_out: str,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> None:
    """
    Generate speech and word timing data.

    IMPORTANT:
    timing_out remains a JSON LIST to preserve compatibility with the
    existing video assembly code.
    """

    if not text or not text.strip():
        raise ValueError(
            "Cannot synthesize empty text."
        )

    if not voice or not voice.strip():
        raise ValueError(
            "TTS voice is empty."
        )

    audio_out = Path(
        audio_out
    )

    timing_out = Path(
        timing_out
    )

    audio_out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    timing_out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ---------------------------------------------------------------
    # Generate audio and attempt native WordBoundary metadata.
    # ---------------------------------------------------------------

    word_boundaries = asyncio.run(
        _synthesize(
            text=text,
            voice=voice,
            audio_out=audio_out,
            rate=rate,
            pitch=pitch,
        )
    )

    # ---------------------------------------------------------------
    # Confirm the generated audio is valid.
    # ---------------------------------------------------------------

    audio_duration = _get_audio_duration(
        audio_out
    )

    # ---------------------------------------------------------------
    # Prefer native timings when reliable.
    # ---------------------------------------------------------------

    if _native_timings_are_valid(
        text=text,
        timings=word_boundaries,
        audio_duration=audio_duration,
    ):

        timings = word_boundaries

        print(
            f"TTS: voice '{voice}' returned "
            f"{len(timings)} reliable native "
            f"WordBoundary events."
        )

        print(
            "TTS: using native word timings."
        )

    else:

        # -----------------------------------------------------------
        # Native metadata unavailable/unreliable.
        # -----------------------------------------------------------

        print(
            f"WARNING: voice '{voice}' returned "
            f"no reliable WordBoundary events "
            f"from edge-tts."
        )

        print(
            "TTS: generating improved estimated "
            "word timings from actual audio duration."
        )

        timings = _estimate_word_timings(
            text=text,
            audio_out=audio_out,
        )

        print(
            f"TTS: generated {len(timings)} "
            f"estimated word timings."
        )

        print(
            f"TTS: actual audio duration = "
            f"{audio_duration:.2f}s"
        )

    # ---------------------------------------------------------------
    # Final safety check.
    # ---------------------------------------------------------------

    if not timings:
        raise RuntimeError(
            "TTS produced audio but no usable "
            "word timings could be generated."
        )

    # IMPORTANT:
    # Write ONLY the timing list.
    #
    # Do NOT wrap it in:
    # {
    #     "words": [...]
    # }
    #
    # Existing video assembly code expects:
    # json.loads(...) -> list
    # ---------------------------------------------------------------

    timing_out.write_text(
        json.dumps(
            timings,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        f"TTS: wrote audio: {audio_out}"
    )

    print(
        f"TTS: wrote timing: {timing_out}"
    )

    print(
        f"TTS: timing entries: {len(timings)}"
    )


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Generate Edge-TTS narration "
            "and word timings."
        )
    )

    parser.add_argument(
        "text_file",
        help=(
            "Path to a .txt file containing "
            "the script"
        ),
    )

    parser.add_argument(
        "voice",
        help=(
            "Edge-TTS voice, e.g. "
            "en-US-AndrewNeural"
        ),
    )

    parser.add_argument(
        "audio_out",
        help="Output MP3 path",
    )

    parser.add_argument(
        "timing_out",
        help="Output timing JSON path",
    )

    parser.add_argument(
        "--rate",
        default="+0%",
        help=(
            'Speech rate, e.g. "-4%%" '
            'or "+5%%"'
        ),
    )

    parser.add_argument(
        "--pitch",
        default="+0Hz",
        help=(
            'Voice pitch, e.g. "-2Hz" '
            'or "+2Hz"'
        ),
    )

    args = parser.parse_args()

    script_text = Path(
        args.text_file
    ).read_text(
        encoding="utf-8"
    )

    synthesize_speech(
        text=script_text,
        voice=args.voice,
        audio_out=args.audio_out,
        timing_out=args.timing_out,
        rate=args.rate,
        pitch=args.pitch,
    )

    print(
        f"Wrote {args.audio_out} "
        f"and {args.timing_out}"
    )

