"""
generate_mascot_assets.py
Generates the mascot character art used by the 2D cutout-animation
pipeline (see generate_kids_video.py) for kids channels like Jungle Ke
Dost. Unlike a single static image, each mascot gets a small SET of pose
frames -- the video cuts between them on phrase boundaries, giving the
mascot real body movement (waving, clapping, jumping, dancing) instead of
just a flapping mouth. This is the same technique real small/mid-size 2D
"cutout style" kids channels use: discrete pose swaps, not smooth skeletal
animation -- achievable for free, at daily-upload volume.

IMPORTANT — caching: art is generated ONCE per mascot and cached
permanently under assets/mascots/<mascot>/ in the repo root, NOT
regenerated on every run. Commit that folder to git after your first local
run so CI never needs to call an image model at all.

Pose set (see POSES below) is intentionally small and reused across every
video for a mascot -- more poses = more one-time generation cost, but
these are still one-time-ever costs, not per-video.

Each pose is generated as an INDEPENDENT image (not edited from a shared
base like the old scene/talk pair) -- because generate_kids_video.py now
concatenates discrete pose clips rather than alpha-overlaying two frames,
pixel-for-pixel alignment between poses is no longer required, which
means each pose can just be its own straightforward text-to-image call.

MODEL NOTE: gemini-2.5-flash-image is used because it's the cheapest
Gemini image model when billing is on (roughly $0.04/image), and this
runs a handful of times per mascot, ever. If GEMINI_API_KEY has no
billing enabled, every call will fail and this falls back to placeholder
frames -- see the README section on generating art for free by hand
through the Gemini web app instead (same cached file layout, no code
changes needed, you just place the PNGs yourself).
"""
import os
import shutil
from pathlib import Path

try:
    from google import genai as genai_client
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "assets" / "mascots"

SCENE_WIDTH, SCENE_HEIGHT = 1080, 1920  # portrait canvas

# The pose set every mascot gets. generate_kids_video.py cuts between
# these on phrase boundaries: "idle" fills silence/gaps, "talk" is the
# default while narration is playing, and the rest are sprinkled in
# periodically during speech for visual variety/rhythm.
POSES = ["idle", "talk", "wave", "clap", "jump", "dance_left", "dance_right"]

POSE_MODIFIERS = {
    "idle": "standing upright, arms relaxed at sides, mouth closed, calm warm smile, at rest",
    "talk": "standing upright, mouth open wide mid-word as if speaking enthusiastically, one hand slightly raised as if mid-sentence",
    "wave": "waving one hand up high and cheerfully at the viewer, big open happy smile",
    "clap": "clapping both hands together in front of itself, delighted expression, mouth open in a happy laugh",
    "jump": "mid-air jump with both feet off the ground, arms raised up joyfully, big open-mouthed excited smile",
    "dance_left": "playful dance pose leaning and stepping to the left, one arm raised up, joyful open-mouthed expression",
    "dance_right": "playful dance pose leaning and stepping to the right, one arm raised up, joyful open-mouthed expression",
}

# Kept intentionally consistent in style/palette across all mascots and
# poses so they read as the same show despite each pose being an
# independent generation.
STYLE_SUFFIX = (
    "Flat vector illustration style, thick clean black outlines, bright "
    "saturated friendly colors, big expressive eyes, simple rounded "
    "shapes -- similar in spirit to popular children's YouTube shows. "
    "Character is centered, front-facing, full-body, filling most of the "
    "frame. Background: a soft, simple, slightly blurred cartoon jungle "
    "(green leaves, soft sunlight) that doesn't distract from the "
    "character. No text, no watermark, no logo anywhere in the image."
)

MASCOT_BASE_DESCRIPTIONS = {
    "elephant": (
        "A cheerful cartoon baby elephant character named Gullu Hathi, "
        "light blue-grey skin, big round friendly eyes, wearing a simple "
        "red bandana around the neck, {pose}. " + STYLE_SUFFIX
    ),
    "bear": (
        "A cheerful cartoon baby bear character named Bhalu Bhaiya, warm "
        "brown fur, big round friendly eyes, wearing a simple yellow "
        "scarf, {pose}. " + STYLE_SUFFIX
    ),
    "bunny": (
        "A cheerful cartoon baby bunny character named Chintu Khargosh, "
        "soft white and grey fur, long upright ears, big round friendly "
        "eyes, wearing a simple green bowtie, {pose}. " + STYLE_SUFFIX
    ),
}


