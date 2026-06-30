"""Multi-provider model adapters for the ClawBench pilot (Anthropic / OpenAI / Google).

Each adapter is a callable(condition, prompt) -> raw_text, matching gradient_runner's contract.
Transient/rate-limit errors are retried with exponential backoff and, if still failing, raised as
RateLimitExhausted so the runner records them distinctly (NEVER as a model format failure; that
miscount produced the V1 Mistral artifact). Clients are injectable for offline testing.

No side effects at import time; real clients are built lazily in make_adapters().
"""
from __future__ import annotations

import re
import time

SYSTEM = ("You are a precise clinical-genomics assistant. Output ONLY a single valid JSON object "
          "that answers the request. No prose, no explanation, no markdown code fences.")

MAX_TOKENS = 4096


class RateLimitExhausted(Exception):
    """Raised after retries are exhausted on a transient/rate-limit error."""


_TRANSIENT = re.compile(r"(?i)(429|rate.?limit|overloaded|timeout|timed out|connection|"
                        r"502|503|504|500|internal server|service unavailable|temporarily)")


def _is_transient(exc: Exception) -> bool:
    return bool(_TRANSIENT.search(f"{type(exc).__name__}: {exc}"))


def _with_retries(fn, retries: int = 6, base: float = 2.0, sleep=time.sleep):
    last = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_transient(exc) and attempt < retries - 1:
                sleep(base * (2 ** attempt))
                continue
            if _is_transient(exc):
                raise RateLimitExhausted(f"{type(exc).__name__}: {exc}") from exc
            raise
    raise RateLimitExhausted(str(last))


def load_env_keys(env_path) -> dict:
    keys = {}
    wanted = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}
    for line in open(env_path):
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m and m.group(1) in wanted:
            keys[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return keys


# ---- per-provider adapters (client injectable) ---------------------------------
def anthropic_adapter(model, client, max_tokens=MAX_TOKENS, retries=6, sleep=time.sleep):
    def call(condition, prompt):
        def _do():
            r = client.messages.create(
                model=model, max_tokens=max_tokens, system=SYSTEM,
                messages=[{"role": "user", "content": prompt}])
            return r.content[0].text
        return _with_retries(_do, retries=retries, sleep=sleep)
    return call


def openai_adapter(model, client, max_tokens=MAX_TOKENS, retries=6, sleep=time.sleep):
    def call(condition, prompt):
        def _do():
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}])
            return r.choices[0].message.content
        return _with_retries(_do, retries=retries, sleep=sleep)
    return call


def google_adapter(model, client, retries=6, sleep=time.sleep):
    def call(condition, prompt):
        def _do():
            r = client.generate_content(f"{SYSTEM}\n\n{prompt}")
            return r.text
        return _with_retries(_do, retries=retries, sleep=sleep)
    return call


def ollama_adapter(model, client, retries=6, sleep=time.sleep):
    """Open-weight arm: a model served locally by Ollama. Free, offline, frozen weights (reproducible).
    `client.chat(model, system, prompt) -> str` is injectable so this is testable without a server.
    Same retry contract as the API adapters; a dead/loading local server is treated as transient."""
    def call(condition, prompt):
        def _do():
            return client.chat(model=model, system=SYSTEM, prompt=prompt)
        return _with_retries(_do, retries=retries, sleep=sleep)
    return call


class OllamaClient:
    """Thin stdlib (urllib) client for a local Ollama server. No new dependency, no API key."""

    def __init__(self, host="http://localhost:11434", timeout=600):
        self.host = host.rstrip("/")
        self.timeout = timeout

    def chat(self, *, model, system, prompt) -> str:
        import json
        import urllib.request
        body = json.dumps({
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "options": {"temperature": 0},
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["message"]["content"]


# ---- real client construction (lazy) -------------------------------------------
def make_adapters(env_path, models: dict) -> dict:
    """Build live adapters. `models` maps a run label -> (provider, model_id).
    Returns label -> callable(condition, prompt)."""
    keys = load_env_keys(env_path)
    out = {}
    for label, (provider, model_id) in models.items():
        if provider == "anthropic":
            import anthropic
            out[label] = anthropic_adapter(model_id, anthropic.Anthropic(api_key=keys["ANTHROPIC_API_KEY"]))
        elif provider == "openai":
            import openai
            out[label] = openai_adapter(model_id, openai.OpenAI(api_key=keys["OPENAI_API_KEY"]))
        elif provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=keys["GOOGLE_API_KEY"])
            out[label] = google_adapter(model_id, genai.GenerativeModel(model_id))
        elif provider == "ollama":
            out[label] = ollama_adapter(model_id, OllamaClient())  # local, no key
        else:
            raise ValueError(f"unknown provider {provider!r}")
    return out
