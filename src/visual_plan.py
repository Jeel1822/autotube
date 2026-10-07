"""
visual_plan.py

Turns the narration's word timings into short "beats" (roughly one sentence
or clause each) and asks Gemini for a concrete stock-footage search query
per beat, so the footage on screen illustrates what is being said at that
moment instead of one topic-wide search shared by the whole video.

Every step fails safe: if Gemini is unavailable or returns junk, each beat
gets a keyword-derived query, and the caller can still fall back to the
old topic-level fetch_clips_for_topic().
"""

import json
import re
from pathlib import Path

SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")
CLAUSE_END = re.compile(r"[,;:\u2014\u2013][\"')\]]*$")

# Words that make poor stock-footage searches on their own.
_FILLER = {
    "the", "a", "an", "of", "in", "on", "to", "and", "is", "was", "it", "that",
    "for", "with", "as", "at", "by", "from", "this", "these", "those", "you",
    "your", "yours", "are", "were", "be", "been", "has", "have", "had", "but",
    "or", "so", "not", "no", "just", "than", "then", "there", "here", "what",
    "why", "how", "when", "where", "which", "who", "can", "could", "will",
    "would", "its", "it's", "they", "them", "their", "we", "our", "us", "i",
    "right", "now", "literally", "actually", "really", "every", "entire",
}


def build_beats(timing_path: str, min_seconds: float = 2.0,
                max_seconds: float = 4.5) -> list:
    """
    Group word timings into contiguous beats.

    A beat closes at a sentence end once it is at least `min_seconds` long,
    at a clause break once it is ~70% of `max_seconds`, or by force once it
    exceeds 1.1x `max_seconds` (for run-on sentences with no punctuation).

    Returns [{"start": float, "end": float, "text": str}, ...]. Beats are
    contiguous: the first starts at 0 and the last ends at the final word's
    end, so the clip durations always add up to the full narration.
    """
    words = json.loads(Path(timing_path).read_text())
    if not words:
        return []

    beats, current = [], []

    def close():
        if not current:
            return
        beats.append({
            "start": current[0]["offset_seconds"],
            "end": current[-1]["offset_seconds"] + current[-1]["duration_seconds"],
            "text": " ".join(w["text"] for w in current),
        })
        current.clear()

    for word in words:
        current.append(word)
        span = (word["offset_seconds"] + word["duration_seconds"]
                - current[0]["offset_seconds"])
        text = word["text"]
        if SENTENCE_END.search(text) and span >= min_seconds:
            close()
        elif CLAUSE_END.search(text) and span >= max_seconds * 0.7:
            close()
        elif span >= max_seconds * 1.1:
            close()
    close()

    # A tiny trailing beat (e.g. a last two-word line) gets merged backwards
    # so we never spend a whole clip on under a second of narration.
    if len(beats) >= 2 and beats[-1]["end"] - beats[-1]["start"] < 1.2:
        tail = beats.pop()
        beats[-1]["end"] = tail["end"]
        beats[-1]["text"] += " " + tail["text"]

    # Make them contiguous.
    beats[0]["start"] = 0.0
    for prev, nxt in zip(beats, beats[1:]):
        prev["end"] = nxt["start"]
    return beats


def _keyword_query(text: str, topic: str) -> dict:
    """Last-resort query for a beat when Gemini gave us nothing usable."""
    words = [w for w in re.findall(r"[a-zA-Z]+", text.lower())
             if w not in _FILLER and len(w) >= 4]
    topic_words = [w for w in re.findall(r"[a-zA-Z]+", topic.lower())
                   if w not in _FILLER and len(w) >= 4]
    query = " ".join(words[:2]) if words else " ".join(topic_words[:2])
    fallback = " ".join(topic_words[:2]) if topic_words else "space astronomy"
    return {"query": query or "space astronomy", "fallback": fallback}


def plan_queries(beats: list, topic: str, niche: str = "science and space facts") -> list:
    """
    Add "query" and "fallback" keys to every beat (mutates and returns it).

    One Gemini call covers all beats. Queries are required to be concrete,
    filmable things (objects, places, natural phenomena), because stock
    libraries index what is physically visible, not abstract ideas.
    """
    if not beats:
        return beats

    numbered = "\n".join(f"{i}. {b['text']}" for i, b in enumerate(beats))
    prompt = f"""
You are choosing stock footage for a vertical YouTube Short about {niche}.
Topic: {topic}

Below are the narration lines in order. For EACH line, give a stock-video
search query (2-4 words) for footage that visually illustrates that exact
line, plus a broader fallback query (1-3 words) in case the first finds
nothing good.

Rules:
- Describe something concrete and filmable: an object, place, animal,
  natural phenomenon, or simple human action. Stock libraries cannot
  search abstract ideas like "time dilation" or "frame dragging".
- Translate abstract claims into a visual metaphor that exists in stock
  footage (for "time ticks slower" use "wall clock close up"; for
  "gravity pulls" use "apple falling" or "earth from space").
- Prefer science, space, nature, and technology imagery. Avoid queries that
  mostly return unrelated things (street scenes, animals, crowds, food).
- Do not repeat the same query for neighbouring lines; vary the visuals.
- No people-identifying terms, no brand names, no text or logo requests.

Return ONLY JSON in exactly this shape, one entry per line, same order:
{{"beats": [{{"i": 0, "query": "...", "fallback": "..."}}]}}

NARRATION LINES:
{numbered}
"""
    planned = {}
    try:
        from src.agents.orchestrator import generate_json
        data = generate_json(prompt, max_output_tokens=2500)
        for item in data.get("beats", []):
            idx = int(item.get("i", -1))
            query = str(item.get("query", "")).strip()
            fallback = str(item.get("fallback", "")).strip()
            if 0 <= idx < len(beats) and query:
                planned[idx] = {"query": query, "fallback": fallback or query}
    except Exception as e:  # noqa: BLE001 - never let planning break a build
        print(f"WARNING: visual planning failed ({e}); using keyword queries.")

    for i, beat in enumerate(beats):
        choice = planned.get(i) or _keyword_query(beat["text"], topic)
        beat["query"] = choice["query"]
        beat["fallback"] = choice["fallback"]

    shown = " | ".join(b["query"] for b in beats[:8])
    print(f"Visual plan: {len(beats)} beats ({len(planned)} from Gemini): {shown}")
    return beats
