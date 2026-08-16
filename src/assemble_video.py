"""
assemble_video.py
Stitches stock clips into a background reel matching the audio length,
overlays the voiceover, and burns in synced captions (from the word-timing
JSON produced by tts.py) using ffmpeg. No paid tools, no GPU required.
"""
import json
import subprocess
import tempfile
from pathlib import Path

LANDSCAPE = (1920, 1080)
PORTRAIT = (1080, 1920)


def _get_audio_duration(audio_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _escape_drawtext(text: str) -> str:
    """Escape characters that are special to ffmpeg's drawtext filter syntax."""
    text = text.replace("\\", "\\\\\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\u2019")   # straight quote -> curly, avoids escaping headaches
    text = text.replace("%", "\\%")
    text = text.replace(",", "\\,")
    text = text.replace("[", "\\[").replace("]", "\\]")
    return text


def _build_caption_chunks(timing_path: str, words_per_caption: int = 4) -> list:
    """Groups word-level timings into short caption chunks: [(start, end, text), ...]"""
    words = json.loads(Path(timing_path).read_text())
    chunks = []
    for i in range(0, len(words), words_per_caption):
        chunk = words[i:i + words_per_caption]
        start = chunk[0]["offset_seconds"]
        end = chunk[-1]["offset_seconds"] + chunk[-1]["duration_seconds"]
        text = " ".join(w["text"] for w in chunk)
        chunks.append((start, end, text))
    return chunks


def assemble_video(
    clip_paths: list,
    audio_path: str,
    timing_path: str,
    output_path: str,
    portrait: bool = False,
) -> None:
    width, height = PORTRAIT if portrait else LANDSCAPE
    audio_duration = _get_audio_duration(audio_path)
    per_clip_duration = max(audio_duration / max(len(clip_paths), 1), 1.0)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. Normalize each clip to target resolution/duration, silent
        normalized = []
        for i, clip in enumerate(clip_paths):
            norm_path = tmp / f"norm_{i}.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-i", clip, "-t", str(per_clip_duration),
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                       f"crop={width}:{height},fps=30",
                "-an", str(norm_path),
            ], check=True, capture_output=True)
            normalized.append(norm_path)

        # 2. Concatenate normalized clips
        concat_list = tmp / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in normalized))
        background = tmp / "background.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", str(background),
        ], check=True, capture_output=True)

        # 3. Build caption chunks (word-timed groups of ~4 words)
        chunks = _build_caption_chunks(timing_path)

        # 4. Merge background + voiceover audio + burned captions via drawtext.
        # drawtext ships with every ffmpeg build (unlike the subtitles filter,
        # which needs libass) so this works with no extra dependencies.
        font_size = 56 if portrait else 44
        y_pos = f"h-{int(font_size * 3.2)}"  # near bottom, matches old subtitle position

        if chunks:
            drawtext_filters = []
            for start, end, text in chunks:
                escaped = _escape_drawtext(text)
                drawtext_filters.append(
                    f"drawtext=text='{escaped}':fontsize={font_size}:fontcolor=white:"
                    f"box=1:boxcolor=black@0.6:boxborderw=10:"
                    f"x=(w-text_w)/2:y={y_pos}:"
                    f"enable='between(t,{start:.3f},{end:.3f})'"
                )
            vf_chain = ",".join(drawtext_filters)
        else:
            vf_chain = None

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-i", str(background), "-i", audio_path]
        if vf_chain:
            cmd += ["-vf", vf_chain]
        cmd += [
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    parser.add_argument("timing_path")
    parser.add_argument("output_path")
    parser.add_argument("clips", nargs="+")
    parser.add_argument("--portrait", action="store_true")
    args = parser.parse_args()

    assemble_video(args.clips, args.audio_path, args.timing_path,
                    args.output_path, args.portrait)
    print(f"Wrote {args.output_path}")
