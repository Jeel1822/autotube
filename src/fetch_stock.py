
"""
fetch_stock.py

Smart Pexels stock-video retrieval for the AutoTube pipeline.

V2 improvements:

- Generates multiple search queries from the topic.
- Tries several increasingly broad queries.
- Avoids weak generic keyword extraction.
- Prefers videos matching the requested orientation.
- Avoids downloading the same Pexels video twice.
- Keeps file sizes reasonable.
- Falls back to abstract space visuals when necessary.
- Never makes the rest of the pipeline responsible for Pexels failures.
"""

import os
import re
from pathlib import Path

import requests


PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "to",
    "why", "what", "how", "your", "you", "we",
    "and", "is", "was", "it", "that", "for",
    "when", "are", "were", "be", "been",
    "being", "do", "does", "did", "can",
    "could", "will", "would", "should",
    "shall", "may", "might", "must",
    "has", "have", "had", "this", "these",
    "those", "from", "near", "where", "which",
    "who", "whom", "with", "by", "at", "as",
    "if", "than", "then", "so", "not", "no",
    "actually", "really", "just", "one",
    "single", "every", "any", "some",
    "possible", "possibly", "or", "but",
    "there", "here", "reason", "its",
    "it's", "happen", "happens",
    "happening", "would", "could",
}


def _topic_words(topic: str) -> list:
    """
    Extract meaningful words from the topic.
    """

    words = re.findall(
        r"[a-zA-Z]+",
        topic.lower(),
    )

    return [
        word
        for word in words
        if word not in STOPWORDS
        and len(word) >= 3
    ]


def _build_search_queries(topic: str) -> list:
    """
    Build several queries ordered from specific to broad.

    Example:

        "What happens when a star gets too close to a black hole"

    becomes something like:

        star black hole
        black hole star space
        black hole astronomy
        space astronomy
    """

    words = _topic_words(topic)

    queries = []

    if words:
        queries.append(
            " ".join(words[:4])
        )

    if len(words) >= 2:
        queries.append(
            " ".join(words[:3]) + " space"
        )

    if "black" in words and "hole" in words:
        queries.extend([
            "black hole space",
            "black hole astronomy",
        ])

    if "star" in words:
        queries.extend([
            "star space",
            "stars astronomy",
        ])

    if "planet" in words:
        queries.extend([
            "planet space",
            "planet astronomy",
        ])

    if "neutron" in words:
        queries.extend([
            "neutron star",
            "neutron star space",
        ])

    if "galaxy" in words:
        queries.extend([
            "galaxy space",
            "galaxy astronomy",
        ])

    if "gravity" in words:
        queries.extend([
            "gravity space",
            "gravity physics",
        ])

    if "moon" in words:
        queries.extend([
            "moon space",
            "moon astronomy",
        ])

    if "sun" in words:
        queries.extend([
            "sun space",
            "sun astronomy",
        ])

    # General fallback queries.
    queries.extend([
        "space astronomy",
        "deep space",
        "cosmos",
        "stars universe",
    ])

    # Remove duplicates while preserving order.
    return list(dict.fromkeys(queries))


