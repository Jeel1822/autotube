"""
trend_scout.py
Picks a topic based on real current signal (top Reddit posts, top-ranking
YouTube search results) instead of only drawing from a static, hand-written
topic file. Falls back to returning None on ANY failure -- missing API
key, network issue, rate limit, empty results -- so the caller
(generate_script.py) can always fall back to the existing static topic
list. This feature is additive and optional; it should never be able to
break a run.

Two free data sources:
- Reddit's public .json endpoints (no auth needed for read-only access,
  just a descriptive User-Agent -- Reddit blocks the default python-requests
  UA string).
- YouTube Data API v3 search endpoint (needs a simple API key, NOT the
  OAuth token used for uploads -- create one at
  https://console.cloud.google.com/apis/credentials in the same project,
  then set it as the YOUTUBE_DATA_API_KEY environment variable / repo
  secret. Optional: Reddit signal alone is enough to run without it.
"""
import os
import re
from datetime import datetime, timedelta, timezone

import requests

try:
    from google import genai as genai_client
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

GEMINI_MODEL = "gemini-3.5-flash-lite"  # keep in sync with generate_script.py


def _fetch_reddit_trending(subreddit: str, limit: int = 12) -> list:
    """Top posts from the last week. Read-only, no auth required -- just
    needs a real User-Agent or Reddit returns 429s."""
    try:
        resp = requests.get(
            f"https://www.reddit.com/r/{subreddit}/top.json",
            params={"t": "week", "limit": limit},
            headers={"User-Agent": "autotube-trend-scout/1.0"},
            timeout=10,
        )
        resp.raise_for_status()
        posts = resp.json()["data"]["children"]
        titles = [p["data"]["title"] for p in posts if not p["data"].get("stickied")]
        return titles
    except Exception as e:
        print(f"WARNING: Reddit trend fetch failed ({e}); skipping this signal.")
        return []


def _fetch_youtube_trending(query: str, max_results: int = 10) -> list:
    """Recent, relevance-ranked video titles for the niche -- a proxy for
    what's currently getting attention in this space on YouTube itself."""
    api_key = os.environ.get("YOUTUBE_DATA_API_KEY")
    if not api_key:
        return []
    try:
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=14)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet", "q": query, "type": "video",
                "order": "viewCount", "publishedAfter": published_after,
                "maxResults": max_results, "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [item["snippet"]["title"] for item in items]
    except Exception as e:
        print(f"WARNING: YouTube trend fetch failed ({e}); skipping this signal.")
        return []


def _synthesize_topic(signal_titles: list, config: dict) -> str:
    """Feeds the raw trend signal to Gemini and asks it to produce ONE
    original topic phrase in the channel's existing style -- inspired by
    what's currently getting attention, but reworded into a fresh,
    specific, video-worthy topic. Never returns a raw scraped title
    verbatim (attribution/copyright safety, and consistency with the
    channel's established topic phrasing)."""
    client = genai_client.Client(api_key=os.environ["GEMINI_API_KEY"])
    signal_text = "\n".join(f"- {t}" for t in signal_titles[:15])

    prompt = f"""You are a trend researcher for a YouTube channel.

Channel niche: {config['niche']}
Tone: {config['tone']}

Here are titles of posts/videos currently getting real attention in or
near this niche:
{signal_text}

Based on what these have in common (recurring themes, what seems to be
capturing curiosity right now), propose ONE single fresh topic for this
channel's next video. It must be:
- An ORIGINAL phrase in this channel's own style (see examples of the
  channel's existing topic phrasing below) -- never copy any title above
  verbatim
- Specific and concrete enough to film/narrate (not vague like "space is
  interesting")
- Something with a clear factual answer/reveal, suitable for the niche

Existing topic style examples from this channel:
- "Why the sky is dark at night even though there are trillions of stars"
- "What would happen if you fell into a black hole"
- "The star that's so big it would swallow Saturn's orbit"

Respond with ONLY the topic phrase itself, one line, no quotes, no
preamble, no explanation."""

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    topic = response.text.strip().strip('"').strip("'")
    # Guard against an empty or absurdly long response derailing the pipeline
    if not topic or len(topic) > 200:
        raise ValueError(f"Unusable synthesized topic: {topic!r}")
    return topic


def get_trending_topic(channel_id: str, config: dict) -> str:
    """Main entry point. Returns a fresh, trend-inspired topic string, or
    None if trend data wasn't available for any reason -- callers should
    fall back to the static topic list in that case, never treat this as
    fatal."""
    if not config.get("trend_aware"):
        return None
    if not (GEMINI_AVAILABLE and os.environ.get("GEMINI_API_KEY")):
        return None

    subreddit = config.get("trend_subreddit")
    signal = []
    if subreddit:
        signal += _fetch_reddit_trending(subreddit)
    signal += _fetch_youtube_trending(config.get("niche", channel_id))

    if not signal:
        print("Trend Scout: no trend signal available this run, falling back to static topics.")
        return None

    try:
        topic = _synthesize_topic(signal, config)
        print(f"Trend Scout: synthesized topic from {len(signal)} signal items -> {topic!r}")
        return topic
    except Exception as e:
        print(f"WARNING: Trend Scout topic synthesis failed ({e}); falling back to static topics.")
        return None
