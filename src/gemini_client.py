"""
Centralized Gemini client for AutoTube.
"""

import os

from google import genai
from google.genai import types


GEMINI_MODEL = "gemini-3.5-flash-lite"


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    return genai.Client(api_key=api_key)


def generate(
    prompt: str,
    max_output_tokens: int | None = None,
    model: str = GEMINI_MODEL,
) -> str:
    """Generate text using Gemini chat."""

    client = get_client()

    chat = client.chats.create(model=model)

    config = None

    if max_output_tokens:
        config = types.GenerateContentConfig(
            max_output_tokens=max_output_tokens
        )

    if config:
        response = chat.send_message(
            prompt,
            config=config,
        )
    else:
        response = chat.send_message(prompt)

    text = getattr(response, "text", None)

    if not text:
        raise RuntimeError("Gemini returned an empty response.")

    return text.strip()


def generate_response(
    prompt: str,
    max_output_tokens: int | None = None,
    model: str = GEMINI_MODEL,
):
    """Generate text and return the full Gemini response."""

    client = get_client()

    chat = client.chats.create(model=model)

    config = None

    if max_output_tokens:
        config = types.GenerateContentConfig(
            max_output_tokens=max_output_tokens
        )

    if config:
        return chat.send_message(
            prompt,
            config=config,
        )

    return chat.send_message(prompt)