def _search_pexels(
    query: str,
    headers: dict,
    orientation: str,
    per_page: int = 8,
) -> list:
    """
    Search Pexels and return videos.
    """

    params = {
        "query": query,
        "per_page": per_page,
        "orientation": orientation,
        "size": "medium",
    }

    response = requests.get(
        PEXELS_SEARCH_URL,
        headers=headers,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.json().get(
        "videos",
        [],
    )


def _choose_video_file(video: dict):
    """
    Select a sensible resolution.

    Prefer roughly 720p-1080p to keep the automated pipeline fast.
    """

    files = video.get(
        "video_files",
        [],
    )

    if not files:
        return None

    suitable = [
        item
        for item in files
        if 720 <= item.get("width", 0) <= 1920
    ]

    if suitable:
        # Prefer the smallest suitable file.
        return sorted(
            suitable,
            key=lambda item: (
                item.get("width", 0),
                item.get("height", 0),
            ),
        )[0]

    return sorted(
        files,
        key=lambda item: item.get("width", 0),
    )[0]


def _score_video(video: dict, orientation: str) -> float:
    """
    Lightweight visual suitability score.

    Pexels does not expose semantic relevance scoring, so this combines:

    - orientation
    - resolution
    - duration
    """

    width = video.get("width") or 0
    height = video.get("height") or 0
    duration = video.get("duration") or 0

    if width <= 0 or height <= 0:
        return 0

    score = 0

    ratio = width / height

    if orientation == "portrait":
        if ratio < 1:
            score += 5
        elif ratio < 1.2:
            score += 3
    else:
        if ratio > 1.4:
            score += 5
        elif ratio > 1.1:
            score += 3

    if 5 <= duration <= 30:
        score += 2
    elif duration > 30:
        score += 1

    if width >= 720:
        score += 2

    return score


def fetch_clips_for_topic(
    topic: str,
    out_dir: str,
    count: int = 5,
    orientation: str = "landscape",
) -> list:
    """
    Download stock clips relevant to the topic.

    Multiple Pexels searches are attempted.

    Returns a list of downloaded file paths.
    """

    api_key = os.environ.get(
        "PEXELS_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "PEXELS_API_KEY not set. "
            "Get a free key at https://www.pexels.com/api/"
        )

    headers = {
        "Authorization": api_key,
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    queries = _build_search_queries(
        topic
    )

    videos_by_id = {}

    # ---------------------------------------------------------
    # SEARCH MULTIPLE QUERIES
    # ---------------------------------------------------------

    for query in queries:

        try:
            videos = _search_pexels(
                query,
                headers,
                orientation,
                per_page=8,
            )

        except Exception as e:
            print(
                f"WARNING: Pexels search failed for "
                f"'{query}' ({e})"
            )
            continue

        for video in videos:

            video_id = video.get("id")

            if video_id:
                videos_by_id[video_id] = video

        # Stop searching once we have enough candidates.
        if len(videos_by_id) >= count * 3:
            break

    # ---------------------------------------------------------
    # FALLBACK SEARCH
    # ---------------------------------------------------------

    if not videos_by_id:

        fallback_queries = [
            "abstract space",
            "stars universe",
            "deep space",
        ]

        for query in fallback_queries:

            try:
                videos = _search_pexels(
                    query,
                    headers,
                    orientation,
                    per_page=10,
                )

                for video in videos:
                    video_id = video.get("id")

                    if video_id:
                        videos_by_id[video_id] = video

                if videos_by_id:
                    break

            except Exception:
                continue

    if not videos_by_id:
        raise RuntimeError(
            f"Pexels returned no usable videos for topic: {topic}"
        )

    # ---------------------------------------------------------
    # RANK VIDEOS
    # ---------------------------------------------------------

    ranked = sorted(
        videos_by_id.values(),
        key=lambda video: _score_video(
            video,
            orientation,
        ),
        reverse=True,
    )

    selected = ranked[:count]

    downloaded = []

    # ---------------------------------------------------------
    # DOWNLOAD
    # ---------------------------------------------------------

    for i, video in enumerate(selected):

        target = _choose_video_file(
            video
        )

        if not target:
            continue

        url = target.get("link")

        if not url:
            continue

        clip_path = (
            out_dir / f"clip_{i}.mp4"
        )

        try:

            with requests.get(
                url,
                stream=True,
                timeout=60,
            ) as response:

                response.raise_for_status()

                with open(
                    clip_path,
                    "wb",
                ) as f:

                    for chunk in response.iter_content(
                        chunk_size=1024 * 64
                    ):

                        if chunk:
                            f.write(chunk)

            if clip_path.exists() and clip_path.stat().st_size > 10000:
                downloaded.append(
                    str(clip_path)
                )

        except Exception as e:

            print(
                f"WARNING: failed downloading "
                f"Pexels clip ({e})"
            )

            if clip_path.exists():
                try:
                    clip_path.unlink()
                except OSError:
                    pass

    if not downloaded:
        raise RuntimeError(
            f"Could not download usable Pexels footage "
            f"for topic: {topic}"
        )

    print(
        f"Pexels: topic={topic!r}"
    )

    print(
        "Pexels queries tried: "
        + " | ".join(queries[:6])
    )

    print(
        f"Pexels: selected {len(downloaded)} clips"
    )

    return downloaded


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "topic"
    )

    parser.add_argument(
        "out_dir"
    )

    parser.add_argument(
        "--count",
        type=int,
        default=5,
    )

    parser.add_argument(
        "--portrait",
        action="store_true",
    )

    args = parser.parse_args()

    orientation = (
        "portrait"
        if args.portrait
        else "landscape"
    )

    paths = fetch_clips_for_topic(
        args.topic,
        args.out_dir,
        args.count,
        orientation,
    )

    print(
        "\n".join(paths)
    )
