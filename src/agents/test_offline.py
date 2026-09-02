"""Offline structural tests for the Cosmic Curious agent layer.

Run with:
    python3 -m src.agents.test_offline

This file does not import google-genai and therefore does not require API
keys, installed third-party packages, or network access.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "src" / "agents"


def extract_json_without_dependencies(text: str):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        starts = [p for p in (cleaned.find("{"), cleaned.find("[")) if p >= 0]
        if not starts:
            raise
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        return json.loads(cleaned[start:end + 1])


def main() -> None:
    py_files = sorted(AGENTS.glob("*.py"))
    for path in py_files:
        ast.parse(path.read_text(), filename=str(path))

    assert extract_json_without_dependencies('{"ok": true}') == {"ok": True}
    assert extract_json_without_dependencies('```json\n{"ok": true}\n```') == {"ok": True}
    assert extract_json_without_dependencies('prefix [1, 2, 3] suffix') == [1, 2, 3]

    sample_report = {
        "channel_id": "cosmic_curious",
        "winners": [{"topic": "Example", "score": 90}],
    }
    assert json.loads(json.dumps(sample_report))["channel_id"] == "cosmic_curious"

    required = {"agent_manager.py", "production_agent.py", "video_registry.py", "ceo_agent.py"}
    assert required.issubset({x.name for x in py_files}), "Missing core V1.6 agent modules"

    print(f"OFFLINE AGENT TEST: OK ({len(py_files)} Python files parsed)")


if __name__ == "__main__":
    main()
