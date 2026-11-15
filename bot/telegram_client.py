"""Telegram Bot API HTTP çağrıları (tek nokta).

Doğrulanmış sınırlar (core.telegram.org/bots/api, Bot API 10.4 — 9 Kasım 2026):
- Bot API'de geçmiş kanal gönderilerinin görüntülenme/iletilme sayısını sorgulayan
  bir metot yoktur; Message nesnesinde bu sayılar için alan yoktur.
- ``message_reaction_count`` güncellemeleri yalnızca bot sohbette yöneticiyse ve
  ``allowed_updates`` içinde açıkça istenirse gelir; gruplanır ve birkaç dakika
  gecikebilir. Geriye dönük sorgulanamaz.
- ``getUpdates`` bir webhook ayarlıyken çalışmaz.

Güvenlik: token yalnızca URL'de kullanılır; hata mesajlarında maskelenir ve
istisna zincirine ham ``requests`` hatası (URL'li) eklenmez.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from . import ErrorClass, backoff_delay
from .config import redact

log = logging.getLogger("gta6bot")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096


class TelegramError(Exception):
    def __init__(self, error_class: ErrorClass, message: str, *, definitely_not_sent: bool = False,
                 status: int | None = None):
        self.error_class = error_class
        self.definitely_not_sent = definitely_not_sent
        self.status = status
        super().__init__(message)


class TelegramUncertainError(TelegramError):
    """İstek gönderildi ama sonucu bilinmiyor (ör. okuma zaman aşımı). sendMessage için
    yeniden deneme YAPILMAZ: aynı haberin iki kez yayınlanmasını önlemek önceliklidir."""


class TelegramClient:
    def __init__(self, token: str, *, session: requests.Session | None = None, timeout: float = 15,
                 max_retries: int = 3, sleep: Callable[[float], None] = time.sleep):
        if not token:
            raise ValueError("Telegram token boş olamaz")
        self._token = token
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep

    def __repr__(self) -> str:
        return "TelegramClient(<redacted>)"

    def _safe(self, text: str) -> str:
        return redact(str(text), [self._token])

    def _call(self, method: str, payload: dict[str, Any], *, idempotent: bool) -> Any:
        url = f"{API_BASE}/bot{self._token}/{method}"
        attempt = 0
        while True:
            try:
                resp = self._session.post(url, json=payload, timeout=self._timeout)
            except requests.exceptions.ConnectTimeout:
                err = TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: bağlantı zaman aşımı",
                                    definitely_not_sent=True)
            except requests.exceptions.ReadTimeout:
                if not idempotent:
                    raise TelegramUncertainError(ErrorClass.NETWORK_TRANSIENT,
                                                 f"{method}: yanıt zaman aşımı (gönderim durumu belirsiz)") from None
                err = TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: yanıt zaman aşımı")
            except requests.exceptions.ConnectionError:
                if not idempotent:
                    raise TelegramUncertainError(ErrorClass.NETWORK_TRANSIENT,
                                                 f"{method}: bağlantı hatası (gönderim durumu belirsiz)") from None
                err = TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: bağlantı hatası")
            except requests.exceptions.RequestException as exc:
                raise TelegramError(ErrorClass.UNEXPECTED_ERROR,
                                    self._safe(f"{method}: {type(exc).__name__}")) from None
            else:
                err = self._interpret(method, resp, idempotent)
                if err is None:
                    return self._result
            # yeniden deneme kararı
            if attempt >= self._max_retries or err.error_class in (ErrorClass.AUTH_PERMISSION,
                                                                   ErrorClass.TELEGRAM_API_ERROR):
                raise err
            if not idempotent and not err.definitely_not_sent:
                raise err
            delay = getattr(err, "retry_after", None) or backoff_delay(attempt)
            log.warning("Telegram %s geçici hata (%s), %.1fs sonra tekrar", method, err.error_class.value, delay)
            self._sleep(min(float(delay), 60.0))
            attempt += 1

    def _interpret(self, method: str, resp: requests.Response, idempotent: bool) -> TelegramError | None:
        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if status == 200 and isinstance(body, dict) and body.get("ok") is True:
            self._result = body.get("result")
            return None
        desc = self._safe(str(body.get("description", ""))[:200]) if isinstance(body, dict) else ""
        if status == 429:
            err = TelegramError(ErrorClass.RATE_LIMIT_QUOTA, f"{method}: 429 {desc}", definitely_not_sent=True,
                                status=status)
            params = body.get("parameters") if isinstance(body, dict) else None
            err.retry_after = (params or {}).get("retry_after")  # type: ignore[attr-defined]
            return err
        if status in (401, 403):
            return TelegramError(ErrorClass.AUTH_PERMISSION, f"{method}: {status} {desc}", definitely_not_sent=True,
                                 status=status)
        if 500 <= status < 600:
            # 5xx'te sunucu isteği işlemiş olabilir: sendMessage için belirsiz say.
            if not idempotent:
                return TelegramUncertainError(ErrorClass.NETWORK_TRANSIENT, f"{method}: {status} (belirsiz)",
                                              status=status)
            return TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: {status}", status=status)
        # 400/404/409 vb.: istek reddedildi, mesaj gönderilmedi.
        return TelegramError(ErrorClass.TELEGRAM_API_ERROR, f"{method}: {status} {desc}", definitely_not_sent=True,
                             status=status)

    # ---- Genel metotlar ---------------------------------------------------------

    def send_message(self, chat_id: str | int, text: str, *, disable_preview: bool = False) -> dict:
        if len(text) > MAX_MESSAGE_CHARS:
            raise TelegramError(ErrorClass.TELEGRAM_API_ERROR, "Mesaj 4096 karakter sınırını aşıyor",
                                definitely_not_sent=True)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": disable_preview, "prefer_small_media": True},
        }
        return self._call("sendMessage", payload, idempotent=False)

    def get_updates(self, offset: int | None, allowed_updates: list[str], limit: int = 100) -> list[dict]:
        payload: dict[str, Any] = {"timeout": 0, "limit": limit, "allowed_updates": allowed_updates}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, idempotent=True)
        return result if isinstance(result, list) else []
