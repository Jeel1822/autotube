"""
packaging_agent.py
Integrates the yt-script hook scoring logic and yt-package title linter logic
into the autotube pipeline.
"""
from pathlib import Path
import json
import os
import re

ROOT = Path(__file__).resolve().parent.parent.parent
FORMULAS_PATH = ROOT / "src" / "data" / "hook_formulas.json"

try:
    FORMULAS = json.loads(FORMULAS_PATH.read_text())["hooks"]
except Exception:
    FORMULAS = []

FILLER = {"basically","actually","literally","just","really","very","so","kind","sort","like",
          "guys","hey","welcome","today","video","subscribe","channel"}
VAGUE = {"amazing","incredible","insane","crazy","huge","massive","game","changer","secret",
         "powerful","ultimate","best","revolutionary","mind","blowing","unbelievable"}
CONCRETE = re.compile(r"\b(\d[\d,.]*\s?(%|k|m|x|s|m|h)?|\$\d|\d+\s?(second|minute|hour|day|week|month|year)s?)\b", re.I)
YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
STAKE = re.compile(r"\b(lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dying|dead)\b", re.I)
CURIOSITY = re.compile(r"\b(why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b", re.I)

from pathlib import Path

def words(t): return re.findall(r"[a-z0-9'%$.]+", t.lower())

def score_hook(t: str) -> int:
    """Scores a single hook string (0-100) using the yt-script hookscore logic."""
    if not t:
        return 0
    w = words(t)
    nums = len(CONCRETE.findall(t))
    vague = sum(1 for x in w if x in VAGUE)
    filler = sum(1 for x in w if x in FILLER)
    spec = max(0, min(100, 34 + nums * 22 - vague * 16 - filler * 5))

    n_you = len(YOU.findall(t))
    first = 30 if YOU.search(" ".join(t.split()[:6])) else 0
    addr = max(0, min(100, 26 + n_you * 20 + first))

    n_stake = len(STAKE.findall(t))
    stake = max(0, min(100, 22 + n_stake * 26 + (14 if CONCRETE.search(t) else 0)))

    n_cur = len(CURIOSITY.findall(t))
    q = 18 if t.strip().endswith("?") else 0
    closed = -18 if re.search(r"\b(because|so that|which means)\b", t, re.I) else 0
    cur = max(0, min(100, 24 + n_cur * 17 + q + closed))

    n_words = len(w)
    if n_words == 0:
        brev = 0
    elif 9 <= n_words <= 24:
        brev = 100
    elif n_words < 9:
        brev = max(30, 100 - (9 - n_words) * 11)
    else:
        brev = max(10, 100 - (n_words - 24) * 7)

    vals = [spec, addr, stake, cur, brev]
    verdict = round(0.6 * (sum(vals) / len(vals)) + 0.4 * min(vals))
    return verdict


def lint_title_and_thumbnail(title: str, thumb: str = None) -> dict:
    """ lints a title and thumbnail pairing using the yt-package logic."""
    t = title.strip()
    n = len(t)
    issues, good = [], []
    if n > 100: issues.append(("length", f"{n} characters - hard limit is 100"))
    elif n > 60: issues.append(("length", f"{n} characters - desktop search cuts near 60"))
    else: good.append(f"{n} characters, inside desktop cut")

    v = [w for w in words(t) if w in VAGUE]
    if v: issues.append(("vague", f"{', '.join(sorted(set(v)))} - swap for a number or name"))

    nums = re.findall(r"\d[\d,.]*%?", t)
    if nums: good.append(f"carries concrete figure ({', '.join(nums[:3])})")
    else: issues.append(("no-number", "no number, date or name"))

    if thumb:
        tw, hw = set(words(t)) - {"the","a","an","of","for","to","in","on","and","or","is","are","with","your","you","my","i","this","that","it","how","what","why"}, set(words(thumb)) - {"the","a","an","of","for","to","in","on","and","or","is","are","with","your","you","my","i","this","that","it","how","what","why"}
        shared = tw & hw
        if shared:
            issues.append(("duplicate", f"thumbnail repeats title on {', '.join(sorted(shared))}"))
        else:
            good.append("thumbnail and title carry different words")

    score = max(0, min(100, 100 - 14 * len(issues) + 4 * len(good)))
    return {"title": t, "score": score, "issues": issues, "good": good}