def _extract_image_bytes(response) -> bytes | None:
    """Pulls the first inline image out of a generate_content response.
    Returns None if the response contains no image part."""
    try:
        for part in response.candidates[0].content.parts:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                return data
    except Exception:
        pass
    return None


def _call_image_model(client, prompt: str):
    """Same defensive config/fallback pattern used elsewhere in this repo
    (generate_script.py's token-budget retries) -- some google-genai
    versions want response_modalities set explicitly for image output,
    others infer it; try the explicit form first, fall back if this SDK
    version rejects it."""
    try:
        from google.genai import types
        config = types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
        return client.models.generate_content(
            model=GEMINI_IMAGE_MODEL, contents=prompt, config=config,
        )
    except Exception as e:
        print(f"WARNING: could not apply response_modalities config ({e}); "
              f"calling without it.")
        return client.models.generate_content(model=GEMINI_IMAGE_MODEL, contents=prompt)


def _generate_pose(client, mascot: str, pose: str) -> bytes:
    prompt = MASCOT_BASE_DESCRIPTIONS[mascot].format(pose=POSE_MODIFIERS[pose])
    response = _call_image_model(client, prompt)
    image_bytes = _extract_image_bytes(response)
    if not image_bytes:
        raise RuntimeError(f"Gemini returned no image for pose '{pose}'.")
    return image_bytes


def _write_placeholder(mascot: str, pose: str, path: Path) -> None:
    """Last-resort fallback: a plain colored card labeled with the
    mascot+pose name, so generate_kids_video.py always has a full pose
    set to work with even if art generation is completely unavailable."""
    from PIL import Image, ImageDraw

    colors = {"elephant": (150, 190, 220), "bear": (150, 110, 80), "bunny": (230, 230, 230)}
    color = colors.get(mascot, (180, 180, 180))
    img = Image.new("RGB", (SCENE_WIDTH, SCENE_HEIGHT), color)
    draw = ImageDraw.Draw(img)
    draw.text((SCENE_WIDTH // 2 - 60, SCENE_HEIGHT // 2), f"{mascot}\n({pose})", fill=(0, 0, 0))
    img.save(path)


def generate_mascot_assets(mascot: str, out_dir: str) -> dict:
    """Returns {pose_name: path} for every pose in POSES -- each copied
    into out_dir (a per-run temp directory) but sourced from the
    permanent cache in assets/mascots/<mascot>/ whenever possible."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = CACHE_DIR / mascot
    cache_dir.mkdir(parents=True, exist_ok=True)

    client = None
    if GEMINI_AVAILABLE and os.environ.get("GEMINI_API_KEY"):
        client = genai_client.Client(api_key=os.environ["GEMINI_API_KEY"])

    result = {}
    for pose in POSES:
        cached_path = cache_dir / f"{pose}.png"
        if not cached_path.exists():
            print(f"No cached '{pose}' art for mascot '{mascot}' -- "
                  f"generating once now (future runs reuse this for free).")
            try:
                if client is None:
                    raise RuntimeError("GEMINI_API_KEY not set or google-genai not installed.")
                image_bytes = _generate_pose(client, mascot, pose)
                cached_path.write_bytes(image_bytes)
            except Exception as e:
                print(f"WARNING: '{pose}' art generation failed ({e}); "
                      f"using a placeholder frame instead.")
                _write_placeholder(mascot, pose, cached_path)

        out_path = out_dir / f"{pose}.png"
        shutil.copyfile(cached_path, out_path)
        result[pose] = str(out_path)

    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mascot", choices=list(MASCOT_BASE_DESCRIPTIONS))
    parser.add_argument("out_dir")
    args = parser.parse_args()

    paths = generate_mascot_assets(args.mascot, args.out_dir)
    print(f"Wrote: {paths}")
