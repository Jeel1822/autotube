import sys
import os
from src.trend_scout import _fetch_youtube_trending
from src.agents.trend_jacker_agent import extract_viral_hook
from src.main import generate_and_upload

def run_instant_jack(channel_id: str, niche: str):
    print(f"Jack: Searching for viral outliers in {niche}...")
    
    # 1. Fetch viral outliers (high view-to-sub ratio)
    outliers = _fetch_youtube_trending(niche, max_results=3)
    
    if not outliers:
        print("Jack: No viral outliers found right now.")
        return

    # 2. Analyze the first one
    target = outliers[0]
    print(f"Jack: Found viral target: {target}")
    analysis = extract_viral_hook(target)
    
    if not analysis or "new_hook" not in analysis:
        print("Jack: Failed to synthesize new hook.")
        return
        
    print(f"Jack: Generated new viral-ready hook: {analysis['new_hook']}")
    
    # 3. Trigger immediate generation as a Short
    # We pass the new_hook as the topic. 
    # generate_and_upload handles the full assembly/upload flow.
    generate_and_upload(channel_id, topic=analysis['new_hook'], is_short=True)

if __name__ == "__main__":
    cid = sys.argv[1]
    niche = sys.argv[2]
    run_instant_jack(cid, niche)
