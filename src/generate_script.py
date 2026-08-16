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

# Roughly 1.5 tokens/word for English is a safe over-estimate; Hindi
# (Devanagari) tokenizes less efficiently per word, so pad generously.
# Without an explicit max_output_tokens, the SDK's default cap can silently
# truncate long-form scripts mid-sentence (observed: an 8-minute/1200-word
# target coming back as a ~365-word/2:26 script) — always request enough
# headroom for the target length plus the title line and some safety margin.
TOKENS_PER_WORD = 2.2
MIN_OUTPUT_TOKENS = 512
TOKEN_SAFETY_MARGIN = 200


def _max_output_tokens_for(words_target: int) -> int:
    return max(MIN_OUTPUT_TOKENS, int(words_target * TOKENS_PER_WORD) + TOKEN_SAFETY_MARGIN)

LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi (written in Devanagari script, not transliterated/Roman Hindi)",
}

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


def _generate_more_topics(config: dict, existing: list, count: int = 20) -> list:
    """Asks Gemini for a fresh batch of topic ideas for this channel's niche,
    avoiding anything already in `existing`. Returns [] on any failure so the
    caller can fall back to looping the existing list instead of crashing."""
    if not (GEMINI_AVAILABLE and os.environ.get("GEMINI_API_KEY")):
        return []
    try:
        client = genai_client.Client(api_key=os.environ["GEMINI_API_KEY"])
        existing_sample = "\n".join(f"- {t}" for t in existing[-40:])
        prompt = f"""You generate topic ideas for a faceless YouTube channel.

Channel: {config['display_name']}
Niche: {config['niche']}
Tone: {config['tone']}

Here are topics already covered (do NOT repeat these or close variations):
{existing_sample}

Generate {count} brand new topic ideas for this channel, each a single line,
each specific enough to script a short video from (not a vague category).
No numbering, no markdown, no quotes — just one topic per line."""

        response = _generate_with_token_budget(client, prompt, max_output_tokens=800)
        lines = [
            re.sub(r"^[\d\.\-\)\s]+", "", line).strip()
            for line in response.text.splitlines()
        ]
        new_topics = [line for line in lines if line and line not in existing]
        return new_topics
    except Exception as e:
        print(f"WARNING: topic auto-generation failed ({e}); will loop existing topics instead.")
        return []


def pick_next_topic(channel_id: str, config: dict) -> str:
    """Pick an unused topic from the seed file. If the seed file is
    exhausted, try to generate a fresh batch of topics via Gemini and append
    them to the seed file (so the channel keeps expanding its topic pool
    instead of quietly repeating content). Only loops back to reused topics
    as a last resort, if topic generation isn't available."""
    topics_file = ROOT / config["topics_seed_file"]
    all_topics = [
        line.strip() for line in topics_file.read_text().splitlines() if line.strip()
    ]
    used = get_used_topics(channel_id)
    unused = [t for t in all_topics if t not in used]

    if not unused:
        new_topics = _generate_more_topics(config, all_topics)
        if new_topics:
            with topics_file.open("a") as f:
                f.write("\n" + "\n".join(new_topics) + "\n")
            print(f"Added {len(new_topics)} new topics to {topics_file.name}")
            unused = new_topics
        else:
            # No API key / generation failed — reset so it loops rather than
            # crashing. You should add more topics to the seed file
            # periodically in this case. See README "Keeping topics fresh".
            unused = all_topics

    topic = random.choice(unused)
    mark_topic_used(channel_id, topic)
    return topic


def pick_language(config: dict) -> str:
    """Randomly picks a language for this run from the channel's configured
    `languages` list, so consecutive uploads aren't predictably alternating
    (e.g. not strict en/hi/en/hi) but genuinely random each time. Channels
    that don't set `languages` in their yaml stay English-only, unchanged
    from before."""
    languages = config.get("languages") or ["en"]
    return random.choice(languages)


def _voice_for_language(config: dict, language: str) -> str:
    """Resolves the TTS voice for a given language, falling back to the
    legacy single `voice` key for channels that haven't been migrated to
    the `voices: {en: ..., hi: ...}` map yet."""
    voices = config.get("voices") or {}
    voice = voices.get(language) or config.get("voice")
    if not voice:
        raise ValueError(
            f"No TTS voice configured for language '{language}' in this "
            f"channel's yaml (add it under 'voices:')."
        )
    return voice


