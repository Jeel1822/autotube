"""Deterministic content filter for Daily Brain candidates.

Runs BEFORE the (LLM) Novelty/Science guardians, costs no Gemini calls, and
is driven by channels/{channel_id}_playbook.yaml so it can be retuned from
analytics without code changes. It removes the patterns that real analytics
showed get ~0 views: jargon-built topics, over-long colon titles, near
duplicates of recent uploads, and a 3rd topic on the same subject within a
short window.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "is",
    "are", "was", "were", "be", "it", "its", "this", "that", "with", "by",
    "what", "why", "how", "when", "if", "would", "could", "do", "does", "did",
    "you", "your", "we", "our", "from", "as", "into", "than", "then", "so",
    "about", "actually", "really", "happens", "happen", "like",
}


def load_playbook(channel_id: str) -> dict:
    path = ROOT / "channels" / f"{channel_id}_playbook.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text())
        data = data if isinstance(data, dict) else {}
    except Exception as e:  # never block the pipeline on a bad playbook
        print(f"WARNING: could not read playbook {path.name} ({e}); "
              f"content filter disabled this run.")
        return {}
    return _merge_snapshot(channel_id, data)


def _merge_snapshot(channel_id: str, playbook: dict) -> dict:
    """Overlay the auto-generated performance snapshot (channel_sync.py) on
    the hand-written playbook: fresh top performers, the latest titles for
    duplicate checks, and measured hit-rates. Rules/patterns stay hand-edited.
    Ignored if missing or older than 30 days."""
    try:
        from datetime import datetime, timedelta, timezone
        from src.channel_sync import load_snapshot
        snap = load_snapshot(channel_id)
        if not snap:
            return playbook
        age = datetime.now(timezone.utc) - datetime.fromisoformat(
            snap["generated_at"])
        if age > timedelta(days=30):
            return playbook
        merged = dict(playbook)
        if snap.get("works"):
            merged["works"] = snap["works"]
        if snap.get("seed_recent_titles"):
            merged["seed_recent_titles"] = snap["seed_recent_titles"]
        merged["measured"] = {
            "date": snap["generated_at"][:10],
            "hit_views": snap.get("hit_views"),
            "n": snap.get("n_shorts_measured"),
            "baseline": snap.get("baseline", {}),
            "patterns": snap.get("pattern_stats", {}),
            "warnings": snap.get("rule_warnings", []),
        }
        return merged
    except Exception:
        return playbook


def playbook_prompt_block(playbook: dict) -> str:
    """Text for the Topic Hunter / Chief Editor prompts ('' if no playbook)."""
    if not playbook:
        return ""
    def bullets(key):
        return "\n".join(f"- {x}" for x in playbook.get(key, []))
    block = (
        "PAST HITS ON THIS CHANNEL (real analytics; each got hundreds to "
        "1,000+ views). Use them ONLY to learn the PATTERN. Never remake, "
        "reword or continue any of these topics: every new topic must be "
        "about a DIFFERENT object or phenomenon:\n" + bullets("works") +
        "\n\nPATTERNS TO COPY:\n" + bullets("patterns") +
        "\n\nWHAT FAILS (do NOT generate or favor these):\n" + bullets("fails")
    )
    m = playbook.get("measured")
    if m and m.get("patterns"):
        base = (m.get("baseline") or {}).get("hit_rate")
        lines = []
        for name, st in m["patterns"].items():
            if st and st.get("n", 0) >= 8 and st.get("hit_rate") is not None:
                lines.append(f"- {name}: {st['hit_rate']:.0%} reach "
                             f"{m.get('hit_views')}+ views (n={st['n']})")
        if lines:
            block += (
                f"\n\nMEASURED ON THIS CHANNEL (auto-updated {m.get('date')}; "
                f"baseline {base:.0%} of {m.get('n')} Shorts reach "
                f"{m.get('hit_views')}+ views):\n" + "\n".join(lines)
                + "\nFavor patterns measured above baseline; avoid those below it."
            ) if base is not None else ""
    if playbook.get("generation_mix"):
        block += ("\n\nREQUIRED MIX FOR THIS BATCH:\n"
                  + bullets("generation_mix"))
    return block


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9']+", text.lower().replace("'s", ""))
    return {_stem(w) for w in words if w not in _STOP and len(w) > 1}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def recent_topics(channel_id: str, playbook: dict, n: int = 30) -> list:
    """Ordered (oldest->newest) recent published topics: seed list from the
    playbook, then the video registry, then memory (all best-effort)."""
    items = list(playbook.get("seed_recent_titles", []))
    try:
        from src.agents.video_registry import recent_videos
        items += [str(e.get("topic")) for e in recent_videos(channel_id, 60)
                  if e.get("topic")]
    except Exception:
        pass
    try:
        from src.agents.memory import load_memory
        items += [str(x.get("topic")) for x in
                  load_memory(channel_id).get("topics", [])
                  if isinstance(x, dict) and x.get("topic")]
    except Exception:
        pass
    seen, out = set(), []
    for t in reversed(items):  # keep the LAST occurrence order
        k = t.casefold()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return list(reversed(out))[-n:]


def all_published_titles(channel_id: str, playbook: dict) -> list:
    """EVERY known published title (seed list + the whole video registry +
    memory), not just the recent window. Duplicate checks need the full
    history: a remake of a video from three weeks ago is still a remake."""
    items = list(playbook.get("seed_recent_titles", []))
    try:
        from src.agents.video_registry import recent_videos
        items += [str(e.get("topic")) for e in recent_videos(channel_id, 5000)
                  if e.get("topic")]
    except Exception:
        pass
    try:
        from src.agents.memory import load_memory
        items += [str(x.get("topic")) for x in
                  load_memory(channel_id).get("topics", [])
                  if isinstance(x, dict) and x.get("topic")]
    except Exception:
        pass
    seen, out = set(), []
    for t in items:
        k = t.casefold()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _overlap(a: set, b: set) -> float:
    """|A & B| / min(|A|, |B|): catches a remake that only adds extra words
    (Jaccard drops fast when the new title is longer)."""
    return len(a & b) / max(1, min(len(a), len(b)))


def _is_near_duplicate(tok: set, other: set, jaccard_thr: float) -> bool:
    if _jaccard(tok, other) >= jaccard_thr:
        return True
    return min(len(tok), len(other)) >= 3 and _overlap(tok, other) >= 0.75


def remake_reason(channel_id: str, topic: str, playbook: dict = None):
    """Why `topic` is a remake of something already published, or None.
    Same duplicate rules as filter_candidates (whole history + top
    performers), usable on a single topic. Used by the Daily Brain slot
    picker so even a report cached BEFORE a filter change can't hand out a
    remake."""
    playbook = playbook if playbook is not None else load_playbook(channel_id)
    thr = float(((playbook or {}).get("filter") or {})
                .get("near_duplicate_threshold", 0.5))
    tok = _tokens(topic)
    for t in all_published_titles(channel_id, playbook or {}):
        if _is_near_duplicate(tok, _tokens(t), thr):
            return f"near-duplicate of a past video: '{t}'"
    for t in (playbook or {}).get("works", []):
        wt = _tokens(t)
        if len(tok & wt) >= 2 and _overlap(tok, wt) >= 0.5:
            return f"remake of a past top performer: '{t}'"
    return None


def _subject_hits(text: str, subjects: dict) -> set:
    low = " " + re.sub(r"[^a-z0-9' -]", " ", text.lower()) + " "
    hits = set()
    for name, words in subjects.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}\w*\b", low):
                hits.add(name)
                break
    return hits


def _tag_topic(topic: str, boost: dict) -> list:
    """Which winning archetypes a topic matches (whole-word / phrase match)."""
    low = topic.lower()
    tags = []
    for tag, phrases in (boost or {}).items():
        for ph in phrases:
            if re.search(rf"\b{re.escape(str(ph).lower().strip())}", low):
                tags.append(tag)
                break
    return tags


def filter_candidates(channel_id: str, candidates: list, playbook: dict = None):
    """Returns (kept, rejected). candidates are Topic Hunter dicts with a
    'topic' key. rejected is a list of (topic, reason)."""
    playbook = playbook if playbook is not None else load_playbook(channel_id)
    cfg = (playbook or {}).get("filter") or {}
    if not cfg:
        return list(candidates), []

    max_words = int(cfg.get("max_topic_words", 14))
    prefer_words = int(cfg.get("prefer_topic_words", 9))
    jargon = [j.lower() for j in cfg.get("jargon_terms", [])]
    dup_thr = float(cfg.get("near_duplicate_threshold", 0.5))
    cap = cfg.get("subject_cap") or {}
    subjects = cap.get("subjects") or {}
    window = int(cap.get("window", 14))
    max_per = int(cap.get("max_per_subject", 2))
    prefixes = [str(p).lower() for p in cfg.get("reject_prefixes", [])]
    boost = cfg.get("boost") or {}

    recent = recent_topics(channel_id, playbook, n=max(window, 30))
    # Duplicate checks use the WHOLE history; only the subject cap is windowed.
    history_tokens = [(t, _tokens(t))
                      for t in all_published_titles(channel_id, playbook)]
    works_tokens = [(t, _tokens(t)) for t in playbook.get("works", [])]
    window_topics = recent[-window:]
    subject_counts: dict = {}
    for t in window_topics:
        for s in _subject_hits(t, subjects):
            subject_counts[s] = subject_counts.get(s, 0) + 1

    kept, rejected = [], []
    accepted_tokens, accepted_subjects = [], {}
    for item in candidates:
        topic = str(item.get("topic", "")).strip()
        low = topic.lower()
        words = len(topic.split())
        reason = None

        pref = next((p for p in prefixes if low.startswith(p)), None)
        hit = next((j for j in jargon if j in low), None)
        if pref:
            reason = f"opens with '{pref.strip()}' (mechanism-style title)"
        elif hit:
            reason = f"jargon: '{hit}'"
        elif words > max_words:
            reason = f"too long ({words} words, max {max_words})"
        elif cfg.get("reject_colon_titles") and ":" in topic:
            reason = "colon/subtitle title"
        else:
            tok = _tokens(topic)
            dup = next((t for t, rt in history_tokens
                        if _is_near_duplicate(tok, rt, dup_thr)), None)
            remake = next((t for t, wt in works_tokens
                           if len(tok & wt) >= 2 and _overlap(tok, wt) >= 0.5),
                          None)
            if dup:
                reason = f"near-duplicate of a past video: '{dup}'"
            elif remake:
                reason = f"remake of a past top performer: '{remake}'"
            elif any(_jaccard(tok, at) >= dup_thr for at in accepted_tokens):
                reason = "near-duplicate of a stronger candidate in this batch"
            else:
                for s in _subject_hits(topic, subjects):
                    used = (subject_counts.get(s, 0)
                            + accepted_subjects.get(s, 0))
                    if used >= max_per:
                        reason = (f"subject '{s}' already used {used}x "
                                  f"in last {window} topics")
                        break

        if reason:
            rejected.append((topic, reason))
            continue

        item = dict(item)
        item["filter_tags"] = _tag_topic(topic, boost)
        if words <= prefer_words:
            item["filter_tags"].append("short")
        if words > prefer_words:
            item["filter_note"] = f"long ({words} words); prefer <= {prefer_words}"
        kept.append(item)
        accepted_tokens.append(_tokens(topic))
        for s in _subject_hits(topic, subjects):
            accepted_subjects[s] = accepted_subjects.get(s, 0) + 1
    # Candidates matching more winning archetypes go first. Downstream steps
    # only look at the first N, so this decides who gets screened (stable
    # sort: ties keep the Topic Hunter's order).
    kept.sort(key=lambda it: -len(it.get("filter_tags", [])))
    return kept, rejected
