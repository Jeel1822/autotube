"""Production brief agent for Cosmic Curious.

Turns one approved topic into a structured handoff for the existing
video-production pipeline. This is planning only; it does not upload.
"""
from src.agents.orchestrator import run_json_batch


def build_brief(topic: str, winner: dict, config: dict) -> dict:
    return run_json_batch(
        "Production Director",
        "Turn an approved science topic into a production-ready creative brief without inventing facts.",
        f"""
Create a production brief for this approved Cosmic Curious topic.

TOPIC:
{topic}

EDITOR WINNER DATA:
{winner}

Return exactly this JSON shape:
{{
  "topic": "...",
  "format": "short" or "both",
  "core_question": "...",
  "scientific_reveal": "...",
  "safe_framing": "...",
  "hook_options": ["...", "...", "...", "...", "..."],
  "preferred_hook": "...",
  "narration_beats": [
    {{"beat": 1, "purpose": "hook", "seconds": 3, "content": "..."}},
    {{"beat": 2, "purpose": "setup", "seconds": 5, "content": "..."}},
    {{"beat": 3, "purpose": "mechanism", "seconds": 10, "content": "..."}},
    {{"beat": 4, "purpose": "reveal", "seconds": 10, "content": "..."}},
    {{"beat": 5, "purpose": "ending", "seconds": 5, "content": "..."}}
  ],
  "visual_beats": [
    {{"beat": 1, "visual": "...", "stock_query": "...", "ai_visual": false}},
    {{"beat": 2, "visual": "...", "stock_query": "...", "ai_visual": false}},
    {{"beat": 3, "visual": "...", "stock_query": "...", "ai_visual": true}}
  ],
  "thumbnail_concepts": [
    {{"concept": "...", "text": "...", "focal_object": "..."}},
    {{"concept": "...", "text": "...", "focal_object": "..."}},
    {{"concept": "...", "text": "...", "focal_object": "..."}}
  ],
  "title_options": ["...", "...", "...", "...", "..."],
  "description_angle": "...",
  "science_risks": ["..."],
  "success_hypothesis": "..."
}}

Rules:
- Keep the science defensible.
- Do not invent observations, numbers, discoveries, or citations.
- Use conditional language for hypothetical outcomes.
- Do not use generic visual queries when a specific visual can be named.
- Keep the Short plan compatible with 30-60 seconds.
""",
        f"CHANNEL: {config['display_name']}\nNICHE: {config['niche']}\nTONE: {config['tone']}",
        max_output_tokens=4500,
    )
