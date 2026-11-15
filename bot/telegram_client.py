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
from typing import Any, Callable, Protocol

import requests

from . import ErrorClass, backoff_delay
from .config import redact

log = logging.getLogger("gta6bot")

API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4096
MAX_RETRY_AFTER_SECONDS = 60  # daha uzun bekleme istenirse bu çalışmada vazgeç, sonraki cron denesin


class MessageSender(Protocol):
    """Telegram'a mesaj gönderen ve güncelleme alan nesne (gerçek istemci veya test sahtesi)."""

    def send_message(self, chat_id: str | int, text: str, *, disable_preview: bool = False) -> dict[str, Any]: ...

    def get_updates(self, offset: int | None, allowed_updates: list[str], limit: int = 100) -> list[dict[str, Any]]: ...


class TelegramError(Exception):
    """Sınıflandırılmış Telegram hatası. ``definitely_not_sent`` → istek kesinlikle işlenmedi."""

    def __init__(self, error_class: ErrorClass, message: str, *, definitely_not_sent: bool = False,
                 status: int | None = None, retry_after: float | None = None):
        self.error_class = error_class
        self.definitely_not_sent = definitely_not_sent
        self.status = status
        self.retry_after = retry_after
        super().__init__(message)


class TelegramUncertainError(TelegramError):
    """İstek gönderildi ama sonucu bilinmiyor (ör. okuma zaman aşımı). sendMessage için
    yeniden deneme YAPILMAZ: aynı haberin iki kez yayınlanmasını önlemek önceliklidir."""


class TelegramClient:
    """Telegram Bot API HTTP istemcisi. Token yalnızca istek URL'sinde kullanılır."""

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

    def _post(self, method: str, payload: dict[str, Any], idempotent: bool) -> tuple[Any, TelegramError | None]:
        """Tek HTTP denemesi: (sonuç, hata). Belirsiz durum idempotent olmayan çağrıda doğrudan yükselir."""
        url = f"{API_BASE}/bot{self._token}/{method}"
        try:
            resp = self._session.post(url, json=payload, timeout=self._timeout)
        except requests.exceptions.ConnectTimeout:
            return None, TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: bağlantı zaman aşımı",
                                       definitely_not_sent=True)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as exc:
            kind = "yanıt zaman aşımı" if isinstance(exc, requests.exceptions.ReadTimeout) else "bağlantı hatası"
            if not idempotent:
                raise TelegramUncertainError(ErrorClass.NETWORK_TRANSIENT,
                                             f"{method}: {kind} (gönderim durumu belirsiz)") from None
            return None, TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: {kind}")
        except requests.exceptions.RequestException as exc:
            raise TelegramError(ErrorClass.UNEXPECTED_ERROR, self._safe(f"{method}: {type(exc).__name__}")) from None
        return self._interpret(method, resp, idempotent)

    def _call(self, method: str, payload: dict[str, Any], *, idempotent: bool) -> Any:
        """Sınırlı yeniden deneme: yalnızca geçici hatalarda ve (idempotent değilse) kesin
        gönderilmemiş isteklerde. 401/403/400 için yeniden deneme yok."""
        for attempt in range(self._max_retries + 1):
            result, err = self._post(method, payload, idempotent)
            if err is None:
                return result
            fatal = err.error_class in (ErrorClass.AUTH_PERMISSION, ErrorClass.TELEGRAM_API_ERROR) or (
                err.retry_after is not None and err.retry_after > MAX_RETRY_AFTER_SECONDS)
            if fatal or attempt >= self._max_retries or (not idempotent and not err.definitely_not_sent):
                raise err
            delay = err.retry_after or backoff_delay(attempt)
            log.warning("Telegram %s geçici hata (%s), %.1fs sonra tekrar", method, err.error_class.value, delay)
            self._sleep(min(float(delay), float(MAX_RETRY_AFTER_SECONDS)))
        raise TelegramError(ErrorClass.UNEXPECTED_ERROR, f"{method}: yeniden deneme döngüsü bitti")  # pragma: no cover

    def _interpret(self, method: str, resp: requests.Response, idempotent: bool) -> tuple[Any, TelegramError | None]:
        """HTTP yanıtını (sonuç, hata) çiftine çevirir."""
        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if status == 200 and body.get("ok") is True:
            return body.get("result"), None
        desc = self._safe(str(body.get("description", ""))[:200])
        if status == 429:
            params = body.get("parameters") or {}
            return None, TelegramError(ErrorClass.RATE_LIMIT_QUOTA, f"{method}: 429 {desc}", definitely_not_sent=True,
                                       status=status, retry_after=params.get("retry_after"))
        if status in (401, 403):
            return None, TelegramError(ErrorClass.AUTH_PERMISSION, f"{method}: {status} {desc}",
                                       definitely_not_sent=True, status=status)
        if 500 <= status < 600:
            # 5xx'te sunucu isteği işlemiş olabilir: sendMessage için belirsiz say.
            if not idempotent:
                return None, TelegramUncertainError(ErrorClass.NETWORK_TRANSIENT, f"{method}: {status} (belirsiz)",
                                                    status=status)
            return None, TelegramError(ErrorClass.NETWORK_TRANSIENT, f"{method}: {status}", status=status)
        # 400/404/409 vb.: istek reddedildi, mesaj gönderilmedi.
        return None, TelegramError(ErrorClass.TELEGRAM_API_ERROR, f"{method}: {status} {desc}",
                                   definitely_not_sent=True, status=status)

    # ---- Genel metotlar ---------------------------------------------------------

    def send_message(self, chat_id: str | int, text: str, *, disable_preview: bool = False) -> dict[str, Any]:
        """HTML parse_mode ile mesaj gönderir; 4096 karakter sınırı önceden denetlenir."""
        if len(text) > MAX_MESSAGE_CHARS:
            raise TelegramError(ErrorClass.TELEGRAM_API_ERROR, "Mesaj 4096 karakter sınırını aşıyor",
                                definitely_not_sent=True)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": disable_preview, "prefer_small_media": True},
        }
        result = self._call("sendMessage", payload, idempotent=False)
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int | None, allowed_updates: list[str], limit: int = 100) -> list[dict[str, Any]]:
        """Bekleyen güncellemeleri alır (long polling yok: timeout=0)."""
        payload: dict[str, Any] = {"timeout": 0, "limit": limit, "allowed_updates": allowed_updates}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload, idempotent=True)
        return result if isinstance(result, list) else []