def _clean_script_text(text: str) -> str:
    """Strip markdown, stage directions, and anything not meant to be spoken."""
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"\[.*?\]", "", text)   # remove [pause], [music], etc.
    text = re.sub(r"\(.*?\)", "", text)   # remove (visual: ...) notes
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_with_gemini(topic: str, config: dict, length_seconds: int, language: str) -> dict:
    client = genai_client.Client(api_key=os.environ["GEMINI_API_KEY"])

    words_target = int(length_seconds * 2.5)  # ~150 wpm speaking pace
    language_name = LANGUAGE_NAMES.get(language, language)

    prompt = f"""You are writing a voiceover script for a faceless YouTube video.

Channel: {config['display_name']}
Niche: {config['niche']}
Tone: {config['tone']}
Topic: {topic}
Language: {language_name}

Respond in EXACTLY this format and nothing else — no markdown, no extra commentary:

TITLE: <a punchy YouTube title in {language_name}, under 90 characters>
SCRIPT:
<the spoken narration only, in {language_name} — no titles, no stage
directions, no [visual cues], no markdown, just the words a narrator
would read aloud>

Target script length: approximately {words_target} words (about
{length_seconds} seconds at natural speaking pace).

Structure: strong hook in the first sentence, build curiosity, deliver the
core facts/insight clearly, end with a punchy closing line. Do not use
phrases like "in conclusion" or "subscribe for more" — end naturally on
the content itself. Write in plain, conversational {language_name}
suitable for text-to-speech."""

    max_tokens = _max_output_tokens_for(words_target)
    response = _generate_with_token_budget(client, prompt, max_tokens)
    return _parse_titled_response(response.text, fallback_topic=topic)


def _generate_with_token_budget(client, prompt: str, max_output_tokens: int):
    """Calls generate_content with an explicit max_output_tokens (falling
    back to no config if this SDK version's config shape differs, so a
    google-genai version mismatch doesn't hard-crash the run), and warns
    loudly if the response still got cut off mid-generation."""
    try:
        from google.genai import types
        config = types.GenerateContentConfig(max_output_tokens=max_output_tokens)
        response = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt, config=config,
        )
    except Exception as e:
        print(f"WARNING: could not apply max_output_tokens config ({e}); "
              f"calling without it.")
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)

    finish_reason = None
    try:
        finish_reason = response.candidates[0].finish_reason
    except Exception:
        pass
    if finish_reason and "MAX_TOKENS" in str(finish_reason).upper():
        print(f"WARNING: Gemini response was truncated by max_output_tokens="
              f"{max_output_tokens}. The generated script will be shorter "
              f"than the target length. Consider raising TOKENS_PER_WORD.")
    return response


def _parse_titled_response(text: str, fallback_topic: str) -> dict:
    """Parses the 'TITLE: ...\\nSCRIPT:\\n...' format out of a Gemini
    response. Falls back to using the topic as the title and the whole
    response as the script if the model didn't follow the format exactly,
    so a formatting slip never crashes the run."""
    title_match = re.search(r"TITLE:\s*(.+)", text)
    script_match = re.search(r"SCRIPT:\s*(.*)", text, re.DOTALL)

    title = title_match.group(1).strip() if title_match else fallback_topic
    script_raw = script_match.group(1).strip() if script_match else text
    return {"title": title, "script": _clean_script_text(script_raw)}


def generate_with_template(topic: str, config: dict, language: str) -> dict:
    """Zero-dependency fallback so the pipeline works with no API key at all."""
    if language == "hi":
        script = (
            f"ज़्यादातर लोग नहीं जानते: {topic}. यह सुनने में आसान लगता है, "
            f"लेकिन इसके पीछे की वजह {config['niche']} के बारे में बहुत कुछ बताती है। "
            f"एक बार जब आप यह समझ जाएंगे, तो आप इसे अपनी ज़िंदगी में हर जगह "
            f"देखने लगेंगे। यही वो छोटी सी बात है जो आपके देखने का नज़रिया बदल देती है।"
        )
        title = topic
    else:
        script = (
            f"Here's something most people don't know: {topic}. "
            f"It sounds simple, but the reasons behind it reveal a lot about "
            f"{config['niche'].lower()}. Once you understand why this happens, "
            f"you'll start noticing it everywhere in your own life. "
            f"That's the kind of small insight that changes how you see the world."
        )
        title = topic[0].upper() + topic[1:] if topic else topic
    return {"title": title, "script": script}


def generate_script(channel_id: str, is_short: bool = False) -> dict:
    config = load_channel_config(channel_id)
    topic = pick_next_topic(channel_id, config)
    language = pick_language(config)
    length = config["short_length_seconds"] if is_short else config["video_length_seconds"]

    if GEMINI_AVAILABLE and os.environ.get("GEMINI_API_KEY"):
        try:
            generated = generate_with_gemini(topic, config, length, language)
        except Exception as e:
            # Don't let a Gemini outage/model-rename/quota issue kill the
            # whole daily run — fall back to the template so a video still
            # gets made, and print the error so it's visible in CI logs.
            print(f"WARNING: Gemini call failed ({e}); using template fallback.")
            generated = generate_with_template(topic, config, language)
    else:
        generated = generate_with_template(topic, config, language)

    return {
        "channel_id": channel_id,
        "topic": topic,
        "title": generated["title"],
        "script": generated["script"],
        "language": language,
        "voice": _voice_for_language(config, language),
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
