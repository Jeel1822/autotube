"""Analytics agent contract.

Actual YouTube Analytics retrieval is intentionally a separate integration
step because it requires analytics scopes/metrics beyond the existing upload
OAuth path. This module provides the learning contract for that integration.
"""

from src.agents.orchestrator import run_json_batch


def analyze(rows: list[dict]) -> dict:
    result = run_json_batch(
        "Channel Analytics Analyst",
        "Find patterns in historical Cosmic Curious performance data.",
        f'''Analyze these video rows:
{rows}
Return {{"patterns":[],"winning_topics":[],"winning_hooks":[],"weak_patterns":[],"recommendations":[]}}.''',
        max_output_tokens=2500,
    )
    return result if isinstance(result, dict) else {}
