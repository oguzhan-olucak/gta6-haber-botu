"""Ortam değişkenleri ve JSON ayarlarının doğrulanması + secret maskeleyen loglama.

Secret'lar yalnızca ortam değişkenlerinden okunur. Hiçbir secret dosyaya yazılmaz,
loglanmaz veya Telegram mesajına eklenmez.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .storage import read_json

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

TrustClass = Literal["OFFICIAL", "ESTABLISHED_MEDIA", "COMMUNITY", "UNKNOWN"]

SECRET_ENV_NAMES = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ADMIN_CHAT_ID")
# Telegram bot token biçimi: <sayı>:<35 civarı karakter>. Biçime uyan her şey maskelenir.
_BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_BOT_URL_RE = re.compile(r"(api\.telegram\.org/bot)[^/\s]+")
_GOOGLE_KEY_RE = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b|\bAQ\.[0-9A-Za-z_.-]{20,}")


class ConfigError(Exception):
    """Ayar dosyası doğrulanamadı."""
    pass


# ---- Ayar modelleri -------------------------------------------------------------

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MinSourceStrength(_Strict):
    """Etiket türüne göre minimum kaynak gücü eşikleri."""
    OFFICIAL: int = Field(90, ge=0, le=100)
    MULTI_SOURCE: int = Field(70, ge=0, le=100)
    SINGLE_SOURCE: int = Field(50, ge=0, le=100)
    COMMUNITY: int = Field(15, ge=0, le=100)


class RelevanceKeywords(_Strict):
    """GTA VI ilgi anahtar kelimeleri.

    - ``strong``: tek başına yeterli (GTA VI, Leonida...).
    - ``specific``: GTA VI'ya özgü ama tek başına belirsiz (Vice City, Lucia, Jason); bir ``brand``
      terimiyle birlikte ya da resmî kaynakta geçerse yeterli.
    - ``brand``: Rockstar / Take-Two.
    - ``exclude``: güçlü terim yoksa haberi eler (GTA Online, Definitive Edition...).
    - ``context``: yalnızca öncelik puanına katkı.
    """
    strong: list[str] = Field(min_length=1)
    context: list[str] = Field(default_factory=list)
    specific: list[str] = Field(default_factory=list)
    brand: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)

    @field_validator("strong", "context", "specific", "brand", "exclude")
    @classmethod
    def _lower(cls, v: list[str]) -> list[str]:
        return [s.strip().lower() for s in v if s.strip()]


class ContentLimits(_Strict):
    """Başlık/özet ve kaynak metni karakter sınırları."""
    title_min_chars: int = Field(15, ge=5)
    title_max_chars: int = Field(110, le=200)
    summary_min_chars: int = Field(60, ge=20)
    summary_max_chars: int = Field(480, le=1500)
    source_text_max_chars: int = Field(700, ge=100, le=4000)


class RetentionLimits(_Strict):
    """Veri dosyaları saklama sınırları."""
    history_max_records: int = Field(2000, ge=50)
    history_max_age_days: int = Field(180, ge=7)
    seen_items_max_age_hours: int = Field(240, ge=24)
    seen_items_max_records: int = Field(5000, ge=100)
    run_log_max_records: int = Field(50, ge=5)
    candidate_pool_max_records: int = Field(400, ge=20)


class Settings(_Strict):
    """config/settings.json şeması (bilinmeyen alan yasak)."""
    paused: bool = False
    brand_name: str = "GTA VI Türkiye Bülteni"
    display_utc_offset_hours: int = Field(3, ge=-12, le=14)
    max_rss_items_per_run: int = Field(60, ge=1, le=500)
    max_item_age_hours: int = Field(48, ge=1, le=336)
    max_gemini_calls_per_run: int = Field(4, ge=0, le=50)
    gemini_quota_cooldown_minutes: int = Field(60, ge=5)
    max_daily_posts: int = Field(8, ge=0, le=50)
    min_minutes_between_posts: int = Field(30, ge=0)
    min_publish_threshold: int = Field(55, ge=0, le=100)
    min_source_strength: MinSourceStrength = MinSourceStrength()
    allow_single_source_media: bool = True
    allow_community_rumors: bool = False
    verify_source_urls: bool = True
    dedup_lookback_hours: int = Field(72, ge=1)
    title_similarity_threshold: float = Field(0.45, gt=0, le=1)
    cluster_similarity_threshold: float = Field(0.27, gt=0, le=1)
    cluster_max_gap_hours: float = Field(72, gt=0)
    daily_limit_mode: Literal["calendar_day_local", "rolling_24h"] = "calendar_day_local"
    reject_injection_suspects: bool = True
    run_deadline_seconds: int = Field(600, ge=30, le=3000)
    state_heartbeat_minutes: int = Field(60, ge=0, le=1440)
    public_channel_username: str = Field("", pattern=r"^@?([A-Za-z][A-Za-z0-9_]{4,31})?$")
    site_max_items: int = Field(60, ge=1, le=500)
    export_site_feed: bool = True
    http_timeout_seconds: float = Field(15, gt=0, le=120)
    http_max_retries: int = Field(3, ge=0, le=6)
    http_max_response_bytes: int = Field(2_000_000, ge=10_000)
    digest_hours_utc: list[int] = Field(default_factory=lambda: [6, 18])
    digest_window_minutes: int = Field(90, ge=10, le=180)
    health_alert_hours: int = Field(24, ge=1)
    alert_dedup_hours: int = Field(6, ge=1)
    measurement_window_hours: int = Field(24, ge=1)
    min_sample_per_group: int = Field(5, ge=2)
    early_signal_below_n: int = Field(15, ge=2)
    relevance_keywords: RelevanceKeywords
    content_limits: ContentLimits = ContentLimits()
    retention_limits: RetentionLimits = RetentionLimits()

    @field_validator("digest_hours_utc")
    @classmethod
    def _hours(cls, v: list[int]) -> list[int]:
        if any(h < 0 or h > 23 for h in v):
            raise ValueError("digest_hours_utc 0-23 arasında olmalı")
        return sorted(set(v))


class Source(_Strict):
    """config/sources.json içindeki tek kaynak."""
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str
    trust_class: TrustClass
    feed_url: str = ""
    enabled: bool = True
    rss_verified: bool = False
    allowed_domains: list[str] = Field(min_length=1)
    origin_group: str
    notes: str = ""
    kind: Literal["rss", "google_news", "html_listing"] = "rss"
    link_pattern: str = ""
    max_verifications_per_run: int = Field(8, ge=1, le=50)
    max_item_age_hours: int | None = Field(None, ge=1, le=336)

    @field_validator("link_pattern")
    @classmethod
    def _regex(cls, v: str) -> str:
        if v:
            re.compile(v)
        return v

    @field_validator("feed_url")
    @classmethod
    def _https(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("feed_url https:// ile başlamalı")
        return v

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = [d.strip().lower().lstrip(".") for d in v]
        if any(not d or "/" in d or ":" in d for d in out):
            raise ValueError("allowed_domains yalnızca alan adı içermeli")
        return out


class SourcesFile(BaseModel):
    """config/sources.json kök şeması."""
    model_config = ConfigDict(extra="allow")
    sources: list[Source]

    @field_validator("sources")
    @classmethod
    def _unique(cls, v: list[Source]) -> list[Source]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("source id'leri benzersiz olmalı")
        return v


def load_settings(path: Path | None = None) -> Settings:
    """settings.json'u okuyup doğrular."""
    path = path or CONFIG_DIR / "settings.json"
    try:
        return Settings.model_validate(read_json(path, dict))
    except ValidationError as exc:
        raise ConfigError(f"settings.json doğrulanamadı: {exc.error_count()} hata") from None


