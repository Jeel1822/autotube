"""Batch topic generation for Cosmic Curious."""

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

    result = run_json_batch(
        "Topic Hunter",
        "Find original, high-retention science/space ideas without copying source titles.",
        f"""
Generate exactly {count} candidate topics.

Each item must contain:
{{
  "topic": "specific topic or question",
  "curiosity": 1,
  "novelty": 1,
  "visual": 1,
  "science_confidence": 1,
  "reason": "one short reason"
}}

Return JSON object:
{{"topics": [ ... ]}}

Use recent signals as inspiration, not as titles to copy.
Reject generic facts, listicles, unsupported mysteries, fake NASA claims,
and recycled ideas.

RECENT SIGNALS:
{signals}

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
