"""
main.py
Orchestrates one full run of the pipeline: pick topic -> generate script ->
TTS -> fetch stock footage -> assemble video -> upload to YouTube.

Usage:
    python src/main.py mind_bites --short
    python src/main.py mind_bites          # long-form

This is what the GitHub Actions workflow calls, once per video, on a schedule.
"""
import argparse
import random
import re
import sys
import tempfile
import traceback
from pathlib import Path

import yaml

from generate_script import (
    generate_script, generate_kids_script,
    save_todays_longform_topic, get_recap_topic_for_short,
)
from tts import synthesize_speech
from fetch_stock import fetch_clips_for_topic
from assemble_video import assemble_video
from generate_thumbnail import generate_thumbnail
from generate_kids_video import generate_kids_video
from generate_mascot_assets import generate_mascot_assets
from upload_youtube import upload_video

ROOT = Path(__file__).resolve().parent.parent


def load_channel_config(channel_id: str) -> dict:
    with open(ROOT / "channels" / f"{channel_id}.yaml") as f:
        return yaml.safe_load(f)


def make_title(title: str, is_short: bool) -> str:
    title = title.strip()
    if title and is_short and not title.endswith("!") and not title.endswith("?"):
        title = title.rstrip(".")
    return title[:95] + (" #Shorts" if is_short else "")


# Common short words that make weak/generic hashtags -- filtered out so
# extracted hashtags are topic-specific (#BlackHole, #Venus) rather than
# noise (#The, #Why, #Which).
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "why",
    "what", "when", "where", "which", "who", "how", "and", "or", "but",
    "of", "in", "on", "at", "to", "for", "with", "your", "you", "it",
    "its", "that", "this", "than", "than", "actually", "really", "just",
}


def _extract_hashtags_from_title(title: str, max_tags: int = 4) -> list:
    """Pulls the most distinctive words out of the title to use as
    additional hashtags, on top of the channel's fixed tag set -- keeps
    every video's hashtags at least partly unique/topic-specific instead
    of repeating the same handful every time, which helps surface videos
    in more searches."""
    words = re.findall(r"[A-Za-z]+", title)
    seen = set()
    tags = []
    for w in words:
        lw = w.lower()
        if lw in _STOPWORDS or len(w) < 4 or lw in seen:
            continue
        seen.add(lw)
        tags.append(w.capitalize())
        if len(tags) >= max_tags:
            break
    return tags


def build_description(title: str, script_text: str, topic: str,
                       channel_tags: list, is_short: bool) -> str:
    """Builds a fuller, more engaging description than a bare script
    excerpt: a hook line, the script itself, a subscribe CTA, and a wide
    hashtag block (channel tags + topic-specific ones extracted from the
    title) -- more hashtags and keyword coverage generally means more
    surface area for YouTube search/suggested to match the video against."""
    hook = f"{title.strip()} \U0001F440"  # eyes emoji -- cheap, universal curiosity cue

    extracted = _extract_hashtags_from_title(title)
    # Channel tags first (consistent branding across every video on the
    # channel), then topic-specific ones, deduped, capped so the block
    # doesn't run away in length.
    all_tag_words = list(dict.fromkeys(channel_tags + extracted))
    hashtags = " ".join("#" + t.replace(" ", "") for t in all_tag_words[:12])
    if is_short:
        hashtags += " #Shorts #ShortVideo"

    cta = "Subscribe for more mind-bending facts every day! \U0001F680"

    return (
        f"{hook}\n\n"
        f"{script_text.strip()}\n\n"
        f"{cta}\n\n"
        f"{hashtags}"
    )


