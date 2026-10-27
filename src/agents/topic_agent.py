"""Batch topic generation for Cosmic Curious."""

from src.agents.content_filter import load_playbook, playbook_prompt_block
from src.agents.orchestrator import run_json_batch


def find_topics(
    channel_id: str,
    config: dict,
    trend_signals: list[str],
    used_topics: list[str],
    count: int = 30,
) -> list[dict]:
    signals = "\n".join(f"- {x}" for x in trend_signals[:40]) or "(no live signals)"
    used = "\n".join(f"- {x}" for x in used_topics[-150:]) or "(none)"
    # Real-analytics playbook (channels/<id>_playbook.yaml): what works, what
    # fails, and the required archetype mix. Edit the YAML, not this file.
    playbook_block = playbook_prompt_block(load_playbook(channel_id)) or (
        "Prefer ONE concrete, strange, easy-to-picture claim about a "
        "familiar object, in plain words a non-scientist understands. "
        "Avoid topics built on unexplained jargon."
    )

    result = run_json_batch(
        "Topic Hunter",
        "Find original, high-retention science/space ideas. Force first-person scene openers on real objects.",
        f"""
Generate exactly {count} candidate topics.

Each item must contain:
{{
  "topic": "first-person scene title, 4-8 words, NEVER starting with 'How' or 'Why'",
  "curiosity": 1,
  "novelty": 1,
  "visual": 1,
  "science_confidence": 1,
  "reason": "one short reason"
}}

Return JSON object:
{{"topics": [ ... ]}}

{playbook_block}

Audience: adults 35+, watching on phones.

CRITICAL REQUIREMENT - FIRST-PERSON SCENES:
Every candidate topic MUST be framed as an active, first-person scene or immediate sensory action on a real physical object/environment.
- REQUIRED OPENINGS: Use scene openers such as "Walking on...", "Standing on...", "Floating above...", "Falling through...", "Falling into...", "Diving into...", "Breathing on...", "Riding a...".
- Picture a real person (the viewer) actually there experiencing one strange, concrete consequence.

STRICT RULE / BANNED PREFIXES:
- NEVER start a topic with "How" or "Why" under any circumstances.

ALREADY USED CHANNEL TOPICS:
{used}
""",
        f"CHANNEL: {config['display_name']}\nNICHE: {config['niche']}\nTONE: {config['tone']}",
        max_output_tokens=4000,
    )

    topics = result.get("topics", []) if isinstance(result, dict) else []
    cleaned = []
    seen = set()
    for item in topics:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "")).strip()
        if not topic or len(topic) > 220:
            continue
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned
