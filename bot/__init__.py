"""GTA VI Türkçe Telegram haber botu.

Ortak küçük yardımcılar burada: hata sınıfları ve exponential backoff + jitter.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from enum import Enum

__version__ = "1.0.0"


class ErrorClass(str, Enum):
    """Brifteki hata sınıfları."""
    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    RATE_LIMIT_QUOTA = "RATE_LIMIT_QUOTA"
    AUTH_PERMISSION = "AUTH_PERMISSION"
    RSS_PARSE_ERROR = "RSS_PARSE_ERROR"
    DATA_SCHEMA_ERROR = "DATA_SCHEMA_ERROR"
    TELEGRAM_API_ERROR = "TELEGRAM_API_ERROR"
    GEMINI_SCHEMA_ERROR = "GEMINI_SCHEMA_ERROR"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 30.0, rng: random.Random | None = None) -> float:
    """Full-jitter exponential backoff: U(0, min(cap, base * 2**attempt))."""
    r = rng or random
    return r.uniform(0, min(cap, base * (2 ** attempt)))


def utcnow() -> datetime:
    """Şu anki UTC zamanı."""
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """Datetime → saniye hassasiyetinde ISO 8601 UTC (Z) dizesi."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    """ISO 8601 dizesini UTC datetime'a çevirir; geçersizse None."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
