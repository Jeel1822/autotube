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
import sys
import tempfile
import traceback
from pathlib import Path

import yaml

from generate_script import generate_script
from tts import synthesize_speech
from fetch_stock import fetch_clips_for_topic
from assemble_video import assemble_video
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


def run(channel_id: str, is_short: bool, privacy_status: str = "public",
        dry_run: bool = False) -> None:
    config = load_channel_config(channel_id)
    print(f"=== Running {config['display_name']} | {'SHORT' if is_short else 'LONG-FORM'} ===")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. Script
        result = generate_script(channel_id, is_short=is_short)
        topic, script_text = result["topic"], result["script"]
        language, voice = result["language"], result["voice"]
        print(f"Topic: {topic}")
        print(f"Language: {language} | Voice: {voice}")
        print(f"Script ({len(script_text.split())} words):\n{script_text}\n")

        # 2. TTS
        audio_path = tmp / "audio.mp3"
        timing_path = tmp / "timing.json"
        synthesize_speech(script_text, voice, str(audio_path), str(timing_path))
        print(f"Audio generated: {audio_path}")

        # 3. Stock footage — search query stays in English (topic is always
        # the internal English working title, regardless of script language)
        # since stock footage libraries index best in English anyway.
        clip_count = 3 if is_short else 8
        clips_dir = tmp / "clips"
        clip_paths = fetch_clips_for_topic(
            topic, str(clips_dir), count=clip_count,
            orientation="portrait" if is_short else "landscape",
        )
        print(f"Downloaded {len(clip_paths)} clips")

        # 4. Assemble
        output_path = tmp / "final.mp4"
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

        # 5. Upload
        title = make_title(result["title"], is_short)
        description = f"{script_text[:400]}...\n\n{' '.join('#' + t.replace(' ', '') for t in config['tags'][:5])}"
        token_path = ROOT / "tokens" / f"{channel_id}_token.pickle"

        video_id = upload_video(
            str(output_path), title, description, config["tags"],
            config["category_id"], str(token_path),
            privacy_status=privacy_status, is_short=is_short,
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