def run(channel_id: str, is_short: bool, privacy_status: str = "public",
        dry_run: bool = False) -> None:
    config = load_channel_config(channel_id)
    is_kids_channel = config.get("visual_style") == "puppet_animation"
    print(f"=== Running {config['display_name']} | {'SHORT' if is_short else 'LONG-FORM'} ===")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. Script
        if is_kids_channel:
            result = generate_kids_script(channel_id, is_short=is_short)
        else:
            # For a Short, first check whether today's long-form video
            # already happened and hasn't been "recapped" yet -- if so,
            # reuse that topic instead of picking a fresh unrelated one.
            # This gives the channel one coherent daily throughline
            # (long-form + a matching recap Short) instead of 6 fully
            # disconnected topics per day, which is the standard
            # repurposing pattern most channels use Shorts for.
            forced_topic = get_recap_topic_for_short(channel_id) if is_short else None
            result = generate_script(channel_id, is_short=is_short, forced_topic=forced_topic)
            if not is_short:
                # Record today's long-form topic so the next Short run
                # (this same scheduler tick or a later one) can pick it up.
                save_todays_longform_topic(channel_id, result["topic"])
        topic, script_text = result["topic"], result["script"]
        language, voice = result["language"], result["voice"]
        print(f"Topic: {topic}")
        if is_kids_channel:
            print(f"Content type: {result['content_type']} | Mascot: {result['mascot_name']}")
        print(f"Language: {language} | Voice: {voice}")
        print(f"Script ({len(script_text.split())} words):\n{script_text}\n")

        # 2. TTS
        audio_path = tmp / "audio.mp3"
        timing_path = tmp / "timing.json"
        # A touch slower than default (-6% to -2%, randomized per video)
        # reads as more natural/deliberate than edge-tts's default pace,
        # and varying it slightly run-to-run avoids every single video on
        # the channel sounding identically, uniformly paced -- a small
        # cue that (subconsciously, across many videos) reads as "AI".
        rate = f"{random.randint(-6, -2)}%"
        synthesize_speech(script_text, voice, str(audio_path), str(timing_path), rate=rate)
        print(f"Audio generated: {audio_path}")

        # 3+4. Visuals + assembly — kids channel uses the puppet-animation
        # pipeline (mascot + lip-synced mouth), everything else uses stock
        # footage + captions.
        output_path = tmp / "final.mp4"
        if is_kids_channel:
            mascot_dir = tmp / "mascot_assets"
            frame_paths = generate_mascot_assets(result["mascot"], str(mascot_dir))
            print(f"Mascot assets ready: {frame_paths}")
            generate_kids_video(str(audio_path), str(timing_path), frame_paths,
                                 str(output_path), portrait=is_short)
        else:
            # Stock footage search query stays in English (topic is always
            # the internal English working title, regardless of script
            # language) since stock footage libraries index best in English.
            clip_count = 3 if is_short else 8
            clips_dir = tmp / "clips"
            clip_paths = fetch_clips_for_topic(
                topic, str(clips_dir), count=clip_count,
                orientation="portrait" if is_short else "landscape",
            )
            print(f"Downloaded {len(clip_paths)} clips")
            assemble_video(clip_paths, str(audio_path), str(timing_path),
                            str(output_path), portrait=is_short)
        print(f"Assembled video: {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")

        if dry_run:
            # Copy to a visible location instead of uploading, for local testing
            dest = ROOT / "output" / f"{channel_id}_{'short' if is_short else 'long'}.mp4"
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(output_path.read_bytes())
            print(f"[DRY RUN] Saved to {dest} instead of uploading")
            return

        # 5. Thumbnail — best-effort; a failure here never blocks the upload
        thumb_path = tmp / "thumbnail.jpg"
        thumbnail_result = generate_thumbnail(
            str(output_path), result["title"], str(thumb_path),
            language=language, portrait=is_short,
        )

        # 6. Upload
        title = make_title(result["title"], is_short)
        description = build_description(
            result["title"], script_text, topic, config["tags"], is_short,
        )
        # Widen the YouTube tag field too (separate from in-description
        # hashtags) -- channel tags plus topic-specific keywords pulled
        # from the title, for better search matching per video.
        video_tags = list(dict.fromkeys(
            config["tags"] + _extract_hashtags_from_title(result["title"], max_tags=6)
        ))
        token_path = ROOT / "tokens" / f"{channel_id}_token.pickle"

        video_id = upload_video(
            str(output_path), title, description, video_tags,
            config["category_id"], str(token_path),
            privacy_status=privacy_status, is_short=is_short,
            thumbnail_path=thumbnail_result,
            made_for_kids=config.get("made_for_kids", False),
        )
        print(f"Uploaded: https://youtube.com/watch?v={video_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channel_id")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--privacy", default="public",
                         choices=["public", "unlisted", "private"])
    parser.add_argument("--dry-run", action="store_true",
                         help="Build the video but don't upload — saves locally instead")
    args = parser.parse_args()

    try:
        run(args.channel_id, args.short, args.privacy, args.dry_run)
    except Exception:
        print("PIPELINE FAILED:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
