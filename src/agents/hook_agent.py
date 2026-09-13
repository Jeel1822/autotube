from src.agents.orchestrator import run_json_batch


def generate_hooks(topic: str, script: str, count: int = 8) -> list[dict]:
    result = run_json_batch(
        "Hook Specialist",
        "Create immediate, accurate, non-clickbait openings for science Shorts.",
        f'''Generate {count} different hooks for this topic.
TOPIC: {topic}
SCRIPT: {script}

REQUIRED PRINCIPLE (backed by real view/retention data from this exact
channel -- not a style preference): the opening sentence MUST state the
single most concrete, jaw-dropping claim of the whole video immediately,
with ZERO scene-setting, teasing, or wind-up. Either direct "you/your"
framing or a bold third-person claim works -- what matters is stating
the actual payoff in sentence one, not building up to it.

Real top performers on this channel (all state the core claim
immediately, no wind-up):
- "Saturn has a hurricane wider than two Earths shaped like a perfect
  hexagon" (third-person, immediate claim -- 1,044 views)
- "This galaxy is the size of the Milky Way, but it's missing almost
  all of its stars" (third-person, immediate claim -- 1,019 views, 102%
  retention)
- "If you spoke on Saturn's moon Titan, your voice would suddenly
  drop..." (second-person, immediate claim -- 1,186 views, 120%
  retention)

Real failures on this channel (these scene-set or tease instead of
stating the claim -- do not do this):
- "Ten kilometers beneath Jupiter's icy crust..." (scene-setting before
  the payoff -- 0 views)
- "Zoom in closer, and you will spot something bizarre" (a TEASE --
  promises something interesting instead of just saying it -- 11%
  retention, viewers bailed almost immediately)
- "How do you find a ghost planet drifting through the galactic bulge?"
  (a question instead of a claim -- makes the viewer wait for the
  answer instead of hooking them with it)

Every hook you generate must pass this test: if you removed everything
after the first sentence, would that sentence alone already be a
complete, concrete, surprising claim? If it's a tease, a question, or a
scene description building toward the claim, rewrite it.

Return {{"hooks":[{{"hook":"...","clarity":1,"curiosity":1,"retention":1,"science_safety":1}}]}}.''',
        max_output_tokens=1800,
    )
    return result.get("hooks", []) if isinstance(result, dict) else []
