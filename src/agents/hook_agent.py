from src.agents.orchestrator import run_json_batch


def generate_hooks(topic: str, script: str, count: int = 8) -> list[dict]:
    result = run_json_batch(
        "Hook Specialist",
        "Create immediate, accurate, non-clickbait openings for science Shorts, emphasizing everyday objects and first-person perspectives.",
        f'''Generate {count} different hooks for this topic.
TOPIC: {topic}
SCRIPT: {script}

REQUIRED PRINCIPLE (backed by real view/retention data from this channel):
The opening sentence MUST state the core claim immediately, with NO scene-setting,
teasing, or wind-up.

STRICT BAN - BANNED OPENERS:
- STRICTLY BAN starting any hook with "How" or "Why" under any circumstances.
- Never start with a question ("How do you...", "Why does...").
- Never start with scene-setting ("Ten kilometers beneath...") or teases ("Zoom in closer...").

Winning patterns for this channel:
- First-person scenes on an everyday object (e.g., "Walking on...", "Standing on...").
- Everyday object anchors (e.g., compass, glass, diamonds, rocket, rain, sound).
- Surprising consequence of a familiar object.

Return {{"hooks":[{{"hook":"...","clarity":1,"curiosity":1,"retention":1,"science_safety":1}}]}}.''',
        max_output_tokens=1800,
    )
        max_output_tokens=1800,
    )
    return result.get("hooks", []) if isinstance(result, dict) else []
