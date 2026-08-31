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


def _ass_timestamp(seconds: float) -> str:
    """Format seconds as an .ass timestamp: H:MM:SS.CC"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _escape_ass_text(text: str) -> str:
    """Escape characters with special meaning inside an .ass Dialogue text field."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _write_ass_subtitles(chunks: list, ass_path: Path, width: int, height: int,
                          font_size: int, portrait: bool) -> None:
    """Writes all caption chunks into a single .ass file (one subtitle track,
    burned in later with a single `subtitles=` filter instead of N chained
    drawtext filters -- this is what keeps ffmpeg fast on long videos)."""
    margin_v = int(font_size * 3.2)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,FreeSans,{font_size},&H00FFFFFF,&H00000000,&H99000000,1,3,2,0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in chunks:
        escaped = _escape_ass_text(text)
        lines.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},"
            f"Default,,0,0,0,,{escaped}\n"
        )
    ass_path.write_text("".join(lines), encoding="utf-8")


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
                # -stream_loop -1 repeats the input indefinitely; -t then
                # caps the output at the requested duration. Without the
                # loop, a source clip shorter than per_clip_duration (very
                # common with free stock footage -- many clips are only
                # 5-10s) would just end early, making the stitched
                # background video shorter than the audio. The final
                # assembly step uses -shortest, which then silently
                # truncates the AUDIO to match that short video --
                # cutting the script off mid-sentence with no error or
                # warning anywhere in the pipeline.
                "ffmpeg", "-y", "-stream_loop", "-1", "-i", clip,
                "-t", str(per_clip_duration),
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

        # 3. Build caption chunks (word-timed groups of ~4 words) and write
        # them all into a single .ass subtitle file. Burning captions in via
        # one `subtitles=` filter (needs libass, which ships with ffmpeg's
        # standard build) is dramatically faster than chaining one drawtext
        # filter per caption -- ffmpeg was re-evaluating a 250+ filter graph
        # on every frame before, which is what caused the multi-minute hangs
        # on longer videos.
        chunks = _build_caption_chunks(timing_path)
        font_size = 56 if portrait else 44

        vf_chain = None
        if chunks:
            ass_path = tmp / "captions.ass"
            _write_ass_subtitles(chunks, ass_path, width, height, font_size, portrait)
            # ffmpeg filter args need colons/backslashes escaped when the path
            # is passed as a filter option value.
            escaped_ass_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
            vf_chain = f"subtitles='{escaped_ass_path}'"

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
