"""
fetch_stock.py
Downloads free stock video clips from Pexels matching the video topic,
so we have background footage to lay the voiceover over.

Requires a free PEXELS_API_KEY (https://www.pexels.com/api/ — instant
approval, no cost, generous rate limit).
"""
import os
import re
from pathlib import Path

import requests

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


def _extract_keywords(topic: str, max_words: int = 3) -> str:
    """Very simple keyword extraction: drop stopwords, keep the meatiest words."""
    stopwords = {
        "the", "a", "an", "of", "in", "on", "to", "why", "what", "how",
        "your", "you", "we", "and", "is", "was", "it", "that", "for",
        "happened", "most", "people", "don't", "know", "after", "when",
    }
    words = re.findall(r"[a-zA-Z]+", topic.lower())
    keywords = [w for w in words if w not in stopwords]
    return " ".join(keywords[:max_words]) if keywords else topic


def fetch_clips_for_topic(topic: str, out_dir: str, count: int = 5,
                            orientation: str = "landscape") -> list:
    """
    Downloads `count` short stock clips relevant to `topic` into out_dir.
    orientation: 'landscape' for long-form, 'portrait' for shorts.
    Returns list of downloaded file paths.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "PEXELS_API_KEY not set. Get a free key at https://www.pexels.com/api/"
        )

    query = _extract_keywords(topic)
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": count,
        "orientation": orientation,
        "size": "medium",
    }

    resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    videos = data.get("videos", [])
    if not videos:
        # Fall back to a generic/abstract query so the pipeline never stalls
        params["query"] = "abstract background"
        resp = requests.get(PEXELS_SEARCH_URL, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        videos = resp.json().get("videos", [])

    for i, video in enumerate(videos[:count]):
        # Pick a reasonably sized file (avoid 4K to save bandwidth/time)
        files = sorted(video["video_files"], key=lambda f: f.get("width", 0))
        target = next((f for f in files if 720 <= f.get("width", 0) <= 1920), files[-1])

        clip_path = out_dir / f"clip_{i}.mp4"
        with requests.get(target["link"], stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(clip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        downloaded.append(str(clip_path))

    return downloaded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("out_dir")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--portrait", action="store_true")
    args = parser.parse_args()

    orientation = "portrait" if args.portrait else "landscape"
    paths = fetch_clips_for_topic(args.topic, args.out_dir, args.count, orientation)
    print("\n".join(paths))
