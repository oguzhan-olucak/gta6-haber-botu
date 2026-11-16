"""Çoklu sağlayıcı yedekleme: Gemini → Groq → OpenRouter. Tanımsız secret atlanır, yalnızca geçici
hatalarda sıradakine geçilir, OpenRouter'da yalnızca ücretsiz modeller, anahtarlar sızmaz, çıktı aynı
Pydantic/halüsinasyon denetiminden geçer."""
from __future__ import annotations

import json

import pytest

from bot import ErrorClass
from bot.config import redact
from bot.gemini import RESPONSE_JSON_SCHEMA, GeminiError
from bot.llm import (
    GROQ_DEFAULT_MODEL,
    GROQ_URL,
    OPENROUTER_URL,
    FallbackGenerator,
    OpenAICompatGenerator,
    build_generator,
    openrouter_model_is_free,
)
from tests.conftest import FakeResponse

GROQ_KEY = "gsk_" + "D" * 40
OR_KEY = "sk-or-v1-" + "e" * 40
GOOD = json.dumps({"title_tr": "x"})


class _Gen:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def generate(self, s, p, schema):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_undefined_providers_are_skipped_silently():
    g = build_generator(_Gen(GOOD), {})
    assert [n for n, _ in g.providers] == ["gemini"]
    g = build_generator(_Gen(GOOD), {"GROQ_API_KEY": GROQ_KEY, "OPENROUTER_API_KEY": "  "})
    assert [n for n, _ in g.providers] == ["gemini", "groq"]
    assert g.providers[1][1].model == GROQ_DEFAULT_MODEL


def test_openrouter_only_free_models():
    assert openrouter_model_is_free("openrouter/free") and openrouter_model_is_free("x/y:free")
    assert not openrouter_model_is_free("deepseek/deepseek-chat")
    g = build_generator(_Gen(GOOD), {"OPENROUTER_API_KEY": OR_KEY, "OPENROUTER_MODEL": "anthropic/paid-model"})
    assert [n for n, _ in g.providers] == ["gemini"]          # ücretli model → sağlayıcı devre dışı
    g = build_generator(_Gen(GOOD), {"OPENROUTER_API_KEY": OR_KEY})
    assert g.providers[1][1].model == "openrouter/free"


@pytest.mark.parametrize("cls", [ErrorClass.NETWORK_TRANSIENT, ErrorClass.RATE_LIMIT_QUOTA, ErrorClass.AUTH_PERMISSION])
def test_falls_through_on_transient_errors(cls):
    gem, groq, orr = _Gen(GeminiError(cls, "x")), _Gen(GeminiError(ErrorClass.NETWORK_TRANSIENT, "y")), _Gen(GOOD)
    g = FallbackGenerator([("gemini", gem), ("groq", groq), ("openrouter", orr)])
    assert g.generate("s", "p", {}) == GOOD and g.last_provider == "openrouter"
    assert g.attempts[-1] == "openrouter:ok" and gem.calls == groq.calls == orr.calls == 1


def test_first_success_wins_and_non_transient_errors_stop():
    gem, groq = _Gen(GOOD), _Gen(GOOD)
    g = FallbackGenerator([("gemini", gem), ("groq", groq)])
    assert g.generate("s", "p", {}) == GOOD and g.last_provider == "gemini" and groq.calls == 0
    bad = FallbackGenerator([("gemini", _Gen(GeminiError(ErrorClass.GEMINI_SCHEMA_ERROR, "z"))), ("groq", groq)])
    with pytest.raises(GeminiError):
        bad.generate("s", "p", {})
    assert groq.calls == 0


def test_all_fail_raises_gemini_error_for_cooldown_logic():
    first = GeminiError(ErrorClass.RATE_LIMIT_QUOTA, "gemini 429")
    g = FallbackGenerator([("gemini", _Gen(first)), ("groq", _Gen(GeminiError(ErrorClass.NETWORK_TRANSIENT, "g")))])
    with pytest.raises(GeminiError) as ei:
        g.generate("s", "p", {})
    assert ei.value is first


class _S:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.responses.pop(0)


def _chat(content):
    return FakeResponse(200, json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def test_openai_compat_request_shape_and_schema():
    s = _S(_chat("```json\n" + GOOD + "\n```"))
    gen = OpenAICompatGenerator("groq", GROQ_URL, GROQ_KEY, GROQ_DEFAULT_MODEL, session=s)
    assert gen.generate("SİSTEM", "<untrusted_source_data>x</untrusted_source_data>", RESPONSE_JSON_SCHEMA) == GOOD
    url, kw = s.calls[0]
    assert url == GROQ_URL and kw["headers"]["Authorization"] == f"Bearer {GROQ_KEY}" and "key=" not in url
    body = kw["json"]
    assert body["model"] == GROQ_DEFAULT_MODEL and body["messages"][0] == {"role": "system", "content": "SİSTEM"}
    assert "untrusted_source_data" in body["messages"][1]["content"]
    assert body["response_format"]["json_schema"]["schema"] == RESPONSE_JSON_SCHEMA


def test_openai_compat_retries_with_json_object_when_schema_unsupported():
    s = _S(FakeResponse(400, b'{"error":{"type":"invalid_request_error","code":"json_schema_unsupported"}}'), _chat(GOOD))
    gen = OpenAICompatGenerator("openrouter", OPENROUTER_URL, OR_KEY, "openrouter/free", session=s)
    assert gen.generate("S", "P", RESPONSE_JSON_SCHEMA) == GOOD
    second = s.calls[1][1]["json"]
    assert second["response_format"] == {"type": "json_object"} and "title_tr" in second["messages"][0]["content"]


@pytest.mark.parametrize("code,cls", [(429, ErrorClass.RATE_LIMIT_QUOTA), (503, ErrorClass.NETWORK_TRANSIENT),
                                      (401, ErrorClass.AUTH_PERMISSION), (404, ErrorClass.AUTH_PERMISSION)])
def test_openai_compat_error_classes_without_key_leak(code, cls):
    body = json.dumps({"error": {"type": "x", "message": f"bad key {GROQ_KEY}"}}).encode()
    gen = OpenAICompatGenerator("groq", GROQ_URL, GROQ_KEY, GROQ_DEFAULT_MODEL, session=_S(FakeResponse(code, body)))
    with pytest.raises(GeminiError) as ei:
        gen.generate("s", "p", {})
    assert ei.value.error_class == cls and GROQ_KEY not in str(ei.value)
    assert GROQ_KEY not in redact(f"log {GROQ_KEY} {OR_KEY}") and OR_KEY not in redact(f"{OR_KEY}")


def test_bot_records_provider_per_post(tmp_path):
    """Tam bot çalışması: Gemini 503 → Groq özeti → kayıtta ve özette sağlayıcı 'groq'."""
    from tests.test_publisher import FakeGenerator, FakeTelegram, go, items, make_env

    class Busy:
        def generate(self, s, p, schema):
            raise GeminiError(ErrorClass.NETWORK_TRANSIENT, "Gemini HTTP 503 UNAVAILABLE")

    cfg, data, session = make_env(tmp_path, items(1))
    gen = FallbackGenerator([("gemini", Busy()), ("groq", FakeGenerator())])
    code, summary = go(cfg, data, session, FakeTelegram(), gen)
    assert summary["published"] >= 1
    assert set(summary["llm_providers"].values()) == {"groq"}
    hist = json.loads((data / "history.json").read_text("utf-8"))
    assert {p.get("llm_provider") for p in hist["posts"] if p.get("publish_status") == "PUBLISHED"} == {"groq"}
