"""Batch novelty guard."""

from src.agents.orchestrator import run_json_batch


def check_topics(channel_id: str, candidates: list[str], previous_topics: list[str]) -> list[dict]:
    previous = "\n".join(f"- {x}" for x in previous_topics[-200:]) or "(none)"
    candidate_text = "\n".join(f"{i+1}. {x}" for i, x in enumerate(candidates))

    result = run_json_batch(
        "Novelty Guardian",
        "Protect the channel from exact duplicates and near-duplicate scientific reveals.",
        f"""
Evaluate ALL candidates in one batch.

Return JSON object:
{{
  "results": [
    {{
      "index": 1,
      "verdict": "PASS" or "REJECT",
      "novelty_score": 1,
      "similar_previous_topic": "... or empty",
      "reason": "short reason"
    }}
  ]
}}

Reject the same idea even if the wording changes. Related subjects are OK
only when the scientific question and viewer payoff are genuinely different.

PREVIOUS TOPICS:
{previous}

CANDIDATES:
{candidate_text}
""",
        f"CHANNEL ID: {channel_id}",
        max_output_tokens=3500,
    )
    return result.get("results", []) if isinstance(result, dict) else []
