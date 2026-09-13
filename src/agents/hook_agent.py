from src.agents.orchestrator import run_json_batch


def generate_hooks(topic: str, script: str, count: int = 8) -> list[dict]:
    result = run_json_batch(
        "Hook Specialist",
        "Create immediate, accurate, non-clickbait openings for science Shorts.",
        f'''Generate {count} different hooks for this topic.
TOPIC: {topic}
SCRIPT: {script}

REQUIRED FRAMING (this is not optional style preference -- it is backed
by real view data from this exact channel): every hook MUST directly
address the viewer using "you"/"your", either by describing something
physically happening TO them, or by opening with a concrete "what if
you were standing there" scenario they can picture themselves inside.

Hooks that instead open by describing a distant object in the third
person ("Mercury bakes...", "Saturn's rings are...", "Massive galaxy
clusters...") have consistently landed at 0-8 views on this channel.
Hooks using direct "you/your" framing or a personal "what if" scenario
have landed at 500-1,100+ views on the exact same channel, same
production quality, same topics -- the ONLY consistent difference is
this framing choice in the first sentence.

Good examples (real, from this channel's top performers):
- "If you spoke on Saturn's moon Titan, your voice would suddenly drop..."
- "What if a twin of Earth has been hiding directly behind the Sun this whole time?"
- "...happening inside your own eyeball" (opening on a bodily/physical effect)

Bad examples (real, from this channel's 0-view videos -- do not do this):
- "Ten kilometers beneath Jupiter's icy crust..."
- "Mercury bakes under extreme heat..."
- "Massive galaxy clusters dominate the cosmos..."

Every single hook you generate must pass this test: does it put the
viewer inside the scenario in the first sentence, using "you" or "your"
or a "what if you..." framing? If a hook describes an object/place
without ever addressing the viewer directly, rewrite it before
including it.

Return {{"hooks":[{{"hook":"...","clarity":1,"curiosity":1,"retention":1,"science_safety":1}}]}}.''',
        max_output_tokens=1800,
    )
    return result.get("hooks", []) if isinstance(result, dict) else []
