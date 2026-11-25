"""
Groq API client for AutoTube, a fast fallback when Gemini is overloaded/rate-limited.

llama-3.3-70b-versatile was retired by Groq on 2026-08-16 (your logs show 404 for it),
so the default is now openai/gpt-oss-120b, Groq's listed replacement. Override with
GROQ_MODEL (a single id) or GROQ_MODELS (comma-separated, tried in order). A model that
returns 404 is skipped for the rest of the process, so the call isn't retried each time.
"""
import os

from openai import OpenAI

DEFAULT_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]
REQUEST_TIMEOUT_S = int(os.environ.get("GROQ_TIMEOUT_S", "60"))

_GONE = set()  # model ids that returned 404 this process


def _candidates(first: str = None) -> list:
    """Requested model(s) first, then the defaults; retired ids removed."""
    raw = os.environ.get("GROQ_MODELS") or os.environ.get("GROQ_MODEL") or ""
    custom = [m.strip() for m in raw.split(",") if m.strip()]
    ordered = ([first] if first else []) + custom + DEFAULT_MODELS
    seen, out = set(), []
    for m in ordered:
        if m not in seen and m not in _GONE:
            seen.add(m)
            out.append(m)
    return out


def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1",
                  timeout=REQUEST_TIMEOUT_S, max_retries=1)


def generate(prompt: str, model: str = None, json_mode: bool = False) -> str:
    client = get_groq_client()
    last_exc = None
    for mdl in _candidates(model):
        kwargs = {
            "model": mdl,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = client.chat.completions.create(**kwargs)
            text = (response.choices[0].message.content or "").strip()
            if text:
                return text
            last_exc = RuntimeError(f"Groq model {mdl} returned an empty response.")
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "404" in msg or "does not exist" in msg or "decommission" in msg:
                print(f"Groq model {mdl} is not available; trying the next one.", flush=True)
                _GONE.add(mdl)
                continue
            raise
    raise last_exc or RuntimeError("No Groq model available.")
