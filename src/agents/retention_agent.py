from src.agents.orchestrator import run_json_batch


def review_script(topic: str, script: str) -> dict:
    return run_json_batch(
        "Retention Editor",
        "Improve pacing without weakening scientific accuracy.",
        f'''Analyze this Short script.
TOPIC: {topic}
SCRIPT: {script}
Return {{"score":1,"weak_points":["..."],"changes":["..."],"improved_script":"..."}}.''',
        max_output_tokens=2500,
    )
