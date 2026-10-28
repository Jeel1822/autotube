"""
channel_sync.py -- the automatic learning loop.

Pulls the channel's REAL upload history from the public YouTube Data API
(only needs YOUTUBE_DATA_API_KEY, the same key Trend Scout already uses --
no extra OAuth scope) and:

  1. Backfills state/<channel>/video_registry.json with every upload the
     registry has never seen, so channel_analytics.py has real history to
     learn from (before this, only videos uploaded by main.py were logged).
  2. Computes state/<channel>/performance_snapshot.json: baseline hit-rate,
     the current top performers, the latest titles (for duplicate checks),
     measured hit-rates for each winning pattern, upload-cadence stats, and
     warnings when one of the filter's own hard rules stops matching reality.
  3. content_filter.load_playbook() merges that snapshot over the hand-written
     playbook, so the Topic Hunter / Chief Editor prompts and the duplicate
     checks update themselves with no manual export.

Run automatically (at most every sync_max_age_days, default 7) at the start
of the Daily Brain, or by hand:

    python3 -m src.channel_sync cosmic_curious --force

Everything here is best-effort: any failure prints a warning and returns
None; it must never block video production.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"

# Standalone runs (python3 -m src.channel_sync ...) don't go through main.py,
# so load the project's .env here too (same file main.py uses).
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass
API = "https://www.googleapis.com/youtube/v3"

MIN_AGE_DAYS = 3            # younger videos haven't had time to show their stats
DEFAULT_HIT_VIEWS = 250     # a Short "hits" at this many views (override in config)
DEFAULT_SHORT_MAX_S = 75


# --------------------------------------------------------------------------
# Low-level API helpers
# --------------------------------------------------------------------------

def _api_key() -> str:
    key = os.environ.get("YOUTUBE_DATA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_DATA_API_KEY is not set.")
    return key


def _get(endpoint: str, **params) -> dict:
    resp = requests.get(
        f"{API}/{endpoint}",
        params={**params, "key": _api_key()},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def iso_duration_seconds(value: str) -> int:
    """'PT1M5S' -> 65."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


# --------------------------------------------------------------------------
# State files
# --------------------------------------------------------------------------

def _state(channel_id: str, name: str) -> Path:
    return STATE_DIR / channel_id / name


def load_snapshot(channel_id: str):
    path = _state(channel_id, "performance_snapshot.json")
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except Exception:
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------
# Channel id resolution (no extra permissions needed)
# --------------------------------------------------------------------------

def resolve_channel_id(channel_id: str, config: dict):
    """
    The channel's YouTube id (UC...). Order: config `youtube_channel_id`,
    env YOUTUBE_CHANNEL_ID, a cached value, then auto-detect from the video
    ids already in the registry (public videos.list tells us the owner).
    """
    explicit = (config.get("youtube_channel_id")
                or os.environ.get("YOUTUBE_CHANNEL_ID") or "").strip()
    if explicit:
        return explicit

    cache = _state(channel_id, "youtube_channel.json")
    try:
        if cache.exists():
            cached = json.loads(cache.read_text()).get("youtube_channel_id")
            if cached:
                return cached
    except Exception:
        pass

    try:
        from src.agents.video_registry import load_registry
        ids = [e["video_id"] for e in load_registry(channel_id)
               if e.get("video_id")][-50:]
        if not ids:
            return None
        items = _get("videos", part="snippet", id=",".join(ids)).get("items", [])
        owners = Counter(i["snippet"]["channelId"] for i in items)
        if owners:
            found = owners.most_common(1)[0][0]
            _write_json(cache, {"youtube_channel_id": found})
            return found
    except Exception as e:
        print(f"WARNING: could not auto-detect the YouTube channel id ({e}). "
              f"Set youtube_channel_id in the channel yaml.")
    return None


# --------------------------------------------------------------------------
# Fetch every upload
# --------------------------------------------------------------------------

