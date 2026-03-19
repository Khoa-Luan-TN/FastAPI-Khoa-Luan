# app/services/ollama_client.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    env_path = Path(__file__).resolve().parents[1] / "core" / "config.env"
    load_dotenv(env_path)
    return (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")


_TIMEOUT = 300  # seconds — increased for 32b model


# ── Core call ─────────────────────────────────────────────────────────────────

def generate_text(
    prompt: str,
    model: str = "qwen2.5:14b",
    system: str | None = None,
    response_format: str | dict | None = "json",
) -> str:
    """Call local Ollama in non-streaming mode and return plain text.

    Args:
        prompt: User prompt.
        model: Ollama model name.
        system: Optional system prompt.
        response_format: Passed as Ollama `format` field ("json", a JSON schema dict, or None to omit).

    Raises RuntimeError on connection failure, timeout, non-200, or empty response.
    """
    url = f"{_base_url()}/api/generate"

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": 256,
            "seed": 42,
        },
    }
    if system is not None:
        payload["system"] = system
    if response_format is not None:
        payload["format"] = response_format

    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Ollama not reachable at {_base_url()}: {e}") from e
    except requests.exceptions.Timeout:
        raise RuntimeError(f"Ollama request timed out after {_TIMEOUT}s")

    if resp.status_code != 200:
        raise RuntimeError(
            f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    text = (data.get("response") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty response text")

    print(f"[ollama_client] ✓ model={model} chars={len(text)}")
    return text


# ── Observability ─────────────────────────────────────────────────────────────

def get_ollama_status() -> dict:
    """Return Ollama server reachability and available models."""
    base = _base_url()
    try:
        resp = requests.get(f"{base}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = [m.get("name") for m in resp.json().get("models", [])]
            return {"reachable": True, "base_url": base, "models": models}
        return {"reachable": False, "base_url": base, "error": f"HTTP {resp.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"reachable": False, "base_url": base, "error": "Connection refused"}
    except Exception as e:
        return {"reachable": False, "base_url": base, "error": str(e)}
