"""
scheduler.py
Runs hourly (triggered by GitHub Actions cron). For each ENABLED channel,
checks whether the current UTC hour matches that channel's configured
upload times, and runs main.py for exactly what's due — 1 long-form video
at its scheduled hour, and up to 1 short at each of its 5 scheduled hours.

This keeps the total at exactly 1 long + 5 shorts per channel per day,
regardless of how often the cron itself fires.

Which channels actually run is controlled by the ENABLED_CHANNELS env var
(comma-separated channel_ids, e.g. "mind_bites"). This lets you bring
channels online one at a time as you finish setting up their YouTube
tokens, instead of the scheduler trying (and failing) to upload to
channels that aren't authorized yet. If ENABLED_CHANNELS is unset, ALL
channels in channels/*.yaml run — only unset it once every channel has
a real token.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _hour_matches(time_str: str, current_hour: int) -> bool:
    """time_str is HH:MM — match on the hour component."""
    return int(time_str.split(":")[0]) == current_hour


def _enabled_channel_ids() -> set | None:
    """Returns None if all channels are enabled, else a set of allowed ids."""
    raw = os.environ.get("ENABLED_CHANNELS", "").strip()
    if not raw:
        return None
    return {c.strip() for c in raw.split(",") if c.strip()}


def main():
    current_hour = datetime.now(timezone.utc).hour
    channels_dir = ROOT / "channels"
    enabled = _enabled_channel_ids()
    ran_any = False

    for config_path in sorted(channels_dir.glob("*.yaml")):
        config = yaml.safe_load(config_path.read_text())
        channel_id = config["channel_id"]

        if enabled is not None and channel_id not in enabled:
            continue  # not set up yet — skip silently

        jobs_due = []
        if _hour_matches(config["upload_time_utc"], current_hour):
            jobs_due.append(False)  # False = not a short (long-form)
        for t in config["shorts_upload_times_utc"]:
            if _hour_matches(t, current_hour):
                jobs_due.append(True)  # True = is a short

        for is_short in jobs_due:
            ran_any = True
            label = "SHORT" if is_short else "LONG-FORM"
            print(f"\n### {channel_id} — {label} due at hour {current_hour} UTC ###\n")
            cmd = [sys.executable, str(ROOT / "src" / "main.py"), channel_id]
            if is_short:
                cmd.append("--short")

            result = subprocess.run(cmd)
            if result.returncode != 0:
                print(f"WARNING: {channel_id} {label} run failed (exit {result.returncode})",
                      file=sys.stderr)
                # Deliberately don't sys.exit here — one channel failing
                # shouldn't block the others in the same hourly tick.

    if not ran_any:
        print(f"Nothing scheduled for hour {current_hour} UTC. Nothing to do.")


if __name__ == "__main__":
    main()
