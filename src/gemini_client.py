"""
Centralized Gemini client for AutoTube.
"""

import os
import random
import time

from google import genai
from google.genai import types


GEMINI_MODEL = "gemini-3.5-flash-lite"


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    return genai.Client(api_key=api_key)


# Fallback models tried if the primary stays overloaded (comma-separated env override).
FALLBACK_MODELS = [
    m.strip()
    for m in os.environ.get("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.8-flash,gemini-3.5-flash-lite").split(",")
    if m.strip()
]

_TRANSIENT = ("503", "unavailable", "429", "resource_exhausted", "500", "502",
              "504", "deadline_exceeded", "timeout", "temporarily", "overloaded",
              "high demand")


def _is_transient(exc: Exception) -> bool:
    blob = " ".join(str(x).lower() for x in (
        exc, getattr(exc, "code", ""), getattr(exc, "status_code", ""),
        getattr(exc, "status", "")))
    return any(m in blob for m in _TRANSIENT)


# model -> monotonic time until which it is considered down (circuit breaker),
# so one overloaded model doesn't cost ~40s of retries on every single call.
_DOWN_UNTIL: dict = {}
_COOLDOWN_SECONDS = 300


_GONE = ("404", "not_found", "no longer available", "not found", "is not supported")


def _is_model_gone(exc: Exception) -> bool:
    blob = " ".join(str(x).lower() for x in (
        exc, getattr(exc, "code", ""), getattr(exc, "status_code", ""),
        getattr(exc, "status", "")))
    return any(m in blob for m in _GONE)


def send_with_retry(prompt, model: str = GEMINI_MODEL, config=None,
                    attempts_per_model: int = 2):
    """Send a prompt, retrying transient errors (503/429/...) briefly per
    model, then falling back to FALLBACK_MODELS. A model that exhausts its
    retries is skipped for 5 minutes. Non-transient errors raise immediately."""
    client = get_client()
    all_models = [model] + [m for m in FALLBACK_MODELS if m != model]
    now = time.monotonic()
    models = [m for m in all_models if _DOWN_UNTIL.get(m, 0) <= now] or all_models
    last_exc = None

    for mi, mdl in enumerate(models):
        for attempt in range(attempts_per_model):
            try:
                chat = client.chats.create(model=mdl)
                if config is not None:
                    return chat.send_message(prompt, config=config)
                return chat.send_message(prompt)
            except Exception as exc:
                last_exc = exc
                if _is_model_gone(exc) and mi < len(models) - 1:
                    # Retired / unavailable model: don't retry, move to next one.
                    print(f"Gemini model {mdl} is not available "
                          f"({str(exc)[:80]}); trying {models[mi + 1]}.", flush=True)
                    _DOWN_UNTIL[mdl] = time.monotonic() + 3600
                    break
                if not _is_transient(exc):
                    raise
                if attempt == attempts_per_model - 1:
                    break
                delay = 3 * 2 ** attempt + random.uniform(0, 1)
                print(f"Gemini transient error on {mdl}: {str(exc)[:80]}. "
                      f"Retrying in {delay:.0f}s...", flush=True)
                time.sleep(delay)
        if _DOWN_UNTIL.get(mdl, 0) <= time.monotonic():
            _DOWN_UNTIL[mdl] = time.monotonic() + _COOLDOWN_SECONDS
        if mi < len(models) - 1 and not _is_model_gone(last_exc):
            print(f"Gemini {mdl} unavailable; switching to {models[mi + 1]} "
                  f"(skipping {mdl} for {_COOLDOWN_SECONDS // 60} min).", flush=True)

    raise last_exc


def generate(
    prompt: str,
    max_output_tokens: int | None = None,
    model: str = GEMINI_MODEL,
    json_mode: bool = False,
) -> str:
    """Generate text using Gemini chat.

    json_mode=True asks Gemini for syntactically valid JSON output
    (response_mime_type), which prevents corrupted keys like s"afe_framing".
    """

    config = None

    if max_output_tokens or json_mode:
        kwargs = {}
        if max_output_tokens:
            kwargs["max_output_tokens"] = max_output_tokens
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**kwargs)

    response = send_with_retry(prompt, model=model, config=config)

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
