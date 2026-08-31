"""
generate_mascot_assets.py

Generates the mascot character art used by the 2D cutout-animation
pipeline (see generate_kids_video.py) for kids channels like Jungle Ke
Dost.

Each mascot gets a small set of reusable pose frames:
idle, talk, wave, clap, jump, dance_left, dance_right.

Images are generated once and permanently cached under:

    assets/mascots/<mascot>/

Future video runs reuse the cached PNGs and do not need to generate
the artwork again.

If Gemini image generation is unavailable, placeholder frames are
created so the pipeline does not crash.
"""

import os
import shutil
from pathlib import Path

try:
    from google import genai as genai_client
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ============================================================
# CONFIGURATION
# ============================================================

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"

ROOT = Path(__file__).resolve().parent.parent

CACHE_DIR = ROOT / "assets" / "mascots"

SCENE_WIDTH = 1080
SCENE_HEIGHT = 1920


# ============================================================
# POSES
# ============================================================

POSES = [
    "idle",
    "talk",
    "wave",
    "clap",
    "jump",
    "dance_left",
    "dance_right",
]


POSE_MODIFIERS = {

    "idle":
        "standing upright, arms relaxed at sides, "
        "mouth closed, calm warm smile, at rest",

    "talk":
        "standing upright, mouth open wide mid-word "
        "as if speaking enthusiastically, one hand "
        "slightly raised as if mid-sentence",

    "wave":
        "waving one hand up high and cheerfully at "
        "the viewer, big open happy smile",

    "clap":
        "clapping both hands together in front of "
        "itself, delighted expression, mouth open "
        "in a happy laugh",

    "jump":
        "mid-air jump with both feet off the ground, "
        "arms raised up joyfully, big open-mouthed "
        "excited smile",

    "dance_left":
        "playful dance pose leaning and stepping to "
        "the left, one arm raised up, joyful "
        "open-mouthed expression",

    "dance_right":
        "playful dance pose leaning and stepping to "
        "the right, one arm raised up, joyful "
        "open-mouthed expression",
}


# ============================================================
# COMMON ART STYLE
# ============================================================

STYLE_SUFFIX = (
    "Flat vector illustration style, thick clean black "
    "outlines, bright saturated friendly colors, big "
    "expressive eyes, simple rounded shapes, polished "
    "professional children's animation character design. "
    "Character is centered, front-facing, full-body, "
    "filling most of the frame. "
    "Background: a soft, simple, slightly blurred "
    "cartoon jungle with green leaves and soft sunlight "
    "that does not distract from the character. "
    "Keep the character design extremely consistent. "
    "No text, no watermark, no logo anywhere in the image."
)


# ============================================================
# MASCOT DESIGNS
# ============================================================

MASCOT_BASE_DESCRIPTIONS = {

    "elephant": (
        "A cheerful cartoon baby elephant character "
        "named Gullu Hathi, light blue-grey skin, "
        "big round friendly eyes, large rounded ears, "
        "small cute trunk, wearing a simple red bandana "
        "around the neck, {pose}. "
        + STYLE_SUFFIX
    ),

    "bear": (
        "A cheerful cartoon baby bear character "
        "named Bhalu Bhaiya, warm brown fur, "
        "big round friendly eyes, small rounded ears, "
        "cute rounded body, wearing a simple yellow "
        "scarf, {pose}. "
        + STYLE_SUFFIX
    ),

    "bunny": (
        "A cheerful cartoon baby bunny character "
        "named Chintu Khargosh, soft white and grey fur, "
        "long upright ears, big round friendly eyes, "
        "small cute nose, wearing a simple green bowtie, "
        "{pose}. "
        + STYLE_SUFFIX
    ),
}


# ============================================================
# IMAGE EXTRACTION
# ============================================================

