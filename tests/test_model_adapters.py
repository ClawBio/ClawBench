"""TDD for the multi-provider model adapter (Anthropic / OpenAI / Google).

Critical (V1 lesson): rate-limit / transient transport errors must be retried with backoff and,
if still failing, raised as RateLimitExhausted so the runner records them DISTINCTLY rather than
miscounting them as model format failures. No network in tests: clients are injected fakes.
"""
from __future__ import annotations

import pytest

import model_adapters as MA


def test_load_env_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-oo\nANTHROPIC_API_KEY=sk-aa\nGOOGLE_API_KEY=g-gg\nOTHER=x\n")
    keys = MA.load_env_keys(env)
    assert keys["OPENAI_API_KEY"] == "sk-oo"
    assert keys["ANTHROPIC_API_KEY"] == "sk-aa"
    assert keys["GOOGLE_API_KEY"] == "g-gg"
    assert "OTHER" not in keys


def test_retries_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limit exceeded")
        return "ok"

    out = MA._with_retries(flaky, retries=5, sleep=lambda *_: None)
    assert out == "ok" and calls["n"] == 3


def test_retries_exhausted_raises_ratelimit():
    def always_429():
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(MA.RateLimitExhausted):
        MA._with_retries(always_429, retries=3, sleep=lambda *_: None)


def test_non_transient_error_propagates():
    def bad():
        raise ValueError("invalid request: bad model id")

    with pytest.raises(ValueError):
        MA._with_retries(bad, retries=3, sleep=lambda *_: None)


def test_is_transient_classification():
    assert MA._is_transient(RuntimeError("429 too many requests"))
    assert MA._is_transient(RuntimeError("503 service unavailable"))
    assert MA._is_transient(RuntimeError("overloaded_error"))
    assert MA._is_transient(RuntimeError("connection timeout"))
    assert not MA._is_transient(ValueError("bad request: unknown field"))


# ---- adapters with injected fake clients ---------------------------------------
class _FakeAnthropic:
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        class R:
            content = [type("B", (), {"text": '{"classification": "Pathogenic"}'})()]
        return R()


class _FakeOpenAI:
    def __init__(self):
        self.chat = self
        self.completions = self

    def create(self, **kw):
        class R:
            choices = [type("C", (), {"message": type("M", (), {"content": '{"classification": "Benign"}'})()})()]
        return R()


class _FakeGoogle:
    def generate_content(self, prompt, **kw):
        return type("R", (), {"text": '{"classification": "Likely Pathogenic"}'})()


def test_anthropic_adapter():
    a = MA.anthropic_adapter("claude-sonnet-4-20250514", client=_FakeAnthropic(), sleep=lambda *_: None)
    assert a("free_prompted", "prompt") == '{"classification": "Pathogenic"}'


def test_openai_adapter():
    a = MA.openai_adapter("gpt-5.2", client=_FakeOpenAI(), sleep=lambda *_: None)
    assert a("free_prompted", "prompt") == '{"classification": "Benign"}'


def test_google_adapter():
    a = MA.google_adapter("gemini-2.5-pro", client=_FakeGoogle(), sleep=lambda *_: None)
    assert a("free_prompted", "prompt") == '{"classification": "Likely Pathogenic"}'


# ---- ollama (local open-weight) adapter ----------------------------------------
class _FakeOllama:
    def __init__(self):
        self.calls = []

    def chat(self, *, model, system, prompt):
        self.calls.append((model, system, prompt))
        return '{"classification": "Benign"}'


class _FlakyOllama:
    """Fails transiently once (server still loading the model), then succeeds."""
    def __init__(self):
        self.n = 0

    def chat(self, **kw):
        self.n += 1
        if self.n == 1:
            raise ConnectionError("connection refused: model loading")
        return '{"classification": "Pathogenic"}'


def test_ollama_adapter_returns_text():
    fake = _FakeOllama()
    a = MA.ollama_adapter("qwen2.5:72b-instruct-q4_K_M", client=fake, sleep=lambda *_: None)
    assert a("skill_execution", "prompt") == '{"classification": "Benign"}'
    # passes through the model id and the shared SYSTEM prompt
    assert fake.calls[0][0] == "qwen2.5:72b-instruct-q4_K_M"
    assert fake.calls[0][1] == MA.SYSTEM


def test_ollama_adapter_retries_transient_then_succeeds():
    a = MA.ollama_adapter("qwen3.6:35b-mlx", client=_FlakyOllama(), sleep=lambda *_: None)
    assert a("skill_execution", "prompt") == '{"classification": "Pathogenic"}'


def test_ollama_adapter_exhausts_to_ratelimit():
    class _Dead:
        def chat(self, **kw):
            raise TimeoutError("timed out")
    a = MA.ollama_adapter("m", client=_Dead(), retries=2, sleep=lambda *_: None)
    try:
        a("skill_execution", "p")
        assert False, "expected RateLimitExhausted"
    except MA.RateLimitExhausted:
        pass
