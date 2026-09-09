"""Final opportunity-ranking agent."""

from src.agents.orchestrator import run_json_batch


def select_winners(finalists: list[dict], config: dict, count: int = 5) -> dict:
    packed = "\n\n".join(
        f"INDEX: {i+1}\nTOPIC: {x['topic']}\n"
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

Use these weighted dimensions (only score what you can actually see data
for above -- curiosity, novelty, visual, science confidence):
- curiosity 35%
- novelty 25%
- visual potential 20%
- science confidence 20%

SCORING RULES (read carefully -- this matters):
- "score" must be an integer from 1 to 100.
- Scores MUST reflect genuine relative differences between candidates.
  It would be unusual for multiple different topics to be exactly or
  nearly equally strong -- find the real differences and reflect them.
  Do NOT assign identical or near-identical scores (e.g. all 95+, or
  all exactly the same number) across your top picks just because they
  all passed earlier screening. A ranked top 5 should show a real
  spread, not a flat ceiling.
- "rank" 1 must have the highest "score"; rank {count} the lowest among
  your picks.

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
