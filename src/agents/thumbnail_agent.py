from src.agents.orchestrator import run_json_batch


def concepts(topic: str, script: str, count: int = 5) -> list[dict]:
    result = run_json_batch(
        "Thumbnail Director",
        "Design high-contrast, curiosity-driven thumbnails that accurately represent the video.",
        f'''Create {count} thumbnail concepts.
TOPIC: {topic}
SCRIPT: {script}
Return {{"concepts":[{{"layout":"...","focal_object":"...","text":"...","curiosity":1,"clarity":1}}]}}.''',
        max_output_tokens=1800,
    )
    return result.get("concepts", []) if isinstance(result, dict) else []