def load_sources(path: Path | None = None) -> list[Source]:
    """sources.json'u okuyup doğrular."""
    path = path or CONFIG_DIR / "sources.json"
    try:
        return SourcesFile.model_validate(read_json(path, dict)).sources
    except ValidationError as exc:
        raise ConfigError(f"sources.json doğrulanamadı: {exc.error_count()} hata") from None


# ---- Ortam / secret'lar -----------------------------------------------------------

@dataclass(frozen=True)
class Secrets:
    """Ortam değişkenlerinden gelen gizli değerler (repr maskeli)."""
    gemini_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    gemini_model: str
    admin_chat_id: str | None

    def __repr__(self) -> str:  # yanlışlıkla loglanırsa bile değer sızmasın
        return "Secrets(<redacted>)"

    __str__ = __repr__


def load_secrets(env: Mapping[str, str] | None = None) -> tuple[Secrets | None, list[str]]:
    """Eksik değişken adlarının listesini döndürür (değerleri asla döndürmez/loglamaz)."""
    env = os.environ if env is None else env
    required = ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GEMINI_MODEL")
    missing = [k for k in required if not (env.get(k) or "").strip()]
    if missing:
        return None, missing
    return (
        Secrets(
            gemini_api_key=env["GEMINI_API_KEY"].strip(),
            telegram_bot_token=env["TELEGRAM_BOT_TOKEN"].strip(),
            telegram_chat_id=env["TELEGRAM_CHAT_ID"].strip(),
            gemini_model=env["GEMINI_MODEL"].strip(),
            admin_chat_id=(env.get("ADMIN_CHAT_ID") or "").strip() or None,
        ),
        [],
    )


# ---- Secret maskeleyen loglama ------------------------------------------------------

def redact(text: str, extra_secrets: list[str] | None = None) -> str:
    """Metindeki bilinen secret değerlerini ve token/anahtar biçimlerini *** ile maskeler."""
    if not text:
        return text
    secrets = [os.environ.get(n, "") for n in SECRET_ENV_NAMES]
    secrets += extra_secrets or []
    for s in sorted({s for s in secrets if s and len(s) >= 6}, key=len, reverse=True):
        text = text.replace(s, "***")
    text = _BOT_URL_RE.sub(r"\1***", text)
    text = _BOT_TOKEN_RE.sub("***", text)
    text = _GOOGLE_KEY_RE.sub("***", text)
    return text


class RedactingFilter(logging.Filter):
    """Her log kaydını (traceback dahil) maskeleyen logging filtresi."""
    def filter(self, record: logging.LogRecord) -> bool:
        """Kaydı maskeler; her zaman True döner."""
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - bozuk format
            msg = str(record.msg)
        record.msg = redact(msg)
        record.args = ()
        if record.exc_info:
            # Traceback metnini de maskele: önce formatla, sonra exc_info'yu kaldır.
            formatted = logging.Formatter().formatException(record.exc_info)
            record.msg = f"{record.msg}\n{redact(formatted)}"
            record.exc_info = None
            record.exc_text = None
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """gta6bot logger'ını maskeleme filtresiyle kurar."""
    logger = logging.getLogger("gta6bot")
    logger.setLevel(level)
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
    # urllib3/requests debug logları URL'de token içerebilir: sustur.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return logger
