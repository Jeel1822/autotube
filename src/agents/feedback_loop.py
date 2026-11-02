"""
Feedback Loop Agent:
Monitors performance of exported assets, feeding real view metrics 
back into the agent memory for rapid strategy iteration.
"""
import json
from pathlib import Path
from src.agents.memory import remember

def process_performance_metric(channel_id: str, video_title: str, views: int, retention: float):
    """Feeds performance metrics into the memory bank for the CEO agent."""
    data = {
        "title": video_title,
        "views": views,
        "retention": retention,
        "is_hit": views >= 2500
    }
    remember(channel_id, "performance_metrics", data)
    print(f"[FEEDBACK LOOP] Metrics ingested for '{video_title}': {views} views")
