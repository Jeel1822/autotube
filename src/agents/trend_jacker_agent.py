from src.agents.orchestrator import run_json_batch

def extract_viral_hook(viral_title: str) -> dict:
    """
    Analyzes a viral title to extract the psychological curiosity gap
    and structural pattern that made it viral.
    """
    result = run_json_batch(
        "Trend Jacker",
        "You are an expert YouTube strategist. Your goal is to reverse-engineer "
        "viral science/space content into original high-impact hooks.",
        f"""
Analyze this viral title: '{viral_title}'
Extract:
1. The Curiosity Gap (Why did people click?)
2. The Core Scientific Fact
3. Propose a better, more punchy 'First-Person' hook for Cosmic Curious.

Return JSON: {{"gap": "...", "fact": "...", "new_hook": "..."}}
        """,
        max_output_tokens=1000
    )
    return result if isinstance(result, dict) else {}