def _extract_image_bytes(response) -> bytes | None:
    """
    Extract the first inline image from a Gemini response.

    Returns:
        bytes | None
    """

    try:

        candidates = getattr(response, "candidates", None)

        if not candidates:
            return None

        content = getattr(candidates[0], "content", None)

        if not content:
            return None

        parts = getattr(content, "parts", None)

        if not parts:
            return None

        for part in parts:

            inline_data = getattr(part, "inline_data", None)

            if inline_data is None:
                continue

            data = getattr(inline_data, "data", None)

            if data:
                return data

    except Exception as e:

        print(
            f"WARNING: could not extract image from "
            f"Gemini response: {e}"
        )

    return None


# ============================================================
# GEMINI IMAGE CALL
# ============================================================

def _call_image_model(client, prompt: str):
    """
    Calls Gemini's image generation model.

    Tries explicit IMAGE + TEXT response modalities first.
    If the installed google-genai SDK rejects that configuration,
    retries without explicit modalities.
    """

    try:

        from google.genai import types

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"]
        )

        return client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
            config=config,
        )

    except Exception as first_error:

        print(
            "WARNING: Gemini image request with explicit "
            f"response modalities failed: {first_error}"
        )

        print(
            "Retrying Gemini image generation without "
            "explicit response modalities..."
        )

        return client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
        )


# ============================================================
# GENERATE ONE POSE
# ============================================================

def _generate_pose(
    client,
    mascot: str,
    pose: str
) -> bytes:

    if mascot not in MASCOT_BASE_DESCRIPTIONS:

        raise ValueError(
            f"Unknown mascot: {mascot}"
        )

    if pose not in POSE_MODIFIERS:

        raise ValueError(
            f"Unknown pose: {pose}"
        )

    prompt = MASCOT_BASE_DESCRIPTIONS[mascot].format(
        pose=POSE_MODIFIERS[pose]
    )

    print(
        f"Generating Gemini artwork: "
        f"mascot={mascot}, pose={pose}"
    )

    response = _call_image_model(
        client,
        prompt
    )

    image_bytes = _extract_image_bytes(
        response
    )

    if not image_bytes:

        raise RuntimeError(
            f"Gemini returned no image for pose "
            f"'{pose}'."
        )

    return image_bytes


# ============================================================
# PLACEHOLDER FRAME
# ============================================================

def _write_placeholder(
    mascot: str,
    pose: str,
    path: Path
) -> None:

    """
    Creates a simple placeholder PNG.

    This guarantees that the video pipeline can continue
    even when Gemini artwork generation is unavailable.
    """

    from PIL import Image, ImageDraw, ImageFont

    colors = {
        "elephant": (150, 190, 220),
        "bear": (150, 110, 80),
        "bunny": (230, 230, 230),
    }

    color = colors.get(
        mascot,
        (180, 180, 180)
    )

    img = Image.new(
        "RGB",
        (
            SCENE_WIDTH,
            SCENE_HEIGHT
        ),
        color
    )

    draw = ImageDraw.Draw(img)

    text = f"{mascot}\n{pose}"

    try:

        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc",
            60
        )

    except Exception:

        font = None

    bbox = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        align="center"
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (
        SCENE_WIDTH - text_width
    ) // 2

    y = (
        SCENE_HEIGHT - text_height
    ) // 2

    draw.multiline_text(
        (x, y),
        text,
        fill=(0, 0, 0),
        font=font,
        align="center",
    )

    img.save(path)


# ============================================================
# CACHE VALIDATION
# ============================================================

def _cached_image_is_valid(
    path: Path
) -> bool:

    """
    Checks that a cached PNG actually exists and is readable.

    This prevents a corrupted/empty image from permanently
    breaking future runs.
    """

    if not path.exists():

        return False

    if path.stat().st_size < 100:

        return False

    try:

        from PIL import Image

        with Image.open(path) as img:

            img.verify()

        return True

    except Exception:

        return False


# ============================================================
# GENERATE MASCOT ASSETS
# ============================================================

