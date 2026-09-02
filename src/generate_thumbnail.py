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

# High-CTR color schemes, rotated per video for visual variety across a
# channel's thumbnail grid (same reason big channels don't reuse one
# template every time -- a uniform look becomes easy to scroll past).
# ASS colors are &HAABBGGRR (alpha, then BGR -- reverse of normal RGB hex).
# BorderStyle 3 = opaque box behind the text using BackColour, which is
# what gives the bold "banner" look instead of a faint outline.
THUMBNAIL_SCHEMES = [
    {"text": "&H0000FFFF", "bg": "&H000022E6"},  # yellow text / red-orange banner
    {"text": "&H00FFFFFF", "bg": "&H00C81414"},  # white text / deep red banner
    {"text": "&H0000FFFF", "bg": "&H00A02020"},  # yellow text / dark blue-red banner
    {"text": "&H00FFFFFF", "bg": "&H0000A5FF"},  # white text / orange banner
]


def _get_video_duration(video_path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _shorten_for_thumbnail(title: str, language: str, max_words: int = 4) -> str:
    """Thumbnails need a short, punchy phrase, not the full SEO title --
    fewer words than the title (4 vs the old 5) so the banner text is big
    enough to read at feed/mobile thumbnail size. Uppercasing for impact
    only makes sense for Latin script -- Devanagari has no case, so leave
    Hindi text as-is."""
    words = title.strip().split()
    short = " ".join(words[:max_words])
    return short.upper() if language == "en" else short


def _escape_ass_text(text: str) -> str:
    """Escape characters with special meaning inside an .ass Dialogue text field."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _write_thumbnail_ass(text: str, ass_path: Path, width: int, height: int,
                          font_size: int, scheme: dict) -> None:
    escaped = _escape_ass_text(text)
    margin_v = int(height * 0.12)
    # BorderStyle 3 + a thick Outline draws an opaque colored banner behind
    # the text (using BackColour) rather than a thin outline around it --
    # this is the bold "banner text" look that reads at a glance in a
    # scrolling feed, vs. the old faint black-box style.
    content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{font_size},{scheme['text']},&H00000000,{scheme['bg']},1,3,14,0,2,50,50,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{escaped}
"""
    ass_path.write_text(content, encoding="utf-8")


def _frame_detail_score(frame_path: Path) -> float:
    """Scores a frame by pixel-value standard deviation (grayscale) --
    a flat, low-detail frame (a fade, a transition, a mostly-solid-color
    moment) has low variance; a frame with real visible content has high
    variance. Used to pick the best of several candidate thumbnail frames
    instead of trusting one fixed timestamp, which can land on a bad
    moment depending on what stock clip happened to be playing there."""
    from PIL import Image, ImageStat
    with Image.open(frame_path) as img:
        stat = ImageStat.Stat(img.convert("L"))
        return stat.stddev[0]


def _pick_best_frame_time(video_path: str, duration: float, tmp_dir: Path,
                           candidates: int = 5) -> float:
    """Extracts several cheap low-res candidate frames spread across the
    middle 65% of the video and returns the timestamp of whichever has
    the most visual detail."""
    start, end = duration * 0.15, duration * 0.80
    if end <= start:
        return max(duration * 0.35, 0.5)

    step = (end - start) / max(candidates - 1, 1)
    best_time, best_score = start, -1.0

    for i in range(candidates):
        t = start + step * i
        candidate_path = tmp_dir / f"candidate_{i}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(t), "-i", video_path,
                "-vframes", "1", "-vf", "scale=320:-1",
                "-q:v", "5", str(candidate_path),
            ], check=True, capture_output=True, timeout=15)
            score = _frame_detail_score(candidate_path)
            if score > best_score:
                best_score, best_time = score, t
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue

    return best_time


def generate_thumbnail(
    video_path: str,
    title: str,
    output_path: str,
    language: str = "en",
    portrait: bool = False,
    override_text: str = None,
) -> str | None:
    """Extracts a frame and overlays a short bold title. Returns
    output_path on success, or None if generation failed for any reason
    (caller should treat this as non-fatal and upload without a custom
    thumbnail).

    override_text: if provided (e.g. from thumbnail_agent's chosen
    concept), used verbatim instead of auto-shortening the title. Still
    subject to the same length/case handling as the auto-derived text
    isn't applied here -- pass pre-formatted text.

    Note on Shorts: YouTube's Shorts feed largely ignores the thumbnails.set
    API and picks its own cover frame, so this is best-effort for shorts --
    it may still show on the watch page / subscriptions feed, but don't
    expect it to change what appears in the Shorts shelf itself.
    """
    try:
        import random
        import tempfile

        duration = _get_video_duration(video_path)

        width, height = (1080, 1920) if portrait else (1280, 720)
        # Larger than before (was 90/64) -- bold banner text needs to read
        # clearly even at small mobile thumbnail sizes.
        font_size = 110 if portrait else 78

        short_text = override_text or _shorten_for_thumbnail(title, language)
        scheme = random.choice(THUMBNAIL_SCHEMES)

        ass_path = Path(output_path).with_suffix(".ass")
        _write_thumbnail_ass(short_text, ass_path, width, height, font_size, scheme)
        escaped_ass_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            grab_time = _pick_best_frame_time(video_path, duration, Path(tmp))

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
