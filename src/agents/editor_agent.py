"""Final opportunity-ranking agent."""

from src.agents.orchestrator import run_json_batch


def select_winners(finalists: list[dict], config: dict, count: int = 5) -> dict:
    packed = "\n\n".join(
        f"INDEX: {i+1}\nTOPIC: {x['topic']}\n"
        f"NOVELTY: {x.get('novelty_score', 0)}\n"
        f"SCIENCE: {x.get('accuracy_score', 0)}\n"
        f"CURIOSITY: {x.get('curiosity', 0)}\n"
        f"NOVELTY: {x.get('novelty_score', x.get('novelty', 0))}\n"
        f"VISUAL: {x.get('visual', 0)}\n"
        f"SCIENCE CONFIDENCE: {x.get('science_confidence', x.get('accuracy_score', 0))}\n"
        f"ORIGINALITY NOTE: {x.get('novelty_reason', '')}\n"
        f"SCIENCE NOTE: {x.get('safe_framing', '')}"
        for i, x in enumerate(finalists)
    )

    return run_json_batch(
        "Chief Editor",
        "Choose the strongest science-video opportunities while protecting long-term channel quality.",
        f"""
Rank the candidates and choose the top {count}.

Use these weighted dimensions:
- curiosity 25%
- novelty 20%
- scientific value 15%
- visual potential 15%
- Short potential 10%
- long-form potential 5%
- accuracy 10%

Return JSON object:
{{
  "winners": [
    {{
      "topic": "...",
      "score": 0,
      "rank": 1,
      "why": "...",
      "recommended_format": "short" or "both"
    }}
  ],
  "winner": "best topic",
  "strategy_note": "one short note"
}}

CANDIDATES:
{packed}
""",
        f"CHANNEL: {config['display_name']}\nNICHE: {config['niche']}",
        max_output_tokens=3500,
    )