def generate_mascot_assets(
    mascot: str,
    out_dir: str
) -> dict:

    """
    Generate or load every pose for a mascot.

    Returns:

        {
            "idle": ".../idle.png",
            "talk": ".../talk.png",
            ...
        }

    Artwork is permanently cached under:

        assets/mascots/<mascot>/

    The generated/cached files are copied into out_dir for
    the current video run.
    """

    if mascot not in MASCOT_BASE_DESCRIPTIONS:

        raise ValueError(
            f"Unknown mascot '{mascot}'. "
            f"Available mascots: "
            f"{', '.join(MASCOT_BASE_DESCRIPTIONS)}"
        )

    out_dir = Path(out_dir)

    out_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    cache_dir = CACHE_DIR / mascot

    cache_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Create Gemini client only if available
    # --------------------------------------------------------

    client = None

    if (
        GEMINI_AVAILABLE
        and os.environ.get("GEMINI_API_KEY")
    ):

        try:

            client = genai_client.Client(
                api_key=os.environ[
                    "GEMINI_API_KEY"
                ]
            )

        except Exception as e:

            print(
                "WARNING: Could not initialize "
                f"Gemini client: {e}"
            )

            client = None

    else:

        print(
            "WARNING: Gemini image generation "
            "is unavailable. Cached images will "
            "be used, otherwise placeholders "
            "will be created."
        )

    # --------------------------------------------------------
    # Process every pose
    # --------------------------------------------------------

    result = {}

    for pose in POSES:

        cached_path = (
            cache_dir / f"{pose}.png"
        )

        # ----------------------------------------------------
        # Existing valid cache
        # ----------------------------------------------------

        if _cached_image_is_valid(
            cached_path
        ):

            print(
                f"Using cached mascot art: "
                f"{mascot}/{pose}.png"
            )

        # ----------------------------------------------------
        # Missing or corrupted cache
        # ----------------------------------------------------

        else:

            if cached_path.exists():

                print(
                    f"Cached image for "
                    f"{mascot}/{pose} is invalid. "
                    f"Regenerating..."
                )

            else:

                print(
                    f"No cached '{pose}' art for "
                    f"mascot '{mascot}' -- "
                    f"generating once now."
                )

            # ------------------------------------------------
            # Try Gemini
            # ------------------------------------------------

            generated = False

            if client is not None:

                try:

                    image_bytes = _generate_pose(
                        client,
                        mascot,
                        pose
                    )

                    cached_path.write_bytes(
                        image_bytes
                    )

                    # Validate generated image
                    if not _cached_image_is_valid(
                        cached_path
                    ):

                        raise RuntimeError(
                            "Generated image was "
                            "written but failed "
                            "validation."
                        )

                    print(
                        f"Saved mascot art: "
                        f"{cached_path}"
                    )

                    generated = True

                except Exception as e:

                    print(
                        f"WARNING: '{pose}' art "
                        f"generation failed: {e}"
                    )

            # ------------------------------------------------
            # Placeholder fallback
            # ------------------------------------------------

            if not generated:

                print(
                    f"Creating placeholder for "
                    f"{mascot}/{pose}"
                )

                _write_placeholder(
                    mascot,
                    pose,
                    cached_path
                )

        # ----------------------------------------------------
        # Copy cached image into current run directory
        # ----------------------------------------------------

        out_path = (
            out_dir / f"{pose}.png"
        )

        shutil.copyfile(
            cached_path,
            out_path
        )

        result[pose] = str(
            out_path
        )

    return result


# ============================================================
# COMMAND LINE INTERFACE
# ============================================================

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Generate/cache mascot pose artwork "
            "for the kids video pipeline."
        )
    )

    parser.add_argument(
        "mascot",
        choices=list(
            MASCOT_BASE_DESCRIPTIONS
        ),
        help="Mascot to generate"
    )

    parser.add_argument(
        "out_dir",
        help="Temporary/output directory "
             "for this video run"
    )

    args = parser.parse_args()

    paths = generate_mascot_assets(
        args.mascot,
        args.out_dir
    )

    print(
        "\nMascot assets ready:"
    )

    for pose, path in paths.items():

        print(
            f"  {pose}: {path}"
        )