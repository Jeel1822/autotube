"""Persistent, bounded memory for the Cosmic Curious agent team."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"


def _default_memory(channel_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "channel_id": channel_id,
        "created_at": now,
        "updated_at": now,
        "topics": [],
        "hooks": [],
        "scripts": [],
        "visual_patterns": [],
        "thumbnail_patterns": [],
        "seo_patterns": [],
        "performance_lessons": [],
        "experiments": [],
        "agent_notes": [],
    }


def _path(channel_id: str) -> Path:
    return STATE_DIR / f"{channel_id}_agent_memory.json"


def load_memory(channel_id: str) -> dict:
    path = _path(channel_id)
    if not path.exists():
        return _default_memory(channel_id)

    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("memory root must be an object")
    except Exception:
        return _default_memory(channel_id)

    base = _default_memory(channel_id)
    base.update(data)
    return base


def save_memory(channel_id: str, memory: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    _path(channel_id).write_text(
        json.dumps(memory, ensure_ascii=False, indent=2)
    )


def remember(channel_id: str, category: str, item, limit: int = 500) -> None:
    memory = load_memory(channel_id)
    bucket = memory.setdefault(category, [])
    bucket.append(item)
    memory[category] = bucket[-limit:]
    save_memory(channel_id, memory)


def recent_memory(channel_id: str, category: str, limit: int = 50) -> list:
    return load_memory(channel_id).get(category, [])[-limit:]


def load_used_topics(channel_id: str) -> set[str]:
    path = STATE_DIR / f"{channel_id}_used_topics.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        return {str(x) for x in data}
    except Exception:
        return set()


def save_daily_brain(channel_id: str, report: dict) -> Path:
    """Save the daily brain report for later analytics/learning agents."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    directory = STATE_DIR / channel_id / "daily_brain"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{day}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return path
