"""
retention_critic.py
Analyzes the latest video performance and writes immediate, actionable
growth lessons into the channel memory.
"""
from src.agents.orchestrator import run_json_batch
from src.agents.memory import remember

def run_post_mortem(channel_id: str, video_id: str, title: str, views: int, hit_threshold: int):
    """
    Performs an automated post-mortem on a specific video.
    If the video is a 'hit', it extracts what went right.
    If it's a 'drop', it identifies the failure mode.
    """
    is_hit = views >= hit_threshold

    result = run_json_batch(
        "Retention Critic",
        "Perform a high-standard post-mortem on the latest video performance to extract elite growth lessons.",
        f"""
Analyze the performance of this video:
Title: {title}
Views: {views}
Status: {'ELITE HIT' if is_hit else 'UNDERPERFORMER'} (Threshold: {hit_threshold})

Task:
1. If it was an ELITE HIT, rigorously identify the specific viral triggers:
   - What was the 'Psychological Friction' in the first 2 seconds?
   - What specific 'FAVOR' rule can we write to replicate this success?
2. If it was an UNDERPERFORMER, diagnose the specific point of failure:
   - Was the hook too academic?
   - Was the visual anchor missing?
   - Write a sharp 'AVOID' rule.
3. Your lesson must be surgical and actionable.

Return:
{{
  "lesson": "One sentence growth rule starting with 'FAVOR' (for elite hits) or 'AVOID' (for underperformers)",
  "confidence": 0.95,
  "pattern_detected": "...",
  "viral_trigger": "..."
}}
"""
    )

    if result and isinstance(result, dict) and "lesson" in result:
        # Save this to performance_lessons memory for the CEO agent
        remember(channel_id, "performance_lessons", result["lesson"])
        print(f"Post-Mortem Lesson Saved: {result['lesson']}")
        return result
    return None
