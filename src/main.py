"""
main.py
Orchestrates one full run of the pipeline: pick topic -> generate script ->
TTS -> fetch stock footage -> assemble video -> upload to YouTube.

Usage:
    python src/main.py mind_bites --short
    python src/main.py mind_bites          # long-form

This is what the GitHub Actions workflow calls, once per video, on a schedule.
"""
from dotenv import load_dotenv
load_dotenv()
import argparse
import random
import re
import sys
import tempfile
import traceback
from pathlib import Path

import yaml

from src.generate_script import (
    generate_script, generate_kids_script,
    save_todays_longform_topic, get_recap_topic_for_short, mark_topic_used,
)
from src.daily_brain_topics import mark_topic_rejected
from src.quality_gate import validate_and_repair
from src.tts import synthesize_speech
from src.fetch_stock import fetch_clips_for_topic
from src.assemble_video import assemble_video
from src.generate_thumbnail import generate_thumbnail
from src.generate_kids_video import generate_kids_video
from src.generate_mascot_assets import generate_mascot_assets
from src.upload_youtube import upload_video

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
    "happens", "happen", "does", "would", "could", "like", "into", "from",
    "about", "every", "after", "before", "their", "there", "when", "then",
    "have", "will", "much", "more", "most", "only", "even", "also",
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


def _summarize_for_description(title: str, script_text: str, is_short: bool) -> str:
    """Short, search-friendly description body (2-3 sentences) instead of
    pasting the whole narration. Gemini writes it; if that fails we fall
    back to the first sentences of the script."""
    try:
        from src.agents.orchestrator import generate_text
        prompt = f"""Write a YouTube video description body for this {'Short' if is_short else 'video'}.

Title: {title}

Script:
{script_text[:3500]}

Rules:
- 2 to 3 sentences, under 280 characters total.
- Say what the viewer will learn; include the main topic keywords naturally.
- Plain text only: no hashtags, no emojis, no quotes, no markdown.
- Do not give away the final payoff. Do not invent facts that aren't in the script.
Return only the description text."""
        text = generate_text(prompt, max_output_tokens=300).strip().strip('"')
        if 40 <= len(text) <= 500:
            return text
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: description summary failed ({e}); using script excerpt.")
    sentences = re.split(r"(?<=[.!?])\s+", script_text.strip())
    return " ".join(sentences[:2])[:300]


def build_description(title: str, script_text: str, topic: str,
                       channel_tags: list, is_short: bool, config: dict = None) -> str:
    """Short summary + subscribe CTA + a handful of hashtags.

    Hashtags: topic-specific ones first (YouTube shows only the first
    three above the title), then two broad channel ones. Capped at 5
    (+ #Shorts for Shorts); stuffing a dozen tags dilutes them.
    """
    summary = _summarize_for_description(title, script_text, is_short)

    # Use hashtag_agent if enabled
    trending_hashtags = []
    if config and config.get("use_hashtag_agent", False):
        from src.agents.hashtag_agent import fetch_trending_hashtags
        trending_hashtags = fetch_trending_hashtags(topic)

    extracted = _extract_hashtags_from_title(title, max_tags=3)
    # If we have trending hashtags, combine them with extracted/broad ones
    combined_tags = list(dict.fromkeys(trending_hashtags + extracted))

    broad = ["SpaceFacts", "Astronomy"]
    tag_words = list(dict.fromkeys(
        t.replace(" ", "") for t in combined_tags + broad
    ))[:5]
    hashtags = " ".join("#" + t for t in tag_words)
    if is_short:
        hashtags += " #Shorts"

    cta = "Subscribe for more mind-bending space and science facts! \U0001F680"

    return f"{title.strip()}\n\n{summary}\n\n{cta}\n\n{hashtags}"


