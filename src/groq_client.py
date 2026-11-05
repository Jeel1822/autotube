"""
Groq API client for AutoTube, providing a reliable, ultra-fast alternative to Gemini.
"""
import os
from openai import OpenAI

def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")
    return OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")

def generate(prompt: str, model: str = "llama-3.3-70b-versatile", json_mode: bool = False) -> str:
    client = get_groq_client()
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content.strip()
