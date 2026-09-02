from src.agents.orchestrator import run_json_batch


def propose(performance_context: str) -> dict:
    return run_json_batch(
        "YouTube Experiment Scientist",
        "Design controlled experiments that change one variable at a time.",
        f'''Performance context:
{performance_context}
Return {{"experiments":[{{"hypothesis":"...","variable":"...","control":"...","test":"...","success_metric":"..."}}]}}.''',
        max_output_tokens=1800,
    )
