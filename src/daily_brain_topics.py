"""
daily_brain_topics.py
Runs the AI Daily Brain (src/agents/agent_manager.py) at most once per UTC
day per channel, and distributes its ranked winner list across that day's
video slots: long-form gets winner #1, each Short consumes the next
ranked winner in order. This mirrors the existing recap-short pattern
(one shared daily state file, consumed slot by slot) but scaled from a
single recap topic to a ranked list of 5.

Fails safe at every step -- any failure (Gemini call fails, agents/
import fails, empty winners list) returns None, and the caller
(generate_script.py) falls straight through to the existing Trend Scout
/ static topic list, exactly as before. This should never make a run
less reliable, only potentially better-researched when it works.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"


def _brain_state_path(channel_id: str) -> Path:
    """Tracks how many of today's ranked winners have been consumed so
    far, separate from the actual brain report (which agents/memory.py
    already saves to state/{channel_id}/daily_brain/{date}.json)."""
    return STATE_DIR / f"{channel_id}_daily_brain_progress.json"


def _load_todays_report(channel_id: str) -> dict:
    """Reads today's saved brain report if agent_manager already ran
    today (via save_daily_brain in agents/memory.py). Returns {} if
    there isn't one yet -- caller decides whether to generate one."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = STATE_DIR / channel_id / "daily_brain" / f"{day}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _run_daily_brain_once(channel_id: str) -> dict:
    """Actually invokes the 5-stage agent pipeline. Only called when
    today has no cached report yet. Any failure here (rate limit,
    science-guardian rejecting everything, etc.) is caught by the
    caller, get_daily_brain_topic()."""
    from src.agents.agent_manager import run_daily_brain
    return run_daily_brain(channel_id)


def get_daily_brain_topic(channel_id: str, config: dict, is_short: bool) -> str:
    """Main entry point. Returns a topic string from today's ranked
    winner list, running the Daily Brain first if it hasn't run yet
    today. Returns None on any failure or if this channel doesn't have
    use_daily_brain enabled -- callers must treat that as "fall back to
    the existing topic-picking logic", not as an error."""
    if not config.get("use_daily_brain"):
        return None

    report = _load_todays_report(channel_id)
    if not report:
        try:
            print("Daily Brain: no report cached for today yet -- running now "
                  "(this happens once per day; later calls today reuse it).")
            report = _run_daily_brain_once(channel_id)
        except Exception as e:
            print(f"WARNING: Daily Brain run failed ({e}); falling back to "
                  f"Trend Scout / static topics.")
            return None

    winners = report.get("winners") or []
    if not winners:
        return None

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    progress_path = _brain_state_path(channel_id)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        progress = {}
    if progress.get("date") != day:
        progress = {"date": day, "long_form_used": False, "shorts_used": 0}

    # Long-form always gets the #1 ranked winner. Each Short works
    # through winners in rank order (2nd, 3rd, ...); if there are more
    # Shorts than winners, it wraps back to the start of the list rather
    # than running out.
    if not is_short:
        if progress["long_form_used"]:
            return None  # today's long-form slot already got its topic
        progress["long_form_used"] = True
        topic = winners[0].get("topic")
    else:
        index = (progress["shorts_used"] + 1) % len(winners)  # +1 to skip the long-form's winner[0] when possible
        if len(winners) == 1:
            index = 0
        topic = winners[index].get("topic")
        progress["shorts_used"] += 1

    progress_path.write_text(json.dumps(progress))
    return topic
