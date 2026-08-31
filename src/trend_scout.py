
"""
trend_scout.py

Current-signal discovery for Cosmic Curious.

V2 strategy:

YouTube -> optional Reddit -> Gemini synthesis

Reddit is treated as an optional signal only.

If Reddit returns 403/429/network errors, the system continues silently
without it.

If no trend source works, the caller falls back to Topic Brain/static topics.

The trend system never becomes a hard dependency for video generation.

Gemini calls are routed through gemini_client.py so the project uses the
current chat.send_message() flow instead of direct models.generate_content().
"""

import os
from datetime import datetime, timedelta, timezone

import requests

try:
    from .gemini_client import generate as gemini_generate
    GEMINI_AVAILABLE = True
except ImportError:
    try:
        from gemini_client import generate as gemini_generate
        GEMINI_AVAILABLE = True
    except ImportError:
        GEMINI_AVAILABLE = False


def _fetch_reddit_trending(subreddit: str, limit: int = 12) -> list:
    """
    Optional Reddit signal.

    Reddit can block automated requests, so failures are deliberately
    ignored.
    """

    try:
        resp = requests.get(
            f"https://www.reddit.com/r/{subreddit}/top.json",
            params={
                "t": "week",
                "limit": limit,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/120 Safari/537.36"
                )
            },
            timeout=10,
        )

        resp.raise_for_status()

        posts = resp.json()["data"]["children"]

        return [
            p["data"]["title"]
            for p in posts
            if not p["data"].get("stickied")
        ]

    except Exception:
        # Reddit is optional. Don't spam the pipeline logs with a 403
        # every run.
        return []


def _fetch_youtube_trending(query: str, max_results: int = 15) -> list:
    """
    Use YouTube Data API search as the primary trend signal.

    Requires:

        YOUTUBE_DATA_API_KEY

    This is intentionally separate from the OAuth credentials used for
    uploading videos.
    """

    api_key = os.environ.get("YOUTUBE_DATA_API_KEY")

    if not api_key:
        return []

    try:
        published_after = (
            datetime.now(timezone.utc)
            - timedelta(days=30)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "maxResults": max_results,
                "key": api_key,
            },
            timeout=15,
        )

        resp.raise_for_status()

        items = resp.json().get("items", [])

        return [
            item["snippet"]["title"]
            for item in items
            if item.get("snippet", {}).get("title")
        ]

    except Exception as e:
        print(
            f"WARNING: YouTube trend fetch failed ({e}); "
            f"skipping this signal."
        )

        return []


def _synthesize_topic(signal_titles: list, config: dict) -> str:
    """
    Convert current trend signals into ONE original topic.

    Never copies a source title verbatim.

    Gemini is accessed through the centralized gemini_client wrapper.
    """

    signal_text = "\n".join(
        f"- {title}"
        for title in signal_titles[:25]
    )

    prompt = f"""
You are a trend researcher for a high-retention science YouTube channel.

CHANNEL:
{config['display_name']}

NICHE:
{config['niche']}

TONE:
{config['tone']}

These are recent titles getting attention:

{signal_text}

Find the underlying scientific themes that are attracting attention.

Then create ONE completely ORIGINAL topic for this channel.

IMPORTANT:

Do NOT copy any title.

Do NOT simply paraphrase a title.

Instead, identify the scientific curiosity behind the trend and create a
new, specific question or phenomenon.

The topic must:

- be scientifically defensible
- have a surprising answer
- work in a 30-60 second Short
- have strong visual potential
- create a strong curiosity gap
- be understandable to a general audience
- avoid generic school-level science
- avoid fake mystery
- avoid unsupported speculation

DO NOT use phrases such as:

"Scientists are terrified"
"NASA doesn't want you to know"
"This changes everything"
"Scientists can't explain"

unless literally supported by the evidence.

Return ONLY the topic itself.

One line.
No quotes.
No explanation.
"""

    # IMPORTANT:
    # Do not use client.models.generate_content() here.
    # gemini_generate() internally uses:
    #
    #     client.chats.create(...)
    #     chat.send_message(...)
    #
    # which avoids the AFC warning from the old direct model call.
    topic = gemini_generate(prompt).strip().strip('"').strip("'")

    if not topic or len(topic) > 200:
        raise ValueError(
            f"Unusable synthesized topic: {topic!r}"
        )

    return topic


def get_trending_topic(channel_id: str, config: dict):
    """
    Main entry point.

    Strategy:

        1. YouTube signal
        2. Reddit signal
        3. Gemini synthesis

    Returns None when no reliable signal is available.
    """

    if not config.get("trend_aware"):
        return None

    if not (
        GEMINI_AVAILABLE
        and os.environ.get("GEMINI_API_KEY")
    ):
        return None

    signal = []

    # ---------------------------------------------------------
    # YouTube = PRIMARY SIGNAL
    # ---------------------------------------------------------

    youtube_signal = _fetch_youtube_trending(
        config.get("niche", channel_id)
    )

    if youtube_signal:
        signal.extend(youtube_signal)

        print(
            f"Trend Scout: received "
            f"{len(youtube_signal)} YouTube signals."
        )

    # ---------------------------------------------------------
    # Reddit = OPTIONAL SIGNAL
    # ---------------------------------------------------------

    subreddit = config.get("trend_subreddit")

    if subreddit:
        reddit_signal = _fetch_reddit_trending(
            subreddit
        )

        if reddit_signal:
            signal.extend(reddit_signal)

            print(
                f"Trend Scout: received "
                f"{len(reddit_signal)} Reddit signals."
            )

    # ---------------------------------------------------------
    # No trend signal
    # ---------------------------------------------------------

    if not signal:
        print(
            "Trend Scout: no current signal available; "
            "falling back to Topic Brain/static topics."
        )

        return None

    # Remove duplicates while preserving order.
    signal = list(dict.fromkeys(signal))

    # ---------------------------------------------------------
    # Gemini synthesis
    # ---------------------------------------------------------

    try:
        topic = _synthesize_topic(
            signal,
            config,
        )

        print(
            f"Trend Scout: synthesized topic from "
            f"{len(signal)} signal items -> {topic!r}"
        )

        return topic

    except Exception as e:
        print(
            f"WARNING: Trend Scout synthesis failed ({e}); "
            f"falling back to Topic Brain/static topics."
        )

        return None
