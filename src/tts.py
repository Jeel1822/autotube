"""
tts.py

Converts script text to speech using edge-tts, with an Azure Speech
REST fallback when edge-tts is blocked (e.g. HTTP 403 from CI runners).

Also produces word-level timing data used by:
    - synced captions
    - mascot mouth-flap timing
    - animation timing

ENGINE STRATEGY
---------------
1. Try edge-tts (up to EDGE_TTS_ATTEMPTS times, fresh Communicate object
   each time).
2. If every attempt fails, fall back to Azure Speech (REST). Requires the
   AZURE_SPEECH_KEY and AZURE_SPEECH_REGION environment variables.
   Uses the same neural voice names, so the channel sounds the same.

TIMING STRATEGY
---------------
1. Prefer native WordBoundary events from edge-tts.
2. Validate the native timing data.
3. If the voice does not provide usable WordBoundary events (always the
   case on the Azure REST fallback), estimate timings from the REAL
   generated audio duration.
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
import os
import re
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import edge_tts
import requests


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum number of native boundaries required before trusting the data.
MIN_VALID_BOUNDARIES = 3

# Native timing coverage must reach at least this percentage of the
# narration's words before we trust it.
MIN_BOUNDARY_COVERAGE = 0.70

# How many times to try edge-tts before falling back to Azure.
EDGE_TTS_ATTEMPTS = 2

# Azure REST output format (mono MP3, compatible with the existing pipeline).
AZURE_OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"


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
        # edge-tts 7.x defaults to SentenceBoundary, which this code
        # ignores. Ask for word-level events explicitly.
        boundary="WordBoundary",
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


async def _synthesize_with_retry(
    text: str,
    voice: str,
    audio_out: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
    attempts: int = EDGE_TTS_ATTEMPTS,
) -> list:
    """
    Retry edge-tts, creating a fresh Communicate object on every attempt.

    Handshake 403s (blocked IP, token/clock-skew problems) and transient
    network errors are retried with a short backoff. The last exception is
    re-raised so the caller can decide to fall back to another engine.
    """

    last_exc = None

    for attempt in range(attempts):

        try:
            return await _synthesize(
                text=text,
                voice=voice,
                audio_out=audio_out,
                rate=rate,
                pitch=pitch,
            )

        except Exception as exc:
            last_exc = exc

            print(
                f"WARNING: edge-tts attempt {attempt + 1}/{attempts} "
                f"failed: {type(exc).__name__}: {exc}"
            )

            if attempt < attempts - 1:
                await asyncio.sleep(2 ** attempt)

    raise last_exc


# ---------------------------------------------------------------------------
# Azure Speech fallback
# ---------------------------------------------------------------------------

def _synthesize_azure(
    text: str,
    voice: str,
    audio_out: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list:
    """
    Fallback TTS using the Azure Speech REST API.

    Uses the same neural voice names as edge-tts (e.g. en-US-AndrewNeural).

    The REST API returns no word boundaries, so this returns an empty list.
    synthesize_speech() then builds estimated timings from the real audio
    duration, exactly as it does for voices without WordBoundary support.
    """

    key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    region = os.environ.get("AZURE_SPEECH_REGION", "").strip()

    if not key or not region:
        raise RuntimeError(
            "Azure fallback unavailable: set the AZURE_SPEECH_KEY and "
            "AZURE_SPEECH_REGION environment variables."
        )

    # en-US-AndrewNeural -> en-US
    lang = "-".join(voice.split("-")[:2])

    ssml = (
        f"<speak version='1.0' xml:lang='{lang}' "
        f"xmlns='http://www.w3.org/2001/10/synthesis'>"
        f"<voice name='{voice}'>"
        f"<prosody rate='{rate}' pitch='{pitch}'>"
        f"{escape(text)}"
        f"</prosody>"
        f"</voice>"
        f"</speak>"
    )

    response = requests.post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": AZURE_OUTPUT_FORMAT,
            "User-Agent": "autotube",
        },
        data=ssml.encode("utf-8"),
        timeout=60,
    )

    response.raise_for_status()

    if not response.content:
        raise RuntimeError("Azure Speech returned an empty audio body.")

    Path(audio_out).write_bytes(response.content)

    print(
        f"TTS: Azure Speech fallback wrote "
        f"{len(response.content)} bytes of audio."
    )

    return []


# ---------------------------------------------------------------------------
# Gemini TTS (uses the same GEMINI_API_KEY as the rest of the pipeline)
# ---------------------------------------------------------------------------

# Preview models; names change, so the list is overridable. Tried in order.
GEMINI_TTS_MODELS = [
    m.strip() for m in os.environ.get(
        "GEMINI_TTS_MODELS",
        "gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts",
    ).split(",") if m.strip()
]
GEMINI_TTS_VOICE = os.environ.get("GEMINI_TTS_VOICE", "Charon")
GEMINI_TTS_STYLE = os.environ.get(
    "GEMINI_TTS_STYLE",
    "Say in a calm, curious, awe-struck documentary narrator voice, at a "
    "steady and engaging pace",
)
GEMINI_TTS_MAX_CHARS = 2500          # per request (docs cap a text field at ~4 KB)
GEMINI_TTS_CHUNK_WAIT = int(os.environ.get("GEMINI_TTS_CHUNK_WAIT", "31"))


def _split_for_gemini(text: str, limit: int = GEMINI_TTS_MAX_CHARS) -> list:
    """Split at sentence boundaries into chunks <= limit characters."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, cur = [], ""
    for sent in sentences:
        if cur and len(cur) + 1 + len(sent) > limit:
            chunks.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _gemini_pcm(client, model: str, prompt_text: str, voice_name: str):
    """One TTS request. Returns (pcm_bytes, sample_rate)."""
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=prompt_text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )
    if not response.candidates or not response.candidates[0].content or not response.candidates[0].content.parts:
        raise RuntimeError("Gemini TTS returned an empty candidate or missing parts.")
    part = response.candidates[0].content.parts[0]
    inline = getattr(part, "inline_data", None)
    if inline is None or not inline.data:
        raise RuntimeError("Gemini TTS returned no audio data.")
    data = inline.data
    if isinstance(data, str):
        import base64
        data = base64.b64decode(data)
    rate = 24000  # Gemini TTS returns 24 kHz, 16-bit, mono PCM
    m = re.search(r"rate=(\d+)", getattr(inline, "mime_type", "") or "")
    if m:
        rate = int(m.group(1))
    return bytes(data), rate


