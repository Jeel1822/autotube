"""
revenue_agent.py
Manages monetization overlays, contextual affiliate injection,
and high-margin digital asset archiving for the Autotube pipeline.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "src" / "data"

# Affiliate catalog disabled (no external store active)
AFFILIATE_CATALOG = {}

def inject_affiliate_cta(script_text: str, description_text: str) -> tuple[str, str | None]:
    """
    Affiliate injection disabled. Returns clean description.
    """
    return description_text, None

def archive_master_asset(channel_id: str, topic: str, script: str, metadata: dict):
    """
    Archives high-value, high-retention video assets into the
    'Cosmos Vault' directory for future Tier 2 Digital Product packaging.
    """
    vault_dir = ROOT / "state" / channel_id / "cosmos_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "topic": topic,
        "script": script,
        "metadata": metadata,
        "status": "archived_for_digital_product"
    }

    # Save asset JSON for digital bundle compilation
    safe_name = re.sub(r"[^a-zA-Z0-9_]+", "_", topic.lower())[:30]
    asset_file = vault_dir / f"{safe_name}.json"
    asset_file.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"[REVENUE ENGINE] Master Asset Archived to Vault: {asset_file.name}")
