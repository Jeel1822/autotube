"""
generate_thumbnail.py
Builds a custom YouTube thumbnail: grabs a frame partway through the
assembled video and burns in a short, bold text overlay for contrast/CTR.

IMPORTANT: text is burned in via a single-line .ass subtitle + the
`subtitles=` filter (libass), NOT ffmpeg's `drawtext` filter. drawtext does
not do proper Indic script shaping -- Hindi text through drawtext comes out
with missing vowel signs and no word spacing (e.g. "इंसान बार-बार" becomes
"इंसन बर-बर"). libass shapes it correctly because it goes through
HarfBuzz. This mirrors the same fix already applied to caption burn-in in
assemble_video.py -- same root cause, same fix, different call site.

Falls back to returning None on any failure so a thumbnail hiccup never
blocks the upload itself -- YouTube will just use an auto-generated frame
instead of a custom one.
"""
import re
import subprocess
from pathlib import Path

# FreeSans (Ubuntu package: fonts-freefont-ttf) has verified Devanagari
# coverage with correct shaping via libass/HarfBuzz -- see module docstring.
# Used for both languages so English and Hindi thumbnails look consistent.
FONT_NAME = "FreeSans"


def _get_video_duration(video_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _shorten_for_thumbnail(title: str, language: str, max_words: int = 5) -> str:
    """Thumbnails need a short, punchy phrase, not the full SEO title.
    Uppercasing for impact only makes sense for Latin script -- Devanagari
    has no case, so leave Hindi text as-is."""
    words = title.strip().split()
    short = " ".join(words[:max_words])
    return short.upper() if language == "en" else short


def _escape_ass_text(text: str) -> str:
    """Escape characters with special meaning inside an .ass Dialogue text field."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _write_thumbnail_ass(text: str, ass_path: Path, width: int, height: int,
                          font_size: int) -> None:
    escaped = _escape_ass_text(text)
    margin_v = int(height * 0.12)
    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{font_size},&H00FFFFFF,&H00000000,&H99000000,1,3,3,0,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{escaped}
"""
    ass_path.write_text(content, encoding="utf-8")


def generate_thumbnail(
    video_path: str,
    title: str,
    output_path: str,
    language: str = "en",
    portrait: bool = False,
) -> str | None:
    """Extracts a frame and overlays a short bold title. Returns
    output_path on success, or None if generation failed for any reason
    (caller should treat this as non-fatal and upload without a custom
    thumbnail).

    Note on Shorts: YouTube's Shorts feed largely ignores the thumbnails.set
    API and picks its own cover frame, so this is best-effort for shorts --
    it may still show on the watch page / subscriptions feed, but don't
    expect it to change what appears in the Shorts shelf itself.
    """
    try:
        duration = _get_video_duration(video_path)
        # Grab a frame ~35% into the video -- usually past any fade-in and
        # well before a fade-out, without needing to know the video's
        # internal structure.
        grab_time = max(duration * 0.35, 0.5)

        width, height = (1080, 1920) if portrait else (1280, 720)
        font_size = 90 if portrait else 64

        short_text = _shorten_for_thumbnail(title, language)

        ass_path = Path(output_path).with_suffix(".ass")
        _write_thumbnail_ass(short_text, ass_path, width, height, font_size)
        escaped_ass_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(grab_time), "-i", video_path,
            "-vframes", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height},subtitles='{escaped_ass_path}'",
            "-q:v", "2", output_path,
        ], check=True, capture_output=True)

        ass_path.unlink(missing_ok=True)
        return output_path
    except Exception as e:
        print(f"WARNING: thumbnail generation failed ({e}); "
              f"upload will proceed without a custom thumbnail.")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("video_path")
    parser.add_argument("title")
    parser.add_argument("output_path")
    parser.add_argument("--language", default="en")
    parser.add_argument("--portrait", action="store_true")
    args = parser.parse_args()

    result = generate_thumbnail(args.video_path, args.title, args.output_path,
                                 args.language, args.portrait)
    print(f"Wrote {result}" if result else "Thumbnail generation failed")
