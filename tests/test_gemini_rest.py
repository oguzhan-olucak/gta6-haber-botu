"""Gemini REST istemcisi: AQ. auth key'leri yalnızca x-goog-api-key başlığıyla gider; hata tanısı
anahtar sızdırmaz; eski istemcide konmuş soğuma kilidi bir kez temizlenir."""
from __future__ import annotations

import json

import pytest

from bot import ErrorClass
from bot.config import redact
from bot.gemini import GEMINI_CLIENT_REV, GeminiError, GeminiRestGenerator, gemini_error_reason
from bot.main import reset_stale_gemini_block
from tests.conftest import FakeResponse

AQ_KEY = "AQ.Ab8DUMMY_TEST_KEY_DO_NOT_USE_0123456789abcdef"


class _Session:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return self.resp


def _ok(text='{"title_tr":"x"}'):
    return FakeResponse(200, content=json.dumps({"candidates": [{"content": {"parts": [
        {"text": "düşünce", "thought": True}, {"text": text}]}}]}).encode())


def test_aq_key_sent_only_in_x_goog_api_key_header():
    s = _Session(_ok())
    gen = GeminiRestGenerator(f" {AQ_KEY}\n", "models/gemini-2.5-flash", session=s)
    out = gen.generate("sys", "prompt", {"type": "object"})
    assert out == '{"title_tr":"x"}'
    url, kw = s.calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert "key=" not in url
    assert kw["headers"]["x-goog-api-key"] == AQ_KEY          # boşluk/satır sonu temizlendi
    assert "Authorization" not in kw["headers"]
    cfg = kw["json"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"] == {"type": "object"}
    assert kw["json"]["systemInstruction"]["parts"][0]["text"] == "sys"


@pytest.mark.parametrize("code,cls", [(401, ErrorClass.AUTH_PERMISSION), (403, ErrorClass.AUTH_PERMISSION),
                                      (404, ErrorClass.AUTH_PERMISSION), (429, ErrorClass.RATE_LIMIT_QUOTA),
                                      (503, ErrorClass.NETWORK_TRANSIENT), (400, ErrorClass.UNEXPECTED_ERROR)])
def test_errors_are_classified_with_safe_reason(code, cls):
    body = {"error": {"code": code, "status": "UNAUTHENTICATED", "message": f"bad key {AQ_KEY}",
                      "details": [{"reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}}
    gen = GeminiRestGenerator(AQ_KEY, "gemini-2.5-flash", session=_Session(FakeResponse(code, json.dumps(body).encode())))
    with pytest.raises(GeminiError) as ei:
        gen.generate("s", "p", {})
    assert ei.value.error_class == cls
    assert "ACCESS_TOKEN_TYPE_UNSUPPORTED" in str(ei.value) and AQ_KEY not in str(ei.value)


def test_error_reason_ignores_free_text_and_redact_masks_aq_keys():
    assert gemini_error_reason({"error": {"status": "PERMISSION_DENIED", "details": [{"reason": AQ_KEY}]}}) \
        == "PERMISSION_DENIED"
    assert gemini_error_reason("garbage") == ""
    assert AQ_KEY not in redact(f"failed with {AQ_KEY}")


def test_invalid_model_name_rejected_before_network():
    s = _Session(_ok())
    with pytest.raises(GeminiError):
        GeminiRestGenerator(AQ_KEY, "../../v1/evil?x=", session=s).generate("s", "p", {})
    assert s.calls == []


def test_empty_candidates_is_schema_error():
    gen = GeminiRestGenerator(AQ_KEY, "gemini-2.5-flash", session=_Session(FakeResponse(200, b'{"candidates":[]}')))
    with pytest.raises(GeminiError) as ei:
        gen.generate("s", "p", {})
    assert ei.value.error_class == ErrorClass.GEMINI_SCHEMA_ERROR


def test_stale_cooldown_from_old_client_is_cleared_once():
    state = {"gemini_quota_blocked_until": "2026-11-16T07:06:23Z", "alerts_last_sent": {"GEMINI_AUTH": "x", "O": "y"}}
    assert reset_stale_gemini_block(state)
    assert "gemini_quota_blocked_until" not in state and state["alerts_last_sent"] == {"O": "y"}
    assert state["gemini_client_rev"] == GEMINI_CLIENT_REV
    # yeni istemcinin koyduğu kilit korunur
    state["gemini_quota_blocked_until"] = "2026-11-16T09:00:00Z"
    assert not reset_stale_gemini_block(state) and state["gemini_quota_blocked_until"]
