"""
export_platforms.py
Multi-Platform Export Support
Takes a finished rendered video (Short) and prepares/exports it for TikTok,
Instagram Reels, and YouTube Shorts simultaneously.
"""
import shutil
from pathlib import Path

def export_to_all_platforms(video_path: str, output_dir: str = "output/multi_platform") -> dict:
    """
    Copies the rendered video into platform-specific export folders so you
    can manually or automatically upload the exact same high-retention short
    to TikTok, Instagram Reels, and YouTube Shorts.
    """
    src_path = Path(video_path)
    if not src_path.exists():
        raise FileNotFoundError(f"Source video not found: {video_path}")

    out = Path(output_dir)
    platforms = ["tiktok", "instagram_reels", "youtube_shorts"]
    results = {}

    for platform in platforms:
        p_dir = out / platform
        p_dir.mkdir(parents=True, exist_ok=True)
        dest_path = p_dir / src_path.name
        shutil.copy2(src_path, dest_path)
        results[platform] = str(dest_path)
        print(f"Exported for {platform}: {dest_path}")

    return results

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export video to multi-platform folders")
    parser.add_argument("video_path", help="Path to the rendered video file")
    parser.add_argument("--out", default="output/multi_platform", help="Output base directory")
    args = parser.parse_args()
    export_to_all_platforms(args.video_path, args.out)
