"""
Standalone diagnostic: checks whether edge-tts's hi-IN-MadhurNeural voice
actually emits WordBoundary events. Both the caption burn-in and the
mascot mouth-flap in generate_kids_video.py depend on this data -- if it
comes back empty, that explains both symptoms at once (no captions, mouth
never swaps to the talking frame) without either step crashing, since both
degrade silently to "nothing to show" rather than erroring.

Run from the repo root: python3 check_timing.py
"""
import sys
sys.path.insert(0, "src")
from tts import synthesize_speech
import json

text = "आओ बच्चों पास हमारे रंग-बिरंगे प्यारे सारे"
synthesize_speech(text, "hi-IN-MadhurNeural", "/tmp/test_audio.mp3", "/tmp/test_timing.json")

timing = json.loads(open("/tmp/test_timing.json").read())
print(f"Word boundary count: {len(timing)}")
if timing:
    print("First 3 entries:", timing[:3])
else:
    print("EMPTY -- no WordBoundary events were captured for this voice.")
