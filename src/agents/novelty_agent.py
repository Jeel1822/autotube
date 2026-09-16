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
      "reason": "max 6 words"
    }}
  ]
}}

Keep "reason" and "similar_previous_topic" extremely short (a few words
each, not full sentences) -- this batch covers up to 30 candidates at
once, and verbose reasoning per item risks the response getting cut off
before the JSON array is complete.

TWO SEPARATE DEDUP CHECKS -- DO BOTH:

1. Compare each candidate against PREVIOUS TOPICS (topics used on
   earlier days, listed below).

2. ALSO compare candidates AGAINST EACH OTHER within this same batch.
   This is critical and was previously missing: if two or more
   candidates in THIS batch describe the same core phenomenon or
   mechanism, only the single strongest one should PASS -- REJECT the
   rest, with similar_previous_topic noting it duplicates another
   candidate in this same batch (not a previous-days topic).

Real near-duplicates from this channel that slipped through because
they were checked against previous_topics but never against each other
in the same batch (same idea, different wording -- reject the weaker
one of each pair):
- "What happens 60 seconds before an asteroid strike" vs "What happens
  1 minute before an asteroid hits Earth" (identical timeframe, reworded)
- "What if Earth spins twice as fast" vs "What if Earth spun twice as
  fast" (identical concept, tense changed)
- "Why neutron stars have nuclear pasta inside" vs "Why neutron stars
  form nuclear pasta" (identical phenomenon, verb changed)
- "How galactic magnetic fields align cosmic dust grains" appearing
  twice with nearly identical framing

Reject the same idea even if the wording, tense, specific numbers, or
framing changes. Related subjects are OK only when the scientific
question and viewer payoff are genuinely different -- not just reworded.

PREVIOUS TOPICS (from earlier days):
{previous}

CANDIDATES (this batch -- check these against each other too):
{candidate_text}
""",
        f"CHANNEL ID: {channel_id}",
        max_output_tokens=6000,
    )
    return result.get("results", []) if isinstance(result, dict) else []
