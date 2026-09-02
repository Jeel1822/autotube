"""
qa_check.py
Pre-upload validation gate. Runs automated checks on an assembled video
right after assembly and before it ever reaches upload_video(). Built in
response to a real, silent bug: audio getting truncated mid-sentence
because the background video ended up shorter than the voiceover (fixed
at the root cause in assemble_video.py's -stream_loop change, but this
gate stays as a safety net in case any other path reintroduces a similar
mismatch in the future).

validate_video() returns (ok, issues) rather than raising directly, so the
caller decides what's fatal vs. a warning:
- A duration mismatch is objective and precise -- treated as fatal.
- A low-detail thumbnail is a heuristic judgment call -- treated as a
  warning only, since a legitimately dark/simple scene could still score
  low without actually being broken.
"""
import subprocess
from pathlib import Path


def _get_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _check_duration_matches_audio(video_path: str, audio_path: str,
                                   tolerance_seconds: float = 1.5) -> str | None:
    video_dur = _get_duration(video_path)
    audio_dur = _get_duration(audio_path)
    diff = abs(video_dur - audio_dur)
    if diff > tolerance_seconds:
        return (
            f"Video duration ({video_dur:.1f}s) doesn't match audio "
            f"duration ({audio_dur:.1f}s) -- off by {diff:.1f}s. The "
            f"video was very likely truncated or padded during assembly, "
            f"cutting off part of the script."
        )
    return None


def _check_audio_not_silent(audio_path: str, max_silence_ratio: float = 0.5) -> str | None:
    out = subprocess.run(
        ["ffmpeg", "-i", audio_path, "-af", "silencedetect=noise=-35dB:d=1",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    log = out.stderr
    silence_durations = []
    for line in log.splitlines():
        if "silence_duration:" in line:
            try:
                silence_durations.append(float(line.split("silence_duration:")[1].strip()))
            except (ValueError, IndexError):
                continue
    total_silence = sum(silence_durations)
    try:
        total_duration = _get_duration(audio_path)
    except (subprocess.CalledProcessError, ValueError):
        return None
    if total_duration > 0 and (total_silence / total_duration) > max_silence_ratio:
        return (
            f"Audio is more than {int(max_silence_ratio * 100)}% silence "
            f"({total_silence:.1f}s of {total_duration:.1f}s) -- TTS may "
            f"have failed partway through."
        )
    return None


def _check_thumbnail_detail(thumbnail_path: str, min_score: float = 12.0) -> str | None:
    try:
        from src.generate_thumbnail import _frame_detail_score
        score = _frame_detail_score(Path(thumbnail_path))
    except Exception:
        return None
    if score < min_score:
        return (
            f"Thumbnail looks unusually flat/low-detail (score {score:.1f}, "
            f"expected > {min_score}) -- may have landed on a blank or "
            f"transition frame. Worth a quick manual look."
        )
    return None


def validate_video(video_path: str, audio_path: str,
                    thumbnail_path: str = None) -> tuple[bool, list, list]:
    """Runs all checks. Returns (ok, fatal_issues, warnings). ok is False
    only if a fatal issue was found -- callers should block the upload
    in that case."""
    fatal_issues = []
    warnings = []

    duration_issue = _check_duration_matches_audio(video_path, audio_path)
    if duration_issue:
        fatal_issues.append(duration_issue)

    silence_issue = _check_audio_not_silent(audio_path)
    if silence_issue:
        fatal_issues.append(silence_issue)

    if thumbnail_path and Path(thumbnail_path).exists():
        thumb_issue = _check_thumbnail_detail(thumbnail_path)
        if thumb_issue:
            warnings.append(thumb_issue)

    return (len(fatal_issues) == 0, fatal_issues, warnings)
