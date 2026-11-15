"""Telegram mesaj şablonları, idempotent yayın, günlük limit, yönetici özeti ve alarm tekilleştirme.

İdempotency protokolü (aynı haberin iki kez yayınlanmaması):
1. Gönderimden ÖNCE history'ye ``SENDING`` kaydı atomik olarak yazılır.
2. Başarılıysa ``PUBLISHED`` + message_id.
3. Zaman aşımı / 5xx gibi belirsiz durumda ``UNCERTAIN``: bu haber bir daha otomatik
   gönderilmez (olası tek kayıp, olası mükerrer gönderiden iyidir). Özette raporlanır.
4. Telegram açıkça reddettiyse (400 vb.) ``FAILED``; sonraki çalışmada yeniden aday olabilir.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import ErrorClass, iso, parse_iso
from .config import Settings
from .processor import LABEL_NOTE, LABEL_TEXT, GeneratedContent, Label
from .telegram_client import TelegramClient, TelegramError, TelegramUncertainError

log = logging.getLogger("gta6bot")

BADGE = {
    Label.OFFICIAL: "🟩",
    Label.MULTI_SOURCE: "🟦",
    Label.SINGLE_SOURCE: "🟨",
    Label.LEAK_CLAIM: "🟥",
    Label.COMMUNITY_CLAIM: "🟧",
}

CATEGORY_TR = {
    "OFFICIAL_ANNOUNCEMENT": "Duyuru",
    "TRAILER_MEDIA": "Fragman & Medya",
    "GAMEPLAY_TECH": "Oynanış & Teknoloji",
    "RELEASE_PLATFORMS": "Çıkış & Platformlar",
    "INDUSTRY_BUSINESS": "Sektör & İş",
    "COMMUNITY_RUMOR": "Topluluk",
    "OTHER": "Gündem",
}

ACTIVE_STATUSES = {"SENDING", "PUBLISHED", "UNCERTAIN"}

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
             "Kasım", "Aralık"]


def tr_upper(text: str) -> str:
    """Türkçe büyük harf: i -> İ, ı -> I (str.upper() 'i'yi 'I' yapar)."""
    return (text or "").replace("i", "İ").replace("ı", "I").upper()


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def format_local(dt: datetime, offset_hours: int) -> str:
    local = dt.astimezone(timezone(timedelta(hours=offset_hours)))
    suffix = "TSİ" if offset_hours == 3 else f"UTC{offset_hours:+d}"
    return f"{local.day} {TR_MONTHS[local.month - 1]} {local.year}, {local:%H:%M} {suffix}"


def render_post(content: GeneratedContent, label: Label, sources: list[dict], settings: Settings,
                now: datetime) -> str:
    """Profesyonel bülten düzeni: tek rozet, etiket satırı, kalın başlık, özet, kaynak bloğu, imza.

    Telegram HTML parse_mode yalnızca sınırlı etiket destekler (b, i, a, code, blockquote...);
    tüm dinamik metin html.escape ile kaçırılır.
    """
    category = CATEGORY_TR.get(content.category, "Gündem")
    src_links = " · ".join(f'<a href="{_e(s["url"])}">{_e(s["name"])}</a>' for s in sources[:3])
    note = _e(LABEL_NOTE[label])
    if label in (Label.LEAK_CLAIM, Label.COMMUNITY_CLAIM, Label.SINGLE_SOURCE):
        note = f"<i>{note}</i>"
    lines = [
        f"{BADGE[label]} <b>{_e(LABEL_TEXT[label])}</b>  ·  {_e(tr_upper(category))}",
        "",
        f"<b>{_e(content.title_tr)}</b>",
        "",
        _e(content.summary_tr),
        "",
        f"<b>Kaynak:</b> {src_links}",
        f"<b>Doğrulama:</b> {note}",
        "",
        f"<i>{_e(settings.brand_name)} · {_e(format_local(now, settings.display_utc_offset_hours))}</i>",
        "#GTA6 #GTAVI",
    ]
    return "\n".join(lines)


# ---- Limitler -----------------------------------------------------------------------------

def posts_in_last_24h(history: dict, now: datetime) -> int:
    cutoff = now - timedelta(hours=24)
    n = 0
    for p in history.get("posts", []):
        if p.get("publish_status") in ACTIVE_STATUSES:
            t = parse_iso(p.get("published_at") or p.get("created_at"))
            if t and t >= cutoff:
                n += 1
    return n


def minutes_since_last_post(history: dict, now: datetime) -> float | None:
    times = [parse_iso(p.get("published_at") or p.get("created_at")) for p in history.get("posts", [])
             if p.get("publish_status") in ACTIVE_STATUSES]
    times = [t for t in times if t]
    if not times:
        return None
    return (now - max(times)).total_seconds() / 60


def already_handled(history: dict, content_id: str) -> bool:
    return any(p.get("content_id") == content_id and p.get("publish_status") in ACTIVE_STATUSES
               for p in history.get("posts", []))


# ---- Yayın --------------------------------------------------------------------------------

def publish_post(*, post: dict, text: str, history: dict, chat_id: str, telegram: TelegramClient,
                 persist: Callable[[], None], now: datetime) -> str:
    """Tek gönderiyi idempotent yayınlar. Dönen değer: yeni publish_status."""
    if not post.get("source_urls"):
        post["publish_status"] = "REJECTED"
        post["publish_error"] = "Kaynak URL'si yok"
        return "REJECTED"
    if already_handled(history, post["content_id"]):
        return "SKIPPED_DUPLICATE"
    post.update({"publish_status": "SENDING", "created_at": iso(now), "chat_id": str(chat_id)})
    history.setdefault("posts", []).append(post)
    persist()  # gönderimden önce kalıcı kayıt
    try:
        result = telegram.send_message(chat_id, text)
    except TelegramUncertainError as exc:
        post["publish_status"] = "UNCERTAIN"
        post["publish_error"] = exc.error_class.value
        log.warning("Gönderim durumu belirsiz (%s); haber yeniden gönderilmeyecek", exc.error_class.value)
    except TelegramError as exc:
        post["publish_status"] = "FAILED"
        post["publish_error"] = exc.error_class.value
        log.warning("Gönderim başarısız: %s", exc.error_class.value)
    else:
        post["publish_status"] = "PUBLISHED"
        post["published_at"] = iso(now)
        post["message_id"] = (result or {}).get("message_id")
        chat = (result or {}).get("chat") or {}
        if chat.get("id") is not None:
            post["chat_id"] = str(chat["id"])
    persist()
    return post["publish_status"]


# ---- Yönetici özeti ve alarmlar --------------------------------------------------------------

def due_digest_key(settings: Settings, state: dict, now: datetime) -> str | None:
    """06:00 ve 18:00 UTC civarı (± digest_window_minutes) için tek özet anahtarı döndürür;
    aynı pencerede daha önce gönderildiyse None."""
    sent = set(state.get("digests_sent", []))
    for day_shift in (-1, 0, 1):
        day = (now + timedelta(days=day_shift)).date()
        for h in settings.digest_hours_utc:
            target = datetime(day.year, day.month, day.day, h, tzinfo=timezone.utc)
            if abs((now - target).total_seconds()) <= settings.digest_window_minutes * 60:
                key = f"{day.isoformat()}T{h:02d}"
                return None if key in sent else key
    return None


def mark_digest_sent(state: dict, key: str) -> None:
    sent = state.setdefault("digests_sent", [])
    sent.append(key)
    del sent[:-20]


def should_alert(state: dict, alert_key: str, settings: Settings, now: datetime) -> bool:
    last = parse_iso(state.get("alerts_last_sent", {}).get(alert_key))
    return last is None or now - last >= timedelta(hours=settings.alert_dedup_hours)


def mark_alert(state: dict, alert_key: str, now: datetime) -> None:
    state.setdefault("alerts_last_sent", {})[alert_key] = iso(now)


def render_digest(summary: dict, history: dict, insights: dict, settings: Settings, now: datetime) -> str:
    published = posts_in_last_24h(history, now)
    uncertain = sum(1 for p in history.get("posts", []) if p.get("publish_status") == "UNCERTAIN")
    held = sum(1 for p in history.get("posts", []) if p.get("publish_status") == "REVIEW_HELD"
               and (parse_iso(p.get("created_at")) or now) >= now - timedelta(hours=24))
    state_line = "DURAKLATILDI (paused=true)" if settings.paused else "Çalışıyor"
    lines = [
        f"<b>{_e(settings.brand_name)} · Yönetici Özeti</b>",
        f"<i>{_e(format_local(now, settings.display_utc_offset_hours))}</i>",
        "",
        f"Durum: <b>{_e(state_line)}</b>",
        f"Son 24 saatte yayın: <b>{published}</b> / {settings.max_daily_posts}",
        f"İncelemeye takılan (yayınlanmadı): {held}",
        f"Belirsiz gönderim (elle kontrol): {uncertain}",
        f"Son çalışma: kaynak {summary.get('sources_ok', 0)}/{summary.get('sources_checked', 0)}, "
        f"yeni öğe {summary.get('new_items', 0)}, Gemini {summary.get('gemini_calls', 0)} çağrı",
        f"Etkileşim analizi: {_e(str(insights.get('status', 'YETERSİZ VERİ')))}",
        "Görüntülenme/iletilme: Bot API ile ölçülemiyor (unavailable)",
    ]
    if summary.get("error_classes"):
        lines.append(f"Hatalar: {_e(', '.join(sorted(set(summary['error_classes']))))}")
    return "\n".join(lines)


def render_alert(error_class: str, detail: str, settings: Settings, now: datetime) -> str:
    return (f"⚠️ <b>{_e(settings.brand_name)} · ACİL UYARI</b>\n"
            f"Sınıf: <code>{_e(error_class)}</code>\n{_e(detail)}\n"
            f"<i>{_e(format_local(now, settings.display_utc_offset_hours))} · aynı uyarı "
            f"{settings.alert_dedup_hours} saat tekrarlanmaz</i>")


def send_admin(telegram: TelegramClient | None, admin_chat_id: str | None, text: str) -> bool:
    if not telegram or not admin_chat_id:
        log.info("ADMIN_CHAT_ID tanımlı değil; yönetici mesajı yalnızca loglandı")
        return False
    try:
        telegram.send_message(admin_chat_id, text, disable_preview=True)
        return True
    except TelegramError as exc:
        log.warning("Yönetici mesajı gönderilemedi: %s", exc.error_class.value)
        return False


__all__ = ["render_post", "publish_post", "posts_in_last_24h", "minutes_since_last_post", "due_digest_key",
           "mark_digest_sent", "should_alert", "mark_alert", "render_digest", "render_alert", "send_admin",
           "ErrorClass"]
