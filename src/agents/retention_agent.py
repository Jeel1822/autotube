from src.agents.orchestrator import run_json_batch


def review_script(topic: str, script: str) -> dict:
    return run_json_batch(
        "Retention Editor",
        "Improve pacing AND make the script sound like a real person "
        "talking, not an AI narrator reading facts, without weakening "
        "scientific accuracy.",
        f'''Analyze this script.
TOPIC: {topic}
SCRIPT: {script}

Rewrite it to sound like a genuine person explaining this to a friend,
not a documentary narrator or an AI reading a Wikipedia summary. Concretely:
- Use contractions (it's, that's, you'd, don't) -- avoid "it is", "that is"
- Vary sentence length -- mix short punchy sentences with longer ones,
  the way people actually talk, not uniform textbook-length sentences
- Cut any phrase that sounds like a formal essay opener ("Imagine a
  world where...", "It is fascinating to note that...") -- start more
  like someone mid-thought ("Okay so here's the wild part...", "So get
  this...")
- Allow one small natural aside or reaction if it fits (a quick "wild,
  right?" or "yeah, really") -- don't force it if it doesn't fit naturally
- Keep every fact and number exactly as accurate as the original -- this
  is a tone/phrasing rewrite, not a content rewrite

CRITICAL PACING RULE FOR LONGER SCRIPTS (backed by real retention data
from this exact channel): a strong opening hook gets the click, but if
the actual payoff/main "wow" fact doesn't land within the first 15-20
seconds of narration (roughly the first 40-50 words), viewers bail
before getting there no matter how good the hook was. One real example
from this channel: a script hooked hard ("get ready to feel deeply
uncomfortable... the universe is tearing itself apart") but then spent
15+ seconds on scene-setting and context before delivering the actual
dark-energy explanation -- result: 107 views but only 11% average
retention, viewers left after ~17 seconds, never reaching the payoff.

If this script is longer than ~15 sentences and the core "wow" fact/
explanation doesn't appear until after several sentences of build-up,
context, or scene-setting, MOVE the core payoff earlier -- ideally into
the second or third sentence, right after the hook -- even if that means
restructuring the order of explanation. Save deeper context/mechanism
detail for after the payoff has already landed, not before it.

Return {{"score":1,"weak_points":["..."],"changes":["..."],"improved_script":"..."}}.''',
        max_output_tokens=2500,
    )