def _synthesize_gemini(
    text: str,
    voice: str,
    audio_out: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list:
    """
    Gemini text-to-speech (preview). Free tier has tight limits (roughly
    2 requests/minute and ~50/day, per Google's preview docs), which is
    plenty for 3 Shorts a day. Returns no word boundaries, so
    synthesize_speech() builds estimated timings from the real duration.

    Env overrides: GEMINI_TTS_VOICE (default Charon), GEMINI_TTS_STYLE,
    GEMINI_TTS_MODELS.
    """
    import shutil
    import subprocess
    import time

    from src.gemini_client import (
        get_client, _is_transient, _is_model_gone,
    )

    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("Gemini TTS needs GEMINI_API_KEY.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Gemini TTS needs ffmpeg on PATH.")

    client = get_client()
    chunks = _split_for_gemini(text)
    n_words = max(1, len(text.split()))
    voice_name = GEMINI_TTS_VOICE
    last_exc = None

    for model in GEMINI_TTS_MODELS:
        try:
            pcm_parts, sr = [], 24000
            for i, chunk in enumerate(chunks):
                if i > 0:
                    time.sleep(GEMINI_TTS_CHUNK_WAIT)  # free-tier RPM
                words = max(1, len(chunk.split()))
                # Try with the style instruction first; if the clip is
                # suspiciously slow (the model read the instruction aloud),
                # retry once with the bare text.
                for use_style in (True, False):
                    prompt_text = (
                        f"{GEMINI_TTS_STYLE}: {chunk}" if use_style else chunk
                    )
                    for attempt in range(3):
                        try:
                            pcm, sr = _gemini_pcm(
                                client, model, prompt_text, voice_name)
                            break
                        except Exception as exc:
                            if attempt < 2 and _is_transient(exc):
                                wait = (5, 20)[attempt]
                                print(f"Gemini TTS transient error on {model}; "
                                      f"retrying in {wait}s...")
                                time.sleep(wait)
                                continue
                            raise
                    seconds = len(pcm) / (sr * 2)
                    if use_style and words / max(seconds, 0.1) < 1.6:
                        print(f"Gemini TTS: clip is {seconds:.1f}s for "
                              f"{words} words (too slow); the style prompt "
                              f"may have been read aloud. Retrying bare.")
                        continue
                    break
                pcm_parts.append(pcm)
            pcm_all = b"".join(pcm_parts)
            break
        except Exception as exc:
            last_exc = exc
            if _is_model_gone(exc) or _is_transient(exc):
                print(f"Gemini TTS model {model} unavailable "
                      f"({type(exc).__name__}); trying the next one.")
                continue
            raise
    else:
        raise RuntimeError(f"Gemini TTS failed on all models: {last_exc}")

    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error",
         "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
         "-b:a", "128k", str(audio_out)],
        input=pcm_all, check=True, timeout=300,
    )
    print(f"TTS: Gemini TTS ({model}, voice {voice_name}) wrote "
          f"{Path(audio_out).stat().st_size} bytes of audio "
          f"(~{len(pcm_all) / (sr * 2):.1f}s for {n_words} words).")
    return []


# ---------------------------------------------------------------------------
# Local offline fallback (no account, key, card or internet)
# ---------------------------------------------------------------------------

