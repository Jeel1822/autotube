from src.agents.orchestrator import run_json_batch


def plan(topic: str, script: str) -> dict:
    return run_json_batch(
        "Visual Director",
        "Turn the narration into scene-specific visuals instead of generic space footage.",
        f'''Create a shot plan for:
TOPIC: {topic}
SCRIPT: {script}
Return {{"shots":[{{"sentence":"...","visual":"...","search_query":"...","animation":"...","on_screen_text":"..."}}]}}.''',
        max_output_tokens=3000,
    )
