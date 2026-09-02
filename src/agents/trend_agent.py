from src.trend_scout import _fetch_reddit_trending, _fetch_youtube_trending


def collect(config: dict) -> dict:
    youtube = _fetch_youtube_trending(config.get("niche", "science space"), 15)
    subreddit = config.get("trend_subreddit")
    reddit = _fetch_reddit_trending(subreddit, 12) if subreddit else []
    return {"youtube": youtube, "reddit": reddit}
