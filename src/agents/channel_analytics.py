"""
channel_analytics.py
Fetches REAL YouTube Analytics data (views, retention, subscribers
gained) for previously published videos, joins it against
video_registry.py's logged topics, and produces a compact ranked summary
suitable for injecting straight into an agent prompt -- so topic
selection can actually learn from what's performed well on this specific
channel, instead of only guessing from abstract curiosity/novelty scores.

Fails safe everywhere: returns None/empty on any failure (no analytics
token yet, too little history, an API error) -- callers should treat
that as "no performance context available this run", never as an error
that should block the pipeline.
"""
from datetime import datetime, timedelta, timezone

from src.agents.video_registry import recent_videos
from src.analytics_auth import get_analytics_service

# Videos need at least this many days live before their stats are
# considered meaningful -- a video published yesterday having "0 views"
# doesn't mean the topic was bad, it means it hasn't had time yet.
MIN_AGE_DAYS = 3
LOOKBACK_DAYS = 90


def fetch_video_performance(youtube_analytics, video_ids: list) -> dict:
    """Returns {video_id: {"views": int, "avg_view_pct": float,
    "subscribers_gained": int}} for the given video IDs. Empty dict on
    any failure or if video_ids is empty."""
    if not video_ids:
        return {}
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=LOOKBACK_DAYS)
        response = youtube_analytics.reports().query(
            ids="channel==MINE",
            startDate=start.strftime("%Y-%m-%d"),
            endDate=end.strftime("%Y-%m-%d"),
            metrics="views,averageViewPercentage,subscribersGained",
            dimensions="video",
            filters=f"video=={','.join(video_ids)}",
            maxResults=200,
        ).execute()

        rows = response.get("rows", [])
        headers = [h["name"] for h in response.get("columnHeaders", [])]
        result = {}
        for row in rows:
            entry = dict(zip(headers, row))
            vid = entry.get("video")
            if vid:
                result[vid] = {
                    "views": entry.get("views", 0),
                    "avg_view_pct": entry.get("averageViewPercentage", 0),
                    "subscribers_gained": entry.get("subscribersGained", 0),
                }
        return result
    except Exception as e:
        print(f"WARNING: fetching video performance failed ({e}); "
              f"no analytics context available this run.")
        return {}


def build_performance_summary(channel_id: str, token_path: str,
                               client_secret_path: str = None,
                               max_examples: int = 10) -> str:
    """Main entry point. Returns a compact text block ranking past
    topics by real performance (views + retention), for injection into
    an agent prompt -- or None if there isn't enough usable data yet
    (no analytics token, too few old-enough videos, API failure)."""
    try:
        registry = recent_videos(channel_id, limit=200)
    except Exception:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)
    eligible = []
    for entry in registry:
        recorded_at = entry.get("recorded_at")
        video_id = entry.get("video_id")
        topic = entry.get("topic")
        if not (recorded_at and video_id and topic):
            continue
        try:
            published = datetime.fromisoformat(recorded_at)
        except ValueError:
            continue
        if published <= cutoff:
            eligible.append(entry)

    if len(eligible) < 5:
        print(f"Analytics: only {len(eligible)} videos old enough to "
              f"have meaningful stats -- skipping performance context "
              f"this run (need at least 5).")
        return None

    try:
        youtube_analytics = get_analytics_service(token_path, client_secret_path)
    except Exception as e:
        print(f"WARNING: could not authenticate for Analytics ({e}); "
              f"no performance context available this run.")
        return None

    video_ids = [e["video_id"] for e in eligible]
    performance = fetch_video_performance(youtube_analytics, video_ids)
    if not performance:
        return None

    scored = []
    for entry in eligible:
        vid = entry["video_id"]
        if vid not in performance:
            continue
        stats = performance[vid]
        # Simple combined score: views matter, but a video that holds
        # attention (retention) is the stronger signal for what topics
        # to repeat -- weighting retention noticeably higher than raw
        # views so a low-view-but-high-retention topic still surfaces.
        combined = stats["views"] * 0.4 + stats["avg_view_pct"] * 10 * 0.6
        scored.append((combined, entry["topic"], stats))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_examples]
    bottom = scored[-max_examples:] if len(scored) > max_examples else []

    lines = ["TOP PERFORMING PAST TOPICS ON THIS CHANNEL (real data):"]
    for _, topic, stats in top:
        lines.append(f"- \"{topic}\" -- {stats['views']} views, "
                      f"{stats['avg_view_pct']:.0f}% avg retention")

    if bottom:
        lines.append("")
        lines.append("LOWER PERFORMING PAST TOPICS (avoid repeating this pattern):")
        for _, topic, stats in bottom:
            lines.append(f"- \"{topic}\" -- {stats['views']} views, "
                          f"{stats['avg_view_pct']:.0f}% avg retention")

    summary = "\n".join(lines)
    print(f"Analytics: built performance summary from {len(scored)} "
          f"videos with real data.")
    return summary
