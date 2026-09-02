"""Persistent registry for Cosmic Curious production and publishing."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"


def _path(channel_id: str) -> Path:
    return STATE_DIR / channel_id / "video_registry.json"


def load_registry(channel_id: str) -> list[dict]:
    path = _path(channel_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record_video(channel_id: str, record: dict) -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(channel_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = load_registry(channel_id)
    entry = dict(record)
    entry.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
    rows.append(entry)
    rows = rows[-1000:]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    return entry


def recent_videos(channel_id: str, limit: int = 50) -> list[dict]:
    return load_registry(channel_id)[-limit:]
