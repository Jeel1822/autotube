from src.agents.orchestrator import run_json_batch


def optimize(topic: str, script: str) -> dict:
    return run_json_batch(
        "YouTube Packaging Strategist",
        "Optimize title/description/tags for discovery without spam or scientific misrepresentation.",
        f'''TOPIC: {topic}\nSCRIPT: {script}
Return {{"titles":["..."],"descriptions":["..."],"tags":["..."],"hashtags":["..."],"recommended_title":"..."}}.''',
        max_output_tokens=2200,
    )
