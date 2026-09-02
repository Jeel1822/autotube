from src.agents.orchestrator import run_json_batch


def generate_hooks(topic: str, script: str, count: int = 8) -> list[dict]:
    result = run_json_batch(
        "Hook Specialist",
        "Create immediate, accurate, non-clickbait openings for science Shorts.",
        f'''Generate {count} different hooks for this topic.
TOPIC: {topic}
SCRIPT: {script}
Return {{"hooks":[{{"hook":"...","clarity":1,"curiosity":1,"retention":1,"science_safety":1}}]}}.''',
        max_output_tokens=1800,
    )
    return result.get("hooks", []) if isinstance(result, dict) else []
