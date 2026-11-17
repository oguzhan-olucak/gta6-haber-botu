"""Gelir altyapısı: ``config/monetization.json`` doğrulaması ve siteye/Telegram'a güvenli aktarım.

Tasarım ilkeleri:
* **Varsayılan kapalı.** Dosya yoksa ya da bir bölüm ``enabled: false`` ise hiçbir şey gösterilmez;
  bağlantısı (``url``) boş olan ürün/sponsor da gösterilmez. Böylece yarım kalan yapılandırma siteye
  "boş kutu" olarak sızmaz.
* **Şeffaflık zorunlu.** Satış ortaklığı bölümü açıklama metni (``disclosure``) olmadan açılamaz;
  sponsor her yerde "Sponsor" ibaresiyle gösterilir (Ticari Reklam ve Haksız Ticari Uygulamalar
  Yönetmeliği ve Reklam Kurulu'nun sosyal medya rehberindeki "reklam/işbirliği" ayrıştırma ilkesi).
* **Güvenlik.** Yalnızca ``https://`` bağlantılar; metinler HTML'den arındırılır, uzunluk sınırlanır.
  Bot yalnızca doğrulanmış ve o an *etkin* olan alanları ``docs/data/monetization.json`` (+ ``.js``)
  olarak yazar; site bu dosyayı yalnızca ``textContent`` ile basar.
* Bozuk yapılandırma botun asıl işini (haber yayını) asla durdurmaz: hata → tüm gelir bölümleri kapalı.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .site_exporter import clean_text
from .storage import write_if_changed, write_text_if_changed
from .textutil import normalize_text

log = logging.getLogger(__name__)

_HTTPS = r"^(https://[^\s<>\"'\\]{4,600})?$"
_USERNAME = r"^@?([A-Za-z][A-Za-z0-9_]{4,31})?$"
SCHEMA_VERSION = 1


def _clean(value: Any, limit: int) -> str:
    """Görüntülenecek metin: HTML/görünmez karakter temizliği + kırpma (büyük/küçük harf korunur)."""
    return clean_text(value, limit) if isinstance(value, str) else ""


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")   # "_comment" vb. açıklama alanlarına izin ver


class Sponsor(_M):
    enabled: bool = False
    name: str = Field("", max_length=60)
    tagline: str = Field("", max_length=140)
    url: str = Field("", pattern=_HTTPS)
    starts: date | None = None
    ends: date | None = None
    telegram_line: bool = True   # kanal gönderilerinin altına tek satır "Sponsor:" ekle

    def active(self, today: date) -> bool:
        if not (self.enabled and self.name.strip() and self.url):
            return False
        if self.starts and today < self.starts:
            return False
        return not (self.ends and today > self.ends)


class KitItem(_M):
    id: str = Field(pattern=r"^[a-z0-9_-]{2,32}$")
    title: str = Field(max_length=80)
    why: str = Field("", max_length=200)
    price_hint: str = Field("", max_length=40)
    partner: str = Field("", max_length=40)
    url: str = Field("", pattern=_HTTPS)
    # Haberin başlık/özetinde geçerse ürün o haberin sayfasında da önerilir (bağlam içi öneri)
    topics: list[str] = Field(default_factory=list, max_length=20)


class Kit(_M):
    enabled: bool = False
    title: str = Field("Lansman Kiti", max_length=60)
    lead: str = Field("", max_length=240)
    disclosure: str = Field("", max_length=300)
    items: list[KitItem] = Field(default_factory=list, max_length=12)

    @field_validator("items")
    @classmethod
    def _unique(cls, v: list[KitItem]) -> list[KitItem]:
        ids = [i.id for i in v]
        if len(ids) != len(set(ids)):
            raise ValueError("kit öğe id'leri benzersiz olmalı")
        return v


class Support(_M):
    enabled: bool = False
    text: str = Field("", max_length=160)
    url: str = Field("", pattern=_HTTPS)


class MediaKit(_M):
    enabled: bool = True
    contact_telegram: str = Field("", pattern=_USERNAME)
    contact_email: str = Field("", pattern=r"^([A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,24})?$")
    price_note: str = Field("", max_length=200)


class Ads(_M):
    """Reklam ağı (AdSense). İstemci kimliği boşken hiçbir reklam kodu yüklenmez."""
    adsense_client: str = Field("", pattern=r"^(ca-pub-\d{10,20})?$")
    auto_ads: bool = True    # Google'ın otomatik yerleşimi (AdSense panelinde de açık olmalı)
    # Elle yerleşim: yuva adı → AdSense reklam birimi kimliği (yalnızca rakam). Boş yuva gizli kalır.
    slots: dict[str, str] = Field(default_factory=dict, max_length=20)

    @field_validator("slots")
    @classmethod
    def _slot_ids(cls, v: dict[str, str]) -> dict[str, str]:
        if any(not re.fullmatch(r"[a-z0-9-]{2,30}", k) or not re.fullmatch(r"\d{6,20}", s) for k, s in v.items()):
            raise ValueError("geçersiz reklam yuvası")
        return v


class Monetization(_M):
    telegram_channel: str = Field("", pattern=_USERNAME)
    telegram_cta: str = Field("Her doğrulanmış GTA VI haberi ilk önce Telegram kanalımızda.", max_length=140)
    sponsor: Sponsor = Sponsor()
    kit: Kit = Kit()
    support: Support = Support()
    media_kit: MediaKit = MediaKit()
    ads: Ads = Ads()

    @property
    def channel(self) -> str:
        return self.telegram_channel.lstrip("@")


DISABLED = Monetization()


def load_monetization(path: Path) -> tuple[Monetization, str | None]:
    """Dosyayı okur; yoksa kapalı varsayılan, bozuksa kapalı varsayılan + hata notu döner."""
    if not path.exists():
        return DISABLED, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("kök nesne değil")
        return Monetization.model_validate(data), None
    except (OSError, ValueError, ValidationError) as exc:
        count = exc.error_count() if isinstance(exc, ValidationError) else 1
        return DISABLED, f"monetization.json okunamadı ({count} hata); gelir bölümleri kapalı"


def local_today(now: datetime, offset_hours: int) -> date:
    return (now.astimezone(timezone.utc) + timedelta(hours=offset_hours)).date()


def public_payload(m: Monetization, today: date) -> dict[str, Any]:
    """Siteye giden, yalnızca etkin ve doğrulanmış alanlar (beyaz liste)."""
    out: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if m.channel:
        out["telegram"] = {"url": f"https://t.me/{m.channel}", "handle": "@" + m.channel,
                           "cta": _clean(m.telegram_cta, 140)}
    if m.sponsor.active(today):
        out["sponsor"] = {"name": _clean(m.sponsor.name, 60), "tagline": _clean(m.sponsor.tagline, 140),
                          "url": m.sponsor.url}
    items = [i for i in m.kit.items if i.url] if m.kit.enabled else []
    if items and m.kit.disclosure.strip():
        out["kit"] = {
            "title": _clean(m.kit.title, 60), "lead": _clean(m.kit.lead, 240),
            "disclosure": _clean(m.kit.disclosure, 300),
            "items": [{"id": i.id, "title": _clean(i.title, 80), "why": _clean(i.why, 200),
                       "price_hint": _clean(i.price_hint, 40), "partner": _clean(i.partner, 40), "url": i.url,
                       "topics": [normalize_text(t).lower()[:40] for t in i.topics if isinstance(t, str)]}
                      for i in items],
        }
    if m.support.enabled and m.support.url:
        out["support"] = {"text": _clean(m.support.text, 160) or "Bülteni destekle", "url": m.support.url}
    if m.ads.adsense_client:
        out["ads"] = {"client": m.ads.adsense_client, "auto": m.ads.auto_ads, "slots": dict(m.ads.slots)}
    if m.media_kit.enabled:
        contact: dict[str, str] = {}
        if m.media_kit.contact_telegram:
            contact["telegram"] = "https://t.me/" + m.media_kit.contact_telegram.lstrip("@")
        if m.media_kit.contact_email:
            contact["email"] = m.media_kit.contact_email
        out["media_kit"] = {"contact": contact, "price_note": _clean(m.media_kit.price_note, 200)}
    return out


def sponsor_line(m: Monetization, today: date) -> tuple[str, str, str] | None:
    """Telegram gönderisine eklenecek sponsor (ad, slogan, url) ya da None."""
    if m.sponsor.active(today) and m.sponsor.telegram_line:
        return _clean(m.sponsor.name, 60), _clean(m.sponsor.tagline, 140), m.sponsor.url
    return None


def kit_for_text(payload: dict[str, Any], text: str, limit: int = 2) -> list[dict[str, Any]]:
    """Haber metninde konusu geçen kit ürünleri (bağlam içi öneri); yoksa boş liste."""
    kit = payload.get("kit")
    if not kit:
        return []
    hay = " " + normalize_text(text).lower() + " "
    hits = [i for i in kit["items"] if any(t and (" " + t) in hay for t in i.get("topics", []))]
    return hits[:limit]


def js_wrap(data: dict[str, Any], var_name: str) -> str:
    if not re.fullmatch(r"__[A-Z0-9_]+__", var_name):
        raise ValueError("geçersiz değişken adı")
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    safe = (raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return f"window.{var_name} = {safe};\n"


def export_monetization(payload: dict[str, Any], site_data_dir: Path) -> bool:
    """docs/data/monetization.json + .js; değişmediyse dokunmaz."""
    site_data_dir.mkdir(parents=True, exist_ok=True)
    target = site_data_dir / "monetization.json"
    js_path = site_data_dir / "monetization.js"
    try:
        if json.loads(target.read_text(encoding="utf-8")) == payload and js_path.exists():
            return False
    except (OSError, ValueError):
        pass
    write_if_changed(target, payload)
    write_text_if_changed(js_path, js_wrap(payload, "__GTA6_MONETIZATION__"))
    return True
