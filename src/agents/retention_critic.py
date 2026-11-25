"""
retention_critic.py
Post-mortem on recently settled videos -> short, actionable lessons in channel
memory.

Changes vs the first version:
  * Judged against the channel's OWN median (views and, when available, real
    retention), not an absolute bar. The old bar (2,500 views) was never reached,
    so every video was labelled UNDERPERFORMER and memory filled with AVOID rules.
  * Each video is audited ONCE (tracked in memory["audited_video_ids"]); it used
    to re-audit the 3 newest videos on every sync.
  * The model is given the real numbers and told to stay within them. It still
    only sees the title, so it must state hypotheses as hypotheses.
"""
from datetime import datetime, timedelta, timezone

from src.agents.memory import load_memory, remember, save_memory
from src.agents.orchestrator import run_json_batch

MAX_AUDITS_PER_SYNC = 4
MAX_AGE_DAYS = 21  # don't dig up ancient videos on the first run


def classify(views: int, median_views: float, hit_threshold: int,
             retention_pct=None, median_retention=None) -> str:
    """HIT / ABOVE / TYPICAL / FLOP -- relative to this channel's baseline."""
    median_views = median_views or 0
    if views >= hit_threshold:
        return "HIT"
    ret_up = (retention_pct is not None and median_retention
              and retention_pct >= 1.5 * median_retention)
    if views >= max(3 * median_views, 50) or (ret_up and views >= median_views):
        return "ABOVE"
    if views < max(median_views / 2, 3):
        return "FLOP"
    return "TYPICAL"


def run_post_mortem(channel_id: str, video_id: str, title: str, views: int,
                    hit_threshold: int, stats: dict = None,
                    median_views: float = 0, median_retention=None):
    """Writes ONE lesson for ONE video. Returns the model result or None.
    TYPICAL videos teach nothing and are skipped."""
    stats = stats or {}
    ret = stats.get("avg_view_pct")
    verdict = classify(views, median_views, hit_threshold, ret, median_retention)
    if verdict == "TYPICAL":
        return None

    ret_line = (f"Average % of the video watched: {ret:.0f}% "
                f"(channel median {median_retention:.0f}%)"
                if ret is not None and median_retention else
                "Retention data: not available (views only)")
    result = run_json_batch(
        "Retention Critic",
        "Write one honest, data-grounded lesson from a single video's result.",
        f"""
Video title: {title}
Views: {views} (channel median {median_views:.0f}; 'hit' bar {hit_threshold})
{ret_line}
Verdict vs this channel's baseline: {verdict}

Rules:
- You only see the TITLE, not the script or visuals. Say what the title pattern
  suggests, phrased as a hypothesis. Do not invent facts about the video.
- HIT/ABOVE -> a lesson starting 'FAVOR' naming the replicable pattern
  (object + place + concrete claim, title length, opener type).
- FLOP -> a lesson starting 'AVOID' only if a specific title/topic pattern is
  plausibly to blame; otherwise return lesson as "".

Return JSON: {{"lesson": "...", "confidence": 0.0, "pattern_detected": "..."}}
""",
    )
    if result and isinstance(result, dict) and result.get("lesson"):
        remember(channel_id, "performance_lessons", result["lesson"])
        print(f"Post-Mortem Lesson Saved [{verdict}]: {result['lesson']}")
        return result
    return None


def audit_recent_videos(channel_id: str, videos: list, snap: dict,
                        min_age_days: int = 3) -> int:
    """Audit up to MAX_AUDITS_PER_SYNC settled, never-audited videos. Returns
    the number of lessons written."""
    mem = load_memory(channel_id)
    audited = set(mem.get("audited_video_ids", []))
    now = datetime.now(timezone.utc)

    def pub(v):
        return datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))

    ret = snap.get("retention_by_id") or {}
    median_views = (snap.get("baseline") or {}).get("median") or 0
    median_ret = (snap.get("retention_summary") or {}).get("median_avg_view_pct")
    hit = snap.get("hit_views", 250)

    todo = [v for v in videos
            if v["video_id"] not in audited
            and timedelta(days=min_age_days) <= now - pub(v) <= timedelta(days=MAX_AGE_DAYS)]
    # Most informative first: biggest winners, then biggest flops.
    todo.sort(key=lambda v: -v["views"])
    picks = todo[:2] + todo[-2:] if len(todo) > MAX_AUDITS_PER_SYNC else todo

    written = 0
    for v in picks:
        r = run_post_mortem(channel_id, v["video_id"], v["title"], v["views"], hit,
                            stats=ret.get(v["video_id"]), median_views=median_views,
                            median_retention=median_ret)
        written += 1 if r else 0
        audited.add(v["video_id"])
    if picks:
        mem = load_memory(channel_id)  # re-load: remember() wrote in between
        mem["audited_video_ids"] = sorted(audited)[-2000:]
        save_memory(channel_id, mem)
    return written
