"""Batch science screening for topic candidates."""

from src.agents.orchestrator import run_json_batch


def fact_check_topics(topics: list[str]) -> list[dict]:
    candidate_text = "\n".join(f"{i+1}. {x}" for i, x in enumerate(topics))

    result = run_json_batch(
        "Science Guardian",
        "Fact-check topic premises before production; accuracy is a hard constraint.",
        f"""
Evaluate ALL topics in one batch.

Return JSON object:
{{
  "results": [
    {{
      "index": 1,
      "verdict": "PASS" or "REVISE" or "REJECT",
      "accuracy_score": 1,
      "claim_type": "established" or "hypothesis" or "mixed",
      "key_risk": "short description or empty",
      "safe_framing": "recommended wording"
    }}
  ]
}}

Judge the TOPIC TITLE ITSELF as the viewer will read it, not just the
underlying science. If the title/hook states or implies something the real
phenomenon does not do (e.g. "explode, vanish, then explode again" for objects
that actually survive or only partly explode), verdict is REVISE or REJECT even
if a related real phenomenon exists. A hook may be dramatic but must not be
scientifically false or deceptive; put an honest rewording in safe_framing.

Reject a materially misleading premise. Do not reject ordinary simplification
for a general audience when it remains accurate.

TOPICS:
{candidate_text}
""",
        max_output_tokens=3500,
    )
    return result.get("results", []) if isinstance(result, dict) else []
