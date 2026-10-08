from src.agents.orchestrator import run_json_batch


def optimize(topic: str, script: str) -> dict:
    return run_json_batch(
        "YouTube Packaging Strategist",
        "Optimize title/description/tags for discovery without spam or scientific misrepresentation.",
        f'''TOPIC: {topic}\nSCRIPT: {script}

TITLE RULES (this channel's best titles were short, concrete and plain):
- Under 60 characters, one concrete surprising claim.
- No unexplained technical terms (no "sublimation", "Roche lobe",
  "eccentricity", "metallicity", "volatiles"). Say it the way you would to a
  friend.
- Vary the opening: do not start every title with "What Happens When" or
  "Why". Statements and "How" titles are fine.
- Must stay scientifically accurate and not overpromise.
Return {{"titles":["..."],"descriptions":["..."],"tags":["..."],"hashtags":["..."],"recommended_title":"..."}}.''',
        max_output_tokens=2200,
    )
