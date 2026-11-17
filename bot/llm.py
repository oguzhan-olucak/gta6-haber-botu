"""Çoklu sağlayıcılı LLM katmanı: Gemini → Groq → OpenRouter → GitHub Models.

Özet üretimi tek bir sağlayıcıya bağlı kalmasın diye ``FallbackGenerator`` sağlayıcıları sırayla dener:

1. **Gemini** (``GeminiRestGenerator``) — her zaman tanımlı.
2. **Groq** — ``GROQ_API_KEY`` varsa; OpenAI uyumlu ``/chat/completions``. Varsayılan model
   ``openai/gpt-oss-120b`` (Groq, ``llama-3.3-70b-versatile``'ı 16 Ağustos 2026'da ücretsiz katmandan
   kaldırdı ve bunu önerdi). ``GROQ_MODEL`` ile değiştirilebilir.
3. **OpenRouter** — ``OPENROUTER_API_KEY`` varsa. Varsayılan ``openrouter/free`` (o an ücretsiz olan bir
   modeli seçen yönlendirici). ``OPENROUTER_MODEL`` yalnızca ``:free`` ile biten ya da ``openrouter/free``
   olan bir ad olabilir; aksi hâlde sağlayıcı devre dışı kalır (ücretli modele asla geçilmez).

4. **GitHub Models** — GitHub Actions içinde ``GITHUB_TOKEN`` (workflow'da ``permissions: models: read``)
   varsa; ayrı anahtar gerekmez. Varsayılan ``openai/gpt-4o-mini``; ``GITHUB_MODELS_MODEL`` ile değişir,
   ``GITHUB_MODELS=0`` ile kapatılır. Ücretsiz katman günlük istek sınırlıdır; bot günde en fazla birkaç
   özet ürettiği için yeterlidir. Hizmet erişilemezse (401/403/404) zincir sessizce devam eder.

**Devre kesici:** Bir sağlayıcı bir çalışmada geçici hata (503/429/zaman aşımı) ya da yetki hatası
verdiyse o çalışmanın kalan çağrılarında sıranın **sonuna** alınır; böylece Gemini 503 verdiğinde her
haberde 45 sn bekleyip yeniden denenmez, doğrudan sağlıklı sağlayıcıya gidilir.

Bir sonraki sağlayıcıya yalnızca **geçici** hatalarda geçilir: 503/500, 429 (kota), zaman aşımı. Yetki
(401/403) hatası o sağlayıcı için son sözdür ama zincir yine devam eder; hepsi başarısız olursa ilk
sağlayıcının (Gemini) hatası yükseltilir, böylece soğuma/alarm mantığı değişmez.

Tüm sağlayıcılar aynı sistem talimatını, aynı kullanıcı istemini (``untrusted_source_data`` yalıtımıyla)
ve aynı JSON şemasını alır; çıktı her durumda ``processor`` içindeki Pydantic + halüsinasyon denetiminden
geçer. Hangi sağlayıcının kullanıldığı ``last_provider`` ile dışarı verilir.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

import requests

from . import ErrorClass
from .config import redact
from .gemini import GeminiError

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
OPENROUTER_DEFAULT_MODEL = "openrouter/free"
GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODELS_DEFAULT_MODEL = "openai/gpt-4o-mini"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{1,100}$")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")
# Bir sonraki sağlayıcıya geçiren hata sınıfları (geçici: aşırı yük, kota, zaman aşımı)
FALLBACK_ON = (ErrorClass.NETWORK_TRANSIENT, ErrorClass.RATE_LIMIT_QUOTA)


class Generator(Protocol):
    def generate(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str: ...


def openrouter_model_is_free(model: str) -> bool:
    """OpenRouter'da yalnızca ücretsiz uç noktalar: ``...:free`` veya ``openrouter/free``."""
    return model == OPENROUTER_DEFAULT_MODEL or model.endswith(":free")


