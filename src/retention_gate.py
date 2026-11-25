"""
retention_gate.py -- cheap, deterministic Short-script checks tied to what the
channel's own data shows (videos watched >= ~25% got ~12x the median views).

No API calls. Returns a list of human-readable problems; empty list = pass.
Wired into quality_gate.check_script when config use_retention_gate is true, so
problems go through the existing repair loop.
"""
import re

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "it", "its",
         "you", "your", "this", "that", "for", "with", "as", "at", "by", "be",
         "are", "was", "will", "than", "then", "so", "but", "if", "from"}

HOOK_MAX_WORDS = 14       # first sentence must land fast
MAX_WORDS_PER_SECOND = 3.0
LOOP_MIN_SHARED = 1


def _sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _content_words(sentence: str) -> set:
    return {w for w in re.findall(r"[a-z']+", sentence.lower())
            if w not in _STOP and len(w) > 2}


def retention_problems(script: str, short_seconds: int = 45) -> list:
    problems = []
    sents = _sentences(script or "")
    if len(sents) < 3:
        return ["Script needs at least 3 sentences (hook, payoff, closer)."]

    hook = sents[0]
    if len(hook.split()) > HOOK_MAX_WORDS:
        problems.append(
            f"Hook is {len(hook.split())} words; state the strange claim in "
            f"<= {HOOK_MAX_WORDS} words so viewers don't swipe in the first 3 seconds.")
    if hook.endswith("?"):
        problems.append("Open with the claim, not a question.")
    if re.match(r"^(in this video|today|welcome|hey|hi|let's|did you know)\b",
                hook.lower()):
        problems.append("Hook is a wind-up; cut straight to the claim.")

    words = len(re.findall(r"\b\w+\b", script))
    if short_seconds and words / max(short_seconds, 1) > MAX_WORDS_PER_SECOND:
        problems.append(
            f"{words} words is too dense for {short_seconds}s "
            f"(> {MAX_WORDS_PER_SECOND} words/sec); viewers will drop off.")

    # Loop: the last line should echo the first so autoplay feels seamless and
    # rewatches count toward watch-through.
    shared = _content_words(hook) & _content_words(sents[-1])
    if len(shared) < LOOP_MIN_SHARED:
        problems.append(
            "Ending doesn't echo the opening. Close by reusing a key word from "
            "the hook so the Short loops back into itself.")

    # Payoff early: the surprising number/claim should appear in the first half.
    half = " ".join(sents[: max(2, len(sents) // 2)])
    if not re.search(r"\d", half) and len(_content_words(half)) < 8:
        problems.append("Deliver the main payoff in the first half, not the end.")
    return problems