def run(channel_id: str, is_short: bool, privacy_status: str = "public",
        dry_run: bool = False, language_override: str = None) -> None:
    config = load_channel_config(channel_id)
    is_kids_channel = config.get("visual_style") == "puppet_animation"
    print(f"=== Running {config['display_name']} | {'SHORT' if is_short else 'LONG-FORM'} | Lang: {language_override or 'auto'} ===")

    # Pre-flight auth check -- fails fast (~1 second) if the YouTube
    # token is dead, instead of discovering it after a full 10-17 minute
    # generation cycle (script, TTS, footage, assembly) only to fail at
    # the very last step. Skipped in dry runs since nothing gets
    # uploaded anyway.
    if not dry_run:
        from src.upload_youtube import verify_token_valid
        token_path = ROOT / "tokens" / f"{channel_id}_token.pickle"
        client_secret_path = ROOT / "client_secret.json"
        verify_token_valid(
            str(token_path),
            str(client_secret_path) if client_secret_path.exists() else None,
        )
        print("Pre-flight auth check passed.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. Script (+ Quality Gate)
        # If the gate rejects a topic after all repairs, the premise itself
        # is usually the problem (a misleading hook can't be repaired away).
        # Reject that topic, move to the next ranked one, and try again
        # instead of failing the whole run.
        MAX_TOPIC_ATTEMPTS = 3
        rejected_topics: set = set()
        forced_topic = None
        if not is_kids_channel and is_short:
            # For a Short, first check whether today's long-form video
            # already happened and hasn't been "recapped" yet -- if so,
            # reuse that topic instead of picking a fresh unrelated one.
            forced_topic = get_recap_topic_for_short(channel_id)

        for topic_attempt in range(1, MAX_TOPIC_ATTEMPTS + 1):
            if is_kids_channel:
                result = generate_kids_script(channel_id, is_short=is_short)
            else:
                result = generate_script(
                    channel_id, is_short=is_short, forced_topic=forced_topic,
                    dry_run=dry_run, exclude_topics=rejected_topics,
                    language_override=language_override,
                )
                if not is_short and not dry_run:
                    # Record today's long-form topic so the next Short run
                    # can pick it up for a recap.
                    save_todays_longform_topic(channel_id, result["topic"])
            topic, script_text = result["topic"], result["script"]
            language, voice = result["language"], result["voice"]

            # Quality Gate (not for the kids puppet pipeline yet; it has
            # different language/content requirements).
            if is_kids_channel:
                break

            target_words = int(
                (config["short_length_seconds"] if is_short
                else config["video_length_seconds"]) * 2.2
            )

            script_text, quality_review = validate_and_repair(
                topic=topic,
                script=script_text,
                config=config,
                target_words=target_words,
            )
            result["script"] = script_text

            print(f"Quality score: {quality_review.get('score', 0):.1f}/10")

            if quality_review.get("approved"):
                break

            # A gate that couldn't run (API outage) says nothing about the
            # topic -- don't blacklist it, just stop.
            # Gemini failing mid-check says nothing about the topic -- unless
            # the gate had ALREADY rejected it twice before the outage hit
            # (a repair loop that can't fix the premise). Then the topic is
            # clearly the problem, so move on instead of stopping the run.
            if (quality_review.get("infra_failure")
                    and quality_review.get("real_rejections", 0) < 2):
                raise RuntimeError(
                    "Quality Gate could not run (Gemini unavailable); "
                    "not rejecting the topic. Re-run later."
                )

            print(f"Topic rejected by Quality Gate: {topic!r} "
                  f"(topic attempt {topic_attempt}/{MAX_TOPIC_ATTEMPTS})")
            rejected_topics.add(topic)
            forced_topic = None  # a recap topic can't be retried; pick fresh
            mark_topic_used(channel_id, topic)
            mark_topic_rejected(channel_id, topic)
        else:
            raise RuntimeError(
                f"Quality Gate rejected {MAX_TOPIC_ATTEMPTS} topics in a row "
                f"({', '.join(sorted(rejected_topics))})."
            )

        print(f"Topic: {topic}")
        if is_kids_channel:
            print(f"Content type: {result['content_type']} | Mascot: {result['mascot_name']}")
        print(f"Language: {language} | Voice: {voice}")
        print(f"Script ({len(script_text.split())} words):\n{script_text}\n")

        # 1b. Editorial pass (hook/SEO/thumbnail/retention agents) — opt-in
        # via config["use_editorial_agents"]. Runs after the script has
        # already passed quality_gate's science fact-check. Every field
        # falls back to the original value if its agent call fails.
        editorial_title = result["title"]
        extra_tags, extra_hashtags, thumbnail_override_text = [], [], None
        if not is_kids_channel:
            from src.editorial_pass import run_editorial_pass
            edit_result = run_editorial_pass(topic, script_text, editorial_title, config)
            script_text = edit_result["script"]
            editorial_title = edit_result["title"]
            extra_tags = edit_result["extra_tags"]
            extra_hashtags = edit_result["extra_hashtags"]
            thumbnail_override_text = edit_result["thumbnail_text"]

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
            clips_dir = tmp / "clips"
            orientation = "portrait" if is_short else "landscape"
            clip_durations = None
            try:
                # Per-sentence visuals: one clip matched to each beat of
                # the narration, cut to that beat's timing.
                from src.visual_plan import build_beats, plan_queries
                from src.fetch_stock import fetch_clips_for_beats
                beats = build_beats(
                    str(timing_path),
                    min_seconds=2.0 if is_short else 5.0,
                    max_seconds=4.5 if is_short else 9.0,
                )
                beats = plan_queries(beats, topic, config.get("niche", "science and space facts"))
                clip_paths, clip_durations = fetch_clips_for_beats(
                    beats, str(clips_dir), orientation=orientation, topic=topic,
                    used_ids_path=ROOT / "state" / f"{channel_id}_used_clips.json",
                )
            except Exception as e:
                print(f"WARNING: per-beat footage failed ({e}); "
                      f"falling back to topic-level footage.")
                clip_paths = fetch_clips_for_topic(
                    topic, str(clips_dir), count=3 if is_short else 8,
                    orientation=orientation,
                )
            print(f"Downloaded {len(clip_paths)} clips")
            assemble_video(clip_paths, str(audio_path), str(timing_path),
                            str(output_path), portrait=is_short,
                            clip_durations=clip_durations)
        print(f"Assembled video: {output_path} ({output_path.stat().st_size / 1e6:.1f} MB)")

        if dry_run:
            # Copy to a visible location instead of uploading, for local testing
            dest = ROOT / "output" / f"{channel_id}_{'short' if is_short else 'long'}.mp4"
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(output_path.read_bytes())
            print(f"[DRY RUN] Saved to {dest} instead of uploading")

            # Export to multi-platform folders (TikTok, IG Reels, YouTube Shorts)
            try:
                from src.export_platforms import export_to_all_platforms
                export_to_all_platforms(str(dest))
            except Exception as e:
                print(f"WARNING: Multi-platform export failed: {e}")
            return

        # 5. Thumbnail — best-effort; a failure here never blocks the upload
        thumb_path = tmp / "thumbnail.jpg"
        thumbnail_result = generate_thumbnail(
            str(output_path), editorial_title, str(thumb_path),
            language=language, portrait=is_short,
            override_text=thumbnail_override_text,
        )

        # 5b. QA gate — catches silent assembly bugs (truncated audio,
        # dead-silent voiceover) before they ever reach an upload. A fatal
        # issue here raises, which the scheduler already treats like any
        # other pipeline failure -- the slot isn't marked done, so it
        # retries next tick instead of publishing a broken video.
        from src.qa_check import validate_video
        ok, fatal_issues, qa_warnings = validate_video(
            str(output_path), str(audio_path),
            str(thumb_path) if thumbnail_result else None,
        )
        for w in qa_warnings:
            print(f"QA WARNING: {w}")
        if not ok:
            issues_text = "; ".join(fatal_issues)
            raise RuntimeError(f"QA check failed, blocking upload: {issues_text}")
        print("QA check passed.")

        # 6. Upload
        title = make_title(editorial_title, is_short)
        description = build_description(
            editorial_title, script_text, topic,
            config["tags"] + extra_tags, is_short, config=config,
        )

        # Tier 1 Revenue: Contextual Affiliate Injection
        from src.agents.revenue_agent import inject_affiliate_cta
        description, affiliate_cat = inject_affiliate_cta(script_text, description)

        # Tier 2 Revenue: Archive to Cosmos Vault
        if not is_short: # Focus vaulting on long-form / high-value assets
            from src.agents.revenue_agent import archive_master_asset
            archive_master_asset(channel_id, topic, script_text, {"affiliate_cat": affiliate_cat})

        # Widen the YouTube tag field too (separate from in-description
        # hashtags) -- channel tags plus topic-specific keywords pulled
        # from the title, for better search matching per video.
        video_tags = list(dict.fromkeys(
            config["tags"] + extra_tags + extra_hashtags
            + _extract_hashtags_from_title(editorial_title, max_tags=6)
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

        # Log to the video registry -- this is the real-history data the
        # ceo_agent (channel strategy agent) reads later. Best-effort:
        # a logging failure should never undo a successful upload.
        try:
            from src.agents.video_registry import record_video
            record_video(channel_id, {
                "video_id": video_id,
                "topic": topic,
                "title": title,
                "is_short": is_short,
                "language": language,
            })
        except Exception as e:
            print(f"WARNING: video_registry logging failed ({e}) -- upload itself succeeded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("channel_id")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--privacy", default="public",
                         choices=["public", "unlisted", "private"])
    parser.add_argument("--dry-run", action="store_true",
                         help="Build the video but don't upload — saves locally instead")
    parser.add_argument("--language", default=None,
                         help="Language code override (e.g. en, hi)")
    args = parser.parse_args()

    try:
        run(args.channel_id, args.short, args.privacy, args.dry_run, language_override=args.language)
    except Exception:
        print("PIPELINE FAILED:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
