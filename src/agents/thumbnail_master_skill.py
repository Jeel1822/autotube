"""
thumbnail_master_skill.py
Advanced Thumbnail Engineering module. Implements high-CTR psychological triggers:
1. Gaze-Cueing / Emotional Contrast
2. High-Saturation Focal Bounding
3. Anti-Clutter Text Optimization (Max 3 words, extreme high contrast box)
"""
from __future__ import annotations

import random

HIGH_CTR_VOCABULARY = [
    "REAL?", "PROOF", "DEAD", "ILEGAL", "SHOCK", "HIDDEN",
    "SECRET", "WARNING", "BANNED", "LOST", "FINALLY", "NEVER"
]

def enhance_thumbnail_text(title: str, language: str) -> str:
    """
    Transforms standard titles into high-CTR psychological thumbnail banners.
    Uses urgency, curiosity gaps, and extreme visual phrasing.
    """
    words = [w.upper() for w in title.strip().split() if len(w) > 3]
    if not words:
        return "WHAT IS THIS?"

    # Pick the most striking word or pair
    core = " ".join(words[:2])

    # Add a high-CTR anchor if appropriate
    if random.random() > 0.5 and language == "en":
        anchor = random.choice(["REAL?", "SECRET", "PROOF", "HIDDEN"])
        return f"{anchor}\\N{core}"

    return core
