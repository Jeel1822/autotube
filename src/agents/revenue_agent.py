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

# Niche affiliate mappings with intent keywords
AFFILIATE_CATALOG = {
    "telescope": {
        "keywords": ["moon", "saturn", "rings", "crater", "star", "galaxy", "nebula"],
        "link_template": "https://autotube.store/gear/pro-telescope",
        "cta": "🔭 Want to see this yourself? Check out the recommended beginner telescope:"
    },
    "space_map": {
        "keywords": ["constellation", "milky way", "sun", "solar system", "orbit"],
        "link_template": "https://autotube.store/gear/cosmic-map",
        "cta": "🌌 Map the universe from your wall. High-res Cosmic Chart:"
    },
    "audio_gear": {
        "keywords": ["sound", "hear", "whistle", "lightning", "atmosphere"],
        "link_template": "https://autotube.store/gear/studio-headphones",
        "cta": "🎧 Experience space audio in full fidelity:"
    }
}

def inject_affiliate_cta(script_text: str, description_text: str) -> tuple[str, str | None]:
    """
    Scans script for high-intent keywords and appends a relevant,
    non-intrusive affiliate link to the YouTube description.
    """
    low_script = script_text.lower()

    for category, details in AFFILIATE_CATALOG.items():
        for kw in details["keywords"]:
            if re.search(rf"\b{re.escape(kw)}\b", low_script):
                cta_block = f"\n\n{details['cta']}\n{details['link_template']}"
                updated_description = description_text + cta_block
                print(f"[REVENUE ENGINE] Contextual CTA Injected: {category} (keyword: {kw})")
                return updated_description, category

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
