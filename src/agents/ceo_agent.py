"""Channel CEO strategy agent."""
from src.agents.orchestrator import run_json_batch
from src.agents.memory import recent_memory
from src.agents.video_registry import recent_videos


def make_strategy(channel_id: str, config: dict) -> dict:
    videos = recent_videos(channel_id, 50)
    lessons = recent_memory(channel_id, "performance_lessons", 50)
    experiments = recent_memory(channel_id, "experiments", 30)

    return run_json_batch(
        "Cosmic Curious Channel CEO",
        "Choose the next growth strategy using actual channel history; optimize for sustainable audience growth and revenue potential.",
        f"""
Analyze the current channel state.

RECENT VIDEO REGISTRY:
{videos}

PERFORMANCE LESSONS:
{lessons}

EXPERIMENT HISTORY:
{experiments}

Return exactly:
{{
  "strategy": "...",
  "priority_topic_families": ["...", "...", "..."],
  "avoid_topic_families": ["..."],
  "hook_patterns_to_test": ["...", "..."],
  "visual_patterns_to_test": ["...", "..."],
  "next_experiments": [
    {{"hypothesis":"...","variable":"...","success_metric":"..."}}
  ],
  "reasoning": "..."
}}

Do not invent performance numbers. If the registry is sparse, explicitly
say confidence is low and use conservative recommendations.
""",
        f"CHANNEL: {config['display_name']}\nNICHE: {config['niche']}\nTONE: {config['tone']}",
        max_output_tokens=3000,
    )
