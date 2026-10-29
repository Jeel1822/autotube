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
        "Perform a post-mortem on the latest video performance to extract growth lessons.",
        f"""
Analyze the performance of this video:
Title: {title}
Views: {views}
Status: {'HIT' if is_hit else 'DROP'} (Threshold: {hit_threshold})

Task:
1. If it was a HIT, identify which winning pattern it used (First-Person, Everyday Object, etc.)
   and why it resonated.
2. If it was a DROP, identify what felt 'off' (Too abstract, jargon, boring opener,
   'How/Why' mechanism).
3. Write exactly ONE clear, short 'performance_lesson'.

Return:
{{
  "lesson": "One sentence growth rule starting with 'FAVOR' or 'AVOID'",
  "confidence": 0.9,
  "pattern_detected": "..."
}}
"""
    )

    if result and isinstance(result, dict) and "lesson" in result:
        # Save this to performance_lessons memory for the CEO agent
        remember(channel_id, "performance_lessons", result["lesson"])
        print(f"Post-Mortem Lesson Saved: {result['lesson']}")
        return result
    return None
