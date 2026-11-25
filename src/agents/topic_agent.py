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

    # Load evolution-tier directives if present
    from src.agents.memory import load_memory
    memory = load_memory(channel_id)
    evolution_block = ""
    directives = memory.get("evolution_directives")
    if directives:
        # Stored as a list (newest last); older code stored a dict. The old
        # code called .get() on the list and crashed whenever a directive existed.
        latest = directives[-1] if isinstance(directives, list) else directives
        text = latest.get("directive", "") if isinstance(latest, dict) else str(latest)
        if text:
            evolution_block = f"\nACTIVE SYSTEM EVOLUTION DIRECTIVE:\n{text}\n"

    result = run_json_batch(
        "Topic Hunter",
        "Find original, high-retention science/space ideas. Force first-person scene openers on real objects.",
        f"""
Generate exactly {count} candidate topics.

Each item must contain:
{{
  "topic": "plain concrete claim or first-person scene, 4-7 words, not starting with 'How'",
  "curiosity": 1,
  "novelty": 1,
  "visual": 1,
  "science_confidence": 1,
  "reason": "one short reason"
}}

Return JSON object:
{{"topics": [ ... ]}}

{playbook_block}
{evolution_block}
Audience: adults 35+, watching on phones.

WINNING BLUEPRINT (every Short above ~1,000 views so far fits this):
1. FAMILIAR OBJECT x ALIEN PLACE: a thing the viewer can picture instantly
   (pencil, steel coin, wood, ice, moon dust, a rocket) in a place where it behaves
   strangely (Venus, Pluto, liquid nitrogen, molten sulfur).
2. ONE plain, concrete claim stated in the topic itself ("Moon dust smells like a
   gunshot", "Why pencils float on Venus"). Both plain claims and first-person
   scenes ("Walking on...", "Standing on...") have worked; use roughly half each.
3. A physical sensation: weight, smell, sound, floating, igniting.
- Avoid titles that open with "How" (mechanism titles did worst). "Why"/"What" are
  fine only when followed by a concrete claim about a familiar object.
- Keep titles to 4-7 words.

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
