"""
Evolution tier: turns the channel's MEASURED results into the strategic
directive that topic_agent injects into the Topic Hunter prompt.

Previously this returned a hardcoded paragraph with a hardcoded timestamp and
never looked at any data (and nothing called it). It now reads
performance_snapshot.json (written by channel_sync) and only states what the
numbers support. With too little data it changes nothing.
"""
from datetime import datetime, timezone

from src.agents.memory import load_memory, save_memory

MIN_SHORTS = 30     # below this, medians are noise
MIN_PATTERN_N = 8   # a pattern needs this many videos to be quoted
WIN_RATIO = 1.5     # pattern median must beat baseline median by this much
LOSE_RATIO = 0.7


def build_directive(snap: dict):
    if not snap or (snap.get("n_shorts_measured") or 0) < MIN_SHORTS:
        return None
    base_med = (snap.get("baseline") or {}).get("median") or 0
    parts = []

    works = (snap.get("works") or [])[:6]
    if works:
        parts.append("Recent winners (>= %d views): %s." % (
            snap.get("hit_views", 250), "; ".join(f'"{w}"' for w in works)))

    wins, loses = [], []
    for tag, st in (snap.get("pattern_stats") or {}).items():
        if not st or (st.get("n") or 0) < MIN_PATTERN_N or st.get("median") is None:
            continue
        if base_med and st["median"] >= WIN_RATIO * base_med:
            wins.append(f"{tag} (median {st['median']:.0f} vs channel {base_med:.0f}, n={st['n']})")
        elif base_med and st["median"] <= LOSE_RATIO * base_med:
            loses.append(f"{tag} (median {st['median']:.0f}, n={st['n']})")
    if wins:
        parts.append("Patterns beating the channel median: " + "; ".join(wins) + ".")
    if loses:
        parts.append("Patterns below the channel median: " + "; ".join(loses) + ".")

    rs = snap.get("retention_summary")
    if rs and rs.get("median_views_high") is not None and rs.get("median_views_low") is not None:
        parts.append(
            "Retention is the strongest lever: Shorts watched >= %d%% on average had "
            "median %.0f views (n=%d) vs %.0f (n=%d) for the rest. Put the strange claim "
            "in the first line and keep the payoff early." % (
                rs["high_retention_cutoff_pct"], rs["median_views_high"], rs["n_high"],
                rs["median_views_low"], rs["n_low"]))

    vc = snap.get("view_ceiling") or {}
    if vc.get("n_within_5pct_of_max", 0) >= 3:
        parts.append(
            "Several Shorts stalled at ~%d views (the initial test audience). "
            "Watch-through is the likely bottleneck, not topic choice (a hypothesis)." % vc["max"])

    if not parts:
        return None
    return "DATA DIRECTIVE (auto-generated from channel stats): " + " ".join(parts)


def evolve_strategy(channel_id: str):
    from src.channel_sync import load_snapshot
    directive = build_directive(load_snapshot(channel_id))
    if not directive:
        print("[EVOLUTION TIER] Not enough data for a directive; leaving it unchanged.")
        return None
    memory = load_memory(channel_id)
    memory["evolution_directives"] = (memory.get("evolution_directives") or [])
    if not isinstance(memory["evolution_directives"], list):
        memory["evolution_directives"] = [memory["evolution_directives"]]
    memory["evolution_directives"].append({
        "directive": directive,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "snapshot",
    })
    memory["evolution_directives"] = memory["evolution_directives"][-5:]
    save_memory(channel_id, memory)
    print(f"[EVOLUTION TIER] New data-driven directive: {directive[:200]}...")
    return directive