class OpenAICompatGenerator:
    """OpenAI uyumlu ``/chat/completions`` istemcisi (Groq, OpenRouter).

    Önce ``response_format: json_schema`` (strict değil) ister; model bunu desteklemiyorsa (HTTP 400)
    bir kez ``json_object`` ile yineler. Anahtar yalnızca ``Authorization: Bearer`` başlığında gider."""

    def __init__(self, name: str, url: str, api_key: str, model: str, *,
                 session: requests.Session | None = None, timeout: float = 45.0,
                 extra_headers: Mapping[str, str] | None = None):
        if not _MODEL_RE.match(model):
            raise ValueError(f"{name}: geçersiz model adı")
        self.name = name
        self._url = url
        self._api_key = api_key.strip().strip('"').strip("'")
        self.model = model
        self._session = session or requests.Session()
        self._timeout = timeout
        self._extra = dict(extra_headers or {})

    def __repr__(self) -> str:
        return f"OpenAICompatGenerator({self.name!r}, model={self.model!r})"

    def body(self, system_instruction: str, prompt: str, schema: dict[str, Any], *, json_mode: str) -> dict[str, Any]:
        """İstek gövdesi (testler için ağdan bağımsız)."""
        if json_mode == "json_schema":
            fmt: dict[str, Any] = {"type": "json_schema",
                                   "json_schema": {"name": "gta6_haber_ozeti", "strict": False, "schema": schema}}
            system = system_instruction
        else:  # json_object: şema talimata eklenir, çıktı yine Pydantic ile doğrulanır
            fmt = {"type": "json_object"}
            system = (system_instruction + "\n\nYalnızca şu JSON şemasına uyan tek bir JSON nesnesi döndür:\n"
                      + json.dumps(schema, ensure_ascii=False))
        return {"model": self.model, "temperature": 0.2, "max_tokens": 1024, "response_format": fmt,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}

    def generate(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        try:
            return self._post(self.body(system_instruction, prompt, schema, json_mode="json_schema"))
        except _SchemaUnsupported:
            return self._post(self.body(system_instruction, prompt, schema, json_mode="json_object"),
                              allow_schema_retry=False)

    def _post(self, body: dict[str, Any], allow_schema_retry: bool = True) -> str:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", **self._extra}
        try:
            resp = self._session.post(self._url, headers=headers, json=body, timeout=self._timeout,
                                      allow_redirects=False)
        except requests.exceptions.Timeout:
            raise GeminiError(ErrorClass.NETWORK_TRANSIENT, f"{self.name} zaman aşımı") from None
        except requests.exceptions.RequestException as exc:
            raise GeminiError(ErrorClass.NETWORK_TRANSIENT, f"{self.name} bağlantı hatası {type(exc).__name__}") from None
        try:
            data = resp.json()
        except ValueError:
            data = None
        code = resp.status_code
        if code != 200:
            msg = redact(f"{self.name} HTTP {code} {_error_code(data)}".strip(), [self._api_key])
            if code == 400 and allow_schema_retry:
                raise _SchemaUnsupported(msg)
            if code == 429:
                raise GeminiError(ErrorClass.RATE_LIMIT_QUOTA, msg)
            if code in (401, 403, 404):
                raise GeminiError(ErrorClass.AUTH_PERMISSION, msg)
            if code in (408,) or 500 <= code < 600:
                raise GeminiError(ErrorClass.NETWORK_TRANSIENT, msg)
            raise GeminiError(ErrorClass.UNEXPECTED_ERROR, msg)
        text = _message_text(data)
        if not text:
            raise GeminiError(ErrorClass.GEMINI_SCHEMA_ERROR, f"{self.name} boş yanıt döndürdü")
        return text


class _SchemaUnsupported(Exception):
    """Model ``json_schema`` biçimini reddetti (HTTP 400): ``json_object`` ile yinele."""


def _error_code(body: Any) -> str:
    """OpenAI biçimli hata gövdesinden yalnızca kısa kod/tür (serbest metin alınmaz)."""
    err = body.get("error") if isinstance(body, dict) else None
    if not isinstance(err, dict):
        return ""
    parts = [str(err.get(k)) for k in ("type", "code") if isinstance(err.get(k), (str, int))]
    return "/".join(p for p in parts if re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", p))


def _message_text(data: Any) -> str:
    """``choices[0].message.content``; olası ```json çitlerini temizler."""
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(content, str):
        return ""
    return _FENCE_RE.sub("", content.strip()).strip()


class FallbackGenerator:
    """Sağlayıcıları sırayla dener; yalnızca geçici/yetki hatasında bir sonrakine geçer.

    Çalışma içi devre kesici: hata veren sağlayıcı sonraki çağrılarda sıranın sonuna alınır.
    Hepsi başarısız olursa birincil sağlayıcının (Gemini) hatası yükseltilir; o denenmediyse ilk hata."""

    def __init__(self, providers: list[tuple[str, Generator]]):
        if not providers:
            raise ValueError("en az bir sağlayıcı gerekli")
        self.providers = providers
        self.last_provider: str | None = None
        self.attempts: list[str] = []   # son çağrıda denenen sağlayıcılar ve sonuçları (tanı için)
        self.run_attempts: list[str] = []  # bu çalışmadaki tüm denemeler (run_log'a yazılır)
        self.tripped: set[str] = set()

    @property
    def chain(self) -> list[str]:
        return [n for n, _ in self.providers]

    @property
    def resolved_model(self) -> str | None:
        """Gemini'nin 404/503 sonrası seçtiği model (alarm için), varsa."""
        return getattr(self.providers[0][1], "resolved_model", None)

    def _ordered(self) -> list[tuple[str, Generator]]:
        healthy = [p for p in self.providers if p[0] not in self.tripped]
        return healthy + [p for p in self.providers if p[0] in self.tripped]

    def generate(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        errors: dict[str, GeminiError] = {}
        first_error: GeminiError | None = None
        self.attempts = []
        for name, gen in self._ordered():
            try:
                out = gen.generate(system_instruction, prompt, schema)
            except GeminiError as exc:
                self.attempts.append(f"{name}:{exc.error_class.value}")
                errors[name] = exc
                first_error = first_error or exc
                if exc.error_class not in FALLBACK_ON and exc.error_class != ErrorClass.AUTH_PERMISSION:
                    self.run_attempts.extend(self.attempts)
                    raise
                self.tripped.add(name)
                log.warning("LLM sağlayıcısı %s başarısız (%s); sıradakine geçiliyor", name, exc.error_class.value)
                continue
            self.attempts.append(f"{name}:ok")
            self.run_attempts.extend(self.attempts)
            self.last_provider = name
            return out
        self.run_attempts.extend(self.attempts)
        assert first_error is not None
        raise errors.get(self.providers[0][0]) or first_error


def build_generator(gemini: Generator, env: Mapping[str, str], *,
                    session: requests.Session | None = None) -> FallbackGenerator:
    """Tanımlı secret'lara göre sağlayıcı zinciri kurar; tanımsız olanlar sessizce atlanır."""
    providers: list[tuple[str, Generator]] = [("gemini", gemini)]
    groq_key = (env.get("GROQ_API_KEY") or "").strip()
    if groq_key:
        model = (env.get("GROQ_MODEL") or "").strip() or GROQ_DEFAULT_MODEL
        try:
            providers.append(("groq", OpenAICompatGenerator("groq", GROQ_URL, groq_key, model, session=session)))
        except ValueError:
            log.warning("GROQ_MODEL geçersiz; Groq devre dışı")
    or_key = (env.get("OPENROUTER_API_KEY") or "").strip()
    if or_key:
        model = (env.get("OPENROUTER_MODEL") or "").strip() or OPENROUTER_DEFAULT_MODEL
        if not openrouter_model_is_free(model):
            log.warning("OPENROUTER_MODEL ücretsiz değil (':free' veya 'openrouter/free' olmalı); OpenRouter devre dışı")
        else:
            try:
                providers.append(("openrouter", OpenAICompatGenerator(
                    "openrouter", OPENROUTER_URL, or_key, model, session=session,
                    extra_headers={"X-Title": "GTA VI Turkiye Bulteni"})))
            except ValueError:
                log.warning("OPENROUTER_MODEL geçersiz; OpenRouter devre dışı")
    gh_token = (env.get("GITHUB_TOKEN") or "").strip()
    if gh_token and (env.get("GITHUB_MODELS") or "").strip() != "0":
        model = (env.get("GITHUB_MODELS_MODEL") or "").strip() or GITHUB_MODELS_DEFAULT_MODEL
        try:
            providers.append(("github", OpenAICompatGenerator("github", GITHUB_MODELS_URL, gh_token, model,
                                                              session=session)))
        except ValueError:
            log.warning("GITHUB_MODELS_MODEL geçersiz; GitHub Models devre dışı")
    return FallbackGenerator(providers)
