"""
generate_script.py
Picks the next unused topic for a channel and generates a script using
Google Gemini's free-tier API via the current `google-genai` SDK (the
old `google-generativeai` package is deprecated and its models have been
shut down — see requirements.txt).

Model used: gemini-3.5-flash-lite — Google's current cheap/fast tier as
of mid-2026, free-tier friendly. Google has a history of retiring model
names every several months (2.0-flash was retired, 2.5-flash is retiring
Oct 2026) — if this script starts failing with a "model not found" or
404 error again in future, check https://ai.google.dev/gemini-api/docs/models
for the current recommended model name and swap it into GEMINI_MODEL below.

Falls back to a simple template-based script if no GEMINI_API_KEY is set
or the API call fails for any reason, so the pipeline never hard-fails.
"""
import os
import json
import random
import re
from pathlib import Path

import yaml

try:
    from google import genai as genai_client
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

GEMINI_MODEL = "gemini-3.5-flash-lite"

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True)


def load_channel_config(channel_id: str) -> dict:
    path = ROOT / "channels" / f"{channel_id}.yaml"
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _used_topics_path(channel_id: str) -> Path:
    return STATE_DIR / f"{channel_id}_used_topics.json"


def get_used_topics(channel_id: str) -> set:
    p = _used_topics_path(channel_id)
    if p.exists():
        return set(json.loads(p.read_text()))
    return set()


def mark_topic_used(channel_id: str, topic: str) -> None:
    used = get_used_topics(channel_id)
    used.add(topic)
    _used_topics_path(channel_id).write_text(json.dumps(sorted(used)))


def pick_next_topic(channel_id: str, config: dict) -> str:
    """Pick an unused topic from the seed file. Loops back if exhausted."""
    topics_file = ROOT / config["topics_seed_file"]
    all_topics = [
        line.strip() for line in topics_file.read_text().splitlines() if line.strip()
    ]
    used = get_used_topics(channel_id)
    unused = [t for t in all_topics if t not in used]

    if not unused:
        # Exhausted the seed list — reset so it loops rather than crashing.
        # NOTE: you should add more topics to the seed file periodically
        # so content doesn't repeat. See README "Keeping topics fresh".
        unused = all_topics

    topic = random.choice(unused)
    mark_topic_used(channel_id, topic)
    return topic


def _clean_script_text(text: str) -> str:
    """Strip markdown, stage directions, and anything not meant to be spoken."""
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\[.*?\]", "", text)   # remove [pause], [music], etc.
    text = re.sub(r"\(.*?\)", "", text)   # remove (visual: ...) notes
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_with_gemini(topic: str, config: dict, length_seconds: int) -> str:
    client = genai_client.Client(api_key=os.environ["GEMINI_API_KEY"])

    words_target = int(length_seconds * 2.5)  # ~150 wpm speaking pace

    prompt = f"""You are writing a voiceover script for a faceless YouTube video.

Channel: {config['display_name']}
Niche: {config['niche']}
Tone: {config['tone']}
Topic: {topic}

Write ONLY the spoken narration, nothing else — no titles, no stage directions,
no [visual cues], no markdown. Just the words a narrator would read aloud.

Target length: approximately {words_target} words (this fills about
{length_seconds} seconds at natural speaking pace).

Structure: strong hook in the first sentence, build curiosity, deliver the
core facts/insight clearly, end with a punchy closing line. Do not use
phrases like "in conclusion" or "subscribe for more" — end naturally on
the content itself.

Write in plain, conversational English suitable for text-to-speech."""

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return _clean_script_text(response.text)


def generate_with_template(topic: str, config: dict) -> str:
    """Zero-dependency fallback so the pipeline works with no API key at all."""
    return (
        f"Here's something most people don't know: {topic}. "
        f"It sounds simple, but the reasons behind it reveal a lot about "
        f"{config['niche'].lower()}. Once you understand why this happens, "
        f"you'll start noticing it everywhere in your own life. "
        f"That's the kind of small insight that changes how you see the world."
    )


def generate_script(channel_id: str, is_short: bool = False) -> dict:
    config = load_channel_config(channel_id)
    topic = pick_next_topic(channel_id, config)
    length = config["short_length_seconds"] if is_short else config["video_length_seconds"]

    if GEMINI_AVAILABLE and os.environ.get("GEMINI_API_KEY"):
        try:
            script_text = generate_with_gemini(topic, config, length)
        except Exception as e:
            # Don't let a Gemini outage/model-rename/quota issue kill the
            # whole daily run — fall back to the template so a video still
            # gets made, and print the error so it's visible in CI logs.
            print(f"WARNING: Gemini call failed ({e}); using template fallback.")
            script_text = generate_with_template(topic, config)
    else:
        script_text = generate_with_template(topic, config)

    return {
        "channel_id": channel_id,
        "topic": topic,
        "script": script_text,
        "is_short": is_short,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("channel_id")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--out", default=None, help="Path to write JSON output")
    args = parser.parse_args()

    result = generate_script(args.channel_id, is_short=args.short)
    output = json.dumps(result, indent=2)

    if args.out:
        Path(args.out).write_text(output)
    print(output)
