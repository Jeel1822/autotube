"""
Repair Agent:
Automated handler for failed video assembly or validation.
"""
def attempt_repair(error_log: str):
    """Analyzes the FFmpeg/Validation failure and suggests parameters."""
    if "duration mismatch" in error_log.lower():
        return {"action": "recalculate_durations", "params": {"tolerance": 2.0}}
    return {"action": "full_rebuild", "params": {"preset": "veryslow"}}