def fetch_uploads(yt_channel_id: str, max_videos: int = 1000) -> list:
    """All public uploads, newest first:
    [{video_id, title, published_at, duration_s, views}]."""
    ch = _get("channels", part="contentDetails", id=yt_channel_id).get("items", [])
    if not ch:
        raise RuntimeError(f"No YouTube channel found for id {yt_channel_id}.")
    uploads = ch[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, token = [], None
    while len(ids) < max_videos:
        params = dict(part="contentDetails", playlistId=uploads, maxResults=50)
        if token:
            params["pageToken"] = token
        page = _get("playlistItems", **params)
        ids += [i["contentDetails"]["videoId"] for i in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            break

    videos = []
    for batch in _chunks(ids[:max_videos], 50):
        items = _get("videos", part="snippet,contentDetails,statistics",
                     id=",".join(batch)).get("items", [])
        for it in items:
            videos.append({
                "video_id": it["id"],
                "title": it["snippet"]["title"],
                "published_at": it["snippet"]["publishedAt"],
                "duration_s": iso_duration_seconds(
                    it["contentDetails"].get("duration", "")),
                "views": int(it.get("statistics", {}).get("viewCount", 0) or 0),
            })
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


# --------------------------------------------------------------------------
# Registry backfill
# --------------------------------------------------------------------------

def clean_title(title: str) -> str:
    return re.sub(r"\s*#shorts\b", "", title, flags=re.I).strip()


def backfill_registry(channel_id: str, videos: list, short_max_s: int) -> int:
    """Add uploads the registry has never seen. Returns how many were added."""
    from src.agents.video_registry import load_registry, _path

    rows = load_registry(channel_id)
    known = {r.get("video_id") for r in rows if r.get("video_id")}
    added = 0
    for v in videos:
        if v["video_id"] in known:
            continue
        rows.append({
            "video_id": v["video_id"],
            "topic": clean_title(v["title"]),
            "title": v["title"],
            "is_short": v["duration_s"] <= short_max_s,
            "language": "en",
            "recorded_at": v["published_at"],
            "source": "backfill",
        })
        added += 1
    if added:
        rows.sort(key=lambda r: str(r.get("recorded_at", "")))
        _write_json(_path(channel_id), rows[-1000:])
    return added


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------

def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_title(title).lower()).strip()


def _rate(views: list, hit: int):
    n = len(views)
    return {
        "n": n,
        "hit_rate": round(sum(v >= hit for v in views) / n, 3) if n else None,
        "median": statistics.median(views) if n else None,
    }


def compute_snapshot(videos: list, playbook: dict, config: dict) -> dict:
    from src.agents.content_filter import _tag_topic

    hit = int(config.get("playbook_hit_views", DEFAULT_HIT_VIEWS))
    short_max = int(config.get("short_max_seconds", DEFAULT_SHORT_MAX_S))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MIN_AGE_DAYS)

    def published(v):
        return datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))

    shorts_all = [v for v in videos if v["duration_s"] <= short_max]
    long_all = [v for v in videos if v["duration_s"] > short_max]
    shorts = [v for v in shorts_all if published(v) <= cutoff]  # mature stats only

    flt = (playbook or {}).get("filter", {}) or {}
    boost = flt.get("boost") or {}
    views_of = lambda vs: [v["views"] for v in vs]

    baseline = _rate(views_of(shorts), hit)

    # --- measured hit-rate per pattern ---------------------------------
    pattern_stats = {}
    tagged = {v["video_id"]: _tag_topic(clean_title(v["title"]), boost)
              for v in shorts}
    for tag in boost:
        pattern_stats[tag] = _rate(
            [v["views"] for v in shorts if tag in tagged[v["video_id"]]], hit)
    pattern_stats["short_title(<=6 words)"] = _rate(
        [v["views"] for v in shorts if len(clean_title(v["title"]).split()) <= 6],
        hit)

    # --- hard rules vs reality (self-check) -----------------------------
    warnings = []
    min_n = 25
    for prefix in flt.get("reject_prefixes", []) or []:
        sel = [v["views"] for v in shorts
               if clean_title(v["title"]).lower().startswith(str(prefix).lower())]
        st = _rate(sel, hit)
        pattern_stats[f"opens with '{str(prefix).strip()}'"] = st
        if (st["n"] >= min_n and baseline["hit_rate"] is not None
                and st["hit_rate"] >= baseline["hit_rate"]):
            warnings.append(
                f"Rule 'reject titles opening with \"{str(prefix).strip()}\"' no "
                f"longer matches the data: {st['hit_rate']:.0%} hit-rate "
                f"(n={st['n']}) vs baseline {baseline['hit_rate']:.0%}. "
                f"Consider removing it from the playbook.")
    for term in flt.get("jargon_terms", []) or []:
        sel = [v["views"] for v in shorts if str(term).lower() in v["title"].lower()]
        st = _rate(sel, hit)
        if (st["n"] >= 8 and baseline["hit_rate"] is not None
                and st["hit_rate"] > max(baseline["hit_rate"], 0.2)):
            warnings.append(
                f"Jargon term '{term}' is doing BETTER than baseline "
                f"({st['hit_rate']:.0%}, n={st['n']}); consider removing it.")

    # --- cadence: uploads per day vs results ---------------------------
    per_day = Counter(published(v).date() for v in shorts_all)
    low = [v["views"] for v in shorts if per_day[published(v).date()] <= 3]
    high = [v["views"] for v in shorts if per_day[published(v).date()] >= 4]
    cadence = {"1-3_per_day": _rate(low, hit), "4+_per_day": _rate(high, hit)}

    # --- top performers & recent titles --------------------------------
    works, seen = [], set()
    for v in sorted(shorts, key=lambda x: -x["views"]):
        if v["views"] < hit or len(works) >= 14:
            break
        key = _norm(v["title"])
        if key in seen:
            continue
        seen.add(key)
        works.append(clean_title(v["title"]))

    recent_titles = [clean_title(v["title"]) for v in shorts_all[:30]][::-1]

    long_views = views_of(long_all)
    return {
        "generated_at": now.isoformat(),
        "hit_views": hit,
        "n_shorts_measured": len(shorts),
        "n_long": len(long_all),
        "baseline": baseline,
        "pattern_stats": pattern_stats,
        "cadence": cadence,
        "long_form": {"n": len(long_all), "total_views": sum(long_views),
                      "median": statistics.median(long_views) if long_views else None},
        "rule_warnings": warnings,
        "works": works,
        "seed_recent_titles": recent_titles,
        "views_by_id": {v["video_id"]: v["views"] for v in videos},
    }


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def sync_channel(channel_id: str, config: dict, playbook: dict = None):
    """Fetch, backfill and write the snapshot. Returns the snapshot or None."""
    try:
        yt_id = resolve_channel_id(channel_id, config)
        if not yt_id:
            print("Channel sync: no YouTube channel id (set youtube_channel_id "
                  "in the channel yaml); skipping.")
            return None
        videos = fetch_uploads(yt_id)
        if not videos:
            print("Channel sync: the channel returned no videos; skipping.")
            return None

        if playbook is None:
            from src.agents.content_filter import load_playbook
            playbook = load_playbook(channel_id)

        short_max = int(config.get("short_max_seconds", DEFAULT_SHORT_MAX_S))
        added = backfill_registry(channel_id, videos, short_max)
        snap = compute_snapshot(videos, playbook, config)
        snap["youtube_channel_id"] = yt_id
        _write_json(_state(channel_id, "performance_snapshot.json"), snap)

        # Run retention_critic post-mortem on recent videos if we have snapshot data
        if snap and snap.get("views_by_id"):
            try:
                from src.agents.retention_critic import run_post_mortem
                views_map = snap["views_by_id"]
                hit_thresh = snap.get("hit_views", 250)
                # Pick the 3 most recent videos to audit
                for v in videos[:3]:
                    vid = v["video_id"]
                    if vid in views_map:
                        run_post_mortem(channel_id, vid, v["title"], views_map[vid], hit_thresh)
            except Exception as e:
                print(f"WARNING: retention_critic post-mortem failed ({e}).")
        for w in snap["rule_warnings"]:
            print(f"  WARNING: {w}")
        return snap
    except Exception as e:
        print(f"WARNING: channel sync failed ({e}); continuing without it.")
        return None


def maybe_sync(channel_id: str, config: dict):
    """Sync at most every sync_max_age_days (default 7). Never raises."""
    try:
        max_age = float(config.get("sync_max_age_days", 7))
        snap = load_snapshot(channel_id)
        if snap:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(
                snap["generated_at"])
            if age < timedelta(days=max_age):
                return snap
        return sync_channel(channel_id, config) or snap
    except Exception as e:
        print(f"WARNING: channel sync skipped ({e}).")
        return None


if __name__ == "__main__":
    import yaml
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cid = sys.argv[1]
    cfg = yaml.safe_load((ROOT / "channels" / f"{cid}.yaml").read_text())
    result = sync_channel(cid, cfg) if "--force" in sys.argv else maybe_sync(cid, cfg)
    if result:
        print(json.dumps({k: v for k, v in result.items()
                          if k not in ("views_by_id", "seed_recent_titles")},
                         indent=2))