def _rate_to_wpm(rate: str, base_wpm: int = 175) -> int:
    """edge-tts style '+10%' / '-5%' -> macOS `say` words-per-minute."""
    try:
        pct = float(str(rate).replace("%", "").replace("+", ""))
    except ValueError:
        pct = 0.0
    return max(80, min(400, int(base_wpm * (1 + pct / 100))))


def _synthesize_local(
    text: str,
    voice: str,
    audio_out: Path,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> list:
    """
    Last-resort offline TTS. Tries, in order:
      1. Piper, if PIPER_MODEL points at a downloaded .onnx voice
         (pip install piper-tts) -- best quality, fully offline.
      2. macOS `say` -- built in, no install. Set LOCAL_TTS_VOICE to a
         voice name (e.g. "Ava (Premium)", "Evan (Enhanced)"; download
         better ones in System Settings > Accessibility > Spoken Content
         > System Voice > Manage Voices). `say -v ?` lists them.

    Neither returns word boundaries, so this returns [] and
    synthesize_speech() builds estimated timings from the real audio
    duration, exactly like the Azure fallback.
    """
    import shutil
    import subprocess
    import tempfile

    audio_out = Path(audio_out)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Local TTS fallback needs ffmpeg on PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw"

        piper_model = os.environ.get("PIPER_MODEL", "").strip()
        piper_bin = shutil.which("piper")

        if piper_model and piper_bin:
            raw = raw.with_suffix(".wav")
            subprocess.run(
                [piper_bin, "-m", piper_model, "-f", str(raw)],
                input=text.encode("utf-8"),
                check=True,
                timeout=300,
            )
            engine = "Piper"

        elif shutil.which("say"):
            raw = raw.with_suffix(".aiff")
            cmd = ["say", "-o", str(raw), "-r", str(_rate_to_wpm(rate))]
            local_voice = os.environ.get("LOCAL_TTS_VOICE", "").strip()
            if local_voice:
                cmd += ["-v", local_voice]
            subprocess.run(
                cmd, input=text.encode("utf-8"), check=True, timeout=300
            )
            engine = f"macOS say ({local_voice or 'default voice'})"

        else:
            raise RuntimeError(
                "No local TTS available: set PIPER_MODEL (and install "
                "piper-tts) or run on macOS where `say` exists."
            )

        if not raw.exists() or raw.stat().st_size == 0:
            raise RuntimeError("Local TTS produced no audio.")

        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw),
             "-ar", "44100", "-ac", "1", "-b:a", "128k", str(audio_out)],
            check=True,
            timeout=300,
        )

    print(f"TTS: local fallback ({engine}) wrote {audio_out.stat().st_size} "
          f"bytes of audio.")
    return []


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
    #
    # edge-tts first (with retries). If it is blocked or down, fall
    # back to Azure Speech, which returns audio only (no boundaries).
    # ---------------------------------------------------------------

    # Provider order is configurable: TTS_ORDER="edge,gemini,azure,local"
    # (default). To try the Gemini voice first: TTS_ORDER="gemini,edge,azure,local".
    # Only edge-tts returns native word timings; the others return [] and
    # estimated timings are built from the real audio duration.
    def _edge():
        return asyncio.run(
            _synthesize_with_retry(
                text=text,
                voice=voice,
                audio_out=audio_out,
                rate=rate,
                pitch=pitch,
            )
        )

    providers = {
        "edge": ("edge-tts", _edge),
        "gemini": ("Gemini TTS", lambda: _synthesize_gemini(
            text=text, voice=voice, audio_out=audio_out,
            rate=rate, pitch=pitch)),
        "azure": ("Azure Speech", lambda: _synthesize_azure(
            text=text, voice=voice, audio_out=audio_out,
            rate=rate, pitch=pitch)),
        "local": ("local offline TTS", lambda: _synthesize_local(
            text=text, voice=voice, audio_out=audio_out,
            rate=rate, pitch=pitch)),
    }
    order = [
        k.strip().lower()
        for k in os.environ.get("TTS_ORDER", "edge,gemini,azure,local").split(",")
        if k.strip().lower() in providers
    ] or ["edge", "gemini", "azure", "local"]

    word_boundaries = None
    failures = []
    for key in order:
        name, fn = providers[key]
        try:
            word_boundaries = fn()
            if failures:
                print(f"TTS: succeeded with {name} after: "
                      + "; ".join(failures))
            break
        except Exception as exc:
            failures.append(f"{name} ({type(exc).__name__})")
            print(f"WARNING: {name} failed ({type(exc).__name__}: "
                  f"{str(exc)[:160]}); trying the next provider.")
    else:
        raise RuntimeError(
            "All TTS providers failed: " + "; ".join(failures)
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
        # Native metadata unavailable/unreliable (always true on the
        # Azure REST fallback).
        # -----------------------------------------------------------

        print(
            f"WARNING: voice '{voice}' returned "
            f"no reliable WordBoundary events."
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
            "Generate TTS narration "
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
            "Neural voice, e.g. "
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