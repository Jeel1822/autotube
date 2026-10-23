
import os
import requests
from datetime import datetime, timedelta, timezone

def fetch_trending_hashtags(topic: str, max_hashtags: int = 5) -> list:
    """
    Finds top-performing YouTube videos for the given topic and extracts
    the most common tags/hashtags they use.
    """
    api_key = os.environ.get("YOUTUBE_DATA_API_KEY")
    if not api_key:
        return []

    base = "https://www.googleapis.com/youtube/v3"
    try:
        # 1. Search for top videos on the topic (last 6 months)
        published_after = (
            datetime.now(timezone.utc) - timedelta(days=180)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        resp = requests.get(
            f"{base}/search",
            params={
                "part": "snippet",
                "q": topic,
                "type": "video",
                "order": "relevance",
                "publishedAfter": published_after,
                "maxResults": 10,
                "relevanceLanguage": "en",
                "key": api_key,
            },
            timeout=10,
        )
        resp.raise_for_status()
        video_ids = [i["id"]["videoId"] for i in resp.json().get("items", [])
                     if i.get("id", {}).get("videoId")]

        if not video_ids:
            return []

        # 2. Get detailed info (including tags) for these videos
        r = requests.get(
            f"{base}/videos",
            params={
                "part": "snippet",
                "id": ",".join(video_ids),
                "key": api_key
            },
            timeout=10,
        )
        r.raise_for_status()
        videos = r.json().get("items", [])

        # 3. Extract and count tags
        tag_counts = {}
        for v in videos:
            tags = v["snippet"].get("tags", [])
            for t in tags:
                t_clean = t.lower().replace(" ", "")
                tag_counts[t_clean] = tag_counts.get(t_clean, 0) + 1

        # 4. Sort by frequency and return top ones
        sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

        # Filter out very generic tags if necessary, or just take the top ones
        # For now, just taking top N
        results = [t[0].capitalize() for t in sorted_tags[:max_hashtags]]
        return results

    except Exception as e:
        print(f"WARNING: hashtag_agent failed: {e}")
        return []
