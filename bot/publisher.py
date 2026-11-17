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
from typing import TYPE_CHECKING, Any, Callable

from . import ErrorClass, iso, parse_iso
from .config import Settings
from .gemini import GeneratedContent
from .labels import LABEL_NOTE, LABEL_TEXT, Label
from .telegram_client import MAX_MESSAGE_CHARS, TelegramError, TelegramUncertainError
from .textutil import tr_upper, truncate

if TYPE_CHECKING:
    from .telegram_client import MessageSender

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
    "COMMUNITY_RUMOR": "İddia",
    "OTHER": "Gündem",
}

ACTIVE_STATUSES = {"SENDING", "PUBLISHED", "UNCERTAIN"}

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
             "Kasım", "Aralık"]


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def format_local(dt: datetime, offset_hours: int) -> str:
    """Tarihi Türkçe ay adlarıyla yerel saat diliminde biçimlendirir (ör. 16 Kasım 2026, 21:40 TSİ)."""
    local = dt.astimezone(timezone(timedelta(hours=offset_hours)))
    suffix = "TSİ" if offset_hours == 3 else f"UTC{offset_hours:+d}"
    return f"{local.day} {TR_MONTHS[local.month - 1]} {local.year}, {local:%H:%M} {suffix}"


MAX_SOURCE_NAME_CHARS = 40
MAX_SOURCE_URL_CHARS = 600


def _source_links(sources: list[dict[str, str]]) -> str:
    """En fazla 3 kaynak; aşırı uzun URL'ler atlanır, adlar kırpılır."""
    links = [f'<a href="{_e(s["url"])}">{_e(truncate(s["name"], MAX_SOURCE_NAME_CHARS))}</a>'
             for s in sources if len(s.get("url", "")) <= MAX_SOURCE_URL_CHARS][:3]
    return " · ".join(links)


def verification_note(label: Label, sources: list[dict[str, str]], independent_count: int | None = None) -> str:
    """Somut doğrulama notu: resmî kaynağın adı veya bağımsız yayın sayısı."""
    if label == Label.OFFICIAL and sources:
        return f"{sources[0]['name']} üzerinde doğrudan duyuruldu (resmî alan adı, bağlantı doğrulandı)."
    if label == Label.MULTI_SOURCE:
        n = independent_count or len(sources)
        return f"{n} bağımsız yayın organı aynı gelişmeyi aktarıyor; resmî doğrulama yok."
    return LABEL_NOTE[label]


def render_post(content: GeneratedContent, label: Label, sources: list[dict[str, str]], settings: Settings,
                now: datetime, *, independent_count: int | None = None, site_link: str | None = None,
                sponsor: tuple[str, str, str] | None = None) -> str:
    """Profesyonel bülten düzeni: tek rozet, etiket satırı, kalın başlık, özet, kaynak bloğu, imza.

    Telegram HTML parse_mode yalnızca sınırlı etiket destekler (b, i, a, code, blockquote...);
    tüm dinamik metin html.escape ile kaçırılır. Sonuç hiçbir koşulda 4096 karakteri aşmaz:
    gerekirse önce kaynak sayısı, sonra özet kısaltılır.
    """
    category = CATEGORY_TR.get(content.category, "Gündem")
    redundant = ((label == Label.OFFICIAL and content.category == "OFFICIAL_ANNOUNCEMENT")
                 or (label in (Label.LEAK_CLAIM, Label.COMMUNITY_CLAIM) and content.category == "COMMUNITY_RUMOR"))
    category_part = "" if redundant else f"  ·  {_e(tr_upper(category))}"
    note = _e(verification_note(label, sources, independent_count))
    if label in (Label.LEAK_CLAIM, Label.COMMUNITY_CLAIM, Label.SINGLE_SOURCE):
        note = f"<i>{note}</i>"

    extra: list[str] = []
    if site_link and site_link.startswith("https://"):
        extra.append(f'🗺 <a href="{_e(site_link)}">Leonida haritasında ve sitede oku</a>')
    if sponsor and sponsor[2].startswith("https://"):
        name, tagline, url = sponsor
        extra.append(f'<i>Sponsor:</i> <a href="{_e(url)}">{_e(name)}</a>' + (f" — {_e(tagline)}" if tagline else ""))

    def build(summary: str, srcs: list[dict[str, str]]) -> str:
        return "\n".join([
            f"{BADGE[label]} <b>{_e(LABEL_TEXT[label])}</b>{category_part}",
            "",
            f"<b>{_e(content.title_tr)}</b>",
            "",
            _e(summary),
            "",
            f"<b>Kaynak:</b> {_source_links(srcs)}",
            f"<b>Doğrulama:</b> {note}",
            *([""] + extra if extra else []),
            "",
            f"<i>{_e(settings.brand_name)} · {_e(format_local(now, settings.display_utc_offset_hours))}</i>",
            "#GTA6 #GTAVI",
        ])

    text = build(content.summary_tr, sources)
    srcs = list(sources)
    while len(text) > MAX_MESSAGE_CHARS and len(srcs) > 1:
        srcs.pop()
        text = build(content.summary_tr, srcs)
    if len(text) > MAX_MESSAGE_CHARS:
        excess = len(text) - MAX_MESSAGE_CHARS
        text = build(truncate(content.summary_tr, max(40, len(content.summary_tr) - excess - 10)), srcs)
    return text[:MAX_MESSAGE_CHARS]


# ---- Limitler -----------------------------------------------------------------------------

def _post_time(p: dict[str, Any]) -> datetime | None:
    return parse_iso(p.get("published_at") or p.get("created_at"))


def local_tz(settings: Settings) -> timezone:
    """Yerel saat dilimi (varsayılan TRT, UTC+3; Türkiye 2016'dan beri yaz saati uygulamıyor)."""
    return timezone(timedelta(hours=settings.display_utc_offset_hours))


def posts_in_last_24h(history: dict[str, Any], now: datetime) -> int:
    """Kayan 24 saatlik pencerede etkin (gönderilmiş/belirsiz) gönderi sayısı."""
    cutoff = now - timedelta(hours=24)
    return sum(1 for p in history.get("posts", []) if p.get("publish_status") in ACTIVE_STATUSES
               and (t := _post_time(p)) is not None and t >= cutoff)


def posts_today(history: dict[str, Any], now: datetime, settings: Settings) -> int:
    """Günlük limit sayacı. ``calendar_day_local``: yerel (TRT) takvim günü — sayaç yerel
    gece yarısı sıfırlanır, UTC gece yarısı (TRT 03:00) etkilemez. ``rolling_24h``: kayan pencere."""
    if settings.daily_limit_mode == "rolling_24h":
        return posts_in_last_24h(history, now)
    tz = local_tz(settings)
    today = now.astimezone(tz).date()
    return sum(1 for p in history.get("posts", []) if p.get("publish_status") in ACTIVE_STATUSES
               and (t := _post_time(p)) is not None and t.astimezone(tz).date() == today)


def minutes_since_last_post(history: dict[str, Any], now: datetime) -> float | None:
    """Son etkin gönderiden bu yana geçen dakika (yoksa None)."""
    times = [t for p in history.get("posts", []) if p.get("publish_status") in ACTIVE_STATUSES
             and (t := _post_time(p)) is not None]
    if not times:
        return None
    return (now - max(times)).total_seconds() / 60


def already_handled(history: dict, content_id: str) -> bool:
    """Bu içerik kimliği daha önce gönderildi/gönderiliyor/belirsiz mi?"""
    return any(p.get("content_id") == content_id and p.get("publish_status") in ACTIVE_STATUSES
               for p in history.get("posts", []))


# ---- Yayın --------------------------------------------------------------------------------

def publish_post(*, post: dict, text: str, history: dict, chat_id: str, telegram: "MessageSender",
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
        result = telegram.send_message(chat_id, text, preview_url=post["source_urls"][0])
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
    """Özet anahtarını kaydeder (son 20 anahtar tutulur)."""
    sent = state.setdefault("digests_sent", [])
    sent.append(key)
    del sent[:-20]


def should_alert(state: dict, alert_key: str, settings: Settings, now: datetime) -> bool:
    """Aynı uyarı anahtarı son alert_dedup_hours içinde gönderilmediyse True."""
    last = parse_iso(state.get("alerts_last_sent", {}).get(alert_key))
    return last is None or now - last >= timedelta(hours=settings.alert_dedup_hours)


def mark_alert(state: dict, alert_key: str, now: datetime) -> None:
    """Uyarı anahtarının son gönderim zamanını kaydeder."""
    state.setdefault("alerts_last_sent", {})[alert_key] = iso(now)


def _recent_published(history: dict[str, Any], now: datetime, settings: Settings, limit: int = 3) -> list[str]:
    """Bugün yayınlanan son haberler: "• ETİKET — başlık" (elle kontrol için)."""
    tz = local_tz(settings)
    today = now.astimezone(tz).date()
    rows = [p for p in history.get("posts", []) if p.get("publish_status") == "PUBLISHED"
            and (t := _post_time(p)) is not None and t.astimezone(tz).date() == today]
    rows.sort(key=lambda p: p.get("published_at") or "", reverse=True)
    return [f"• {_e(str(p.get('label_text', '')))} — {_e(truncate(str(p.get('title_tr') or '(başlıksız)'), 90))}"
            for p in rows[:limit]]


def _run_line(summary: dict[str, Any]) -> str:
    if not summary.get("sources_checked"):
        reason = "duraklatıldı" if summary.get("paused") else "güvenli mod" if summary.get("safe_mode") else \
            "etkin kaynak yok"
        return f"Son çalışma: toplama yapılmadı ({reason})"
    return (f"Son çalışma: kaynak {summary.get('sources_ok', 0)}/{summary['sources_checked']}, "
            f"yeni öğe {summary.get('new_items', 0)}, Gemini {summary.get('gemini_calls', 0)} çağrı")


def render_digest(summary: dict[str, Any], history: dict[str, Any], insights: dict[str, Any], settings: Settings,
                  now: datetime) -> str:
    """Günde iki kez gönderilen yönetici özeti metni (Telegram HTML)."""
    published = posts_today(history, now, settings)
    uncertain = sum(1 for p in history.get("posts", []) if p.get("publish_status") == "UNCERTAIN")
    held = sum(1 for p in history.get("posts", []) if p.get("publish_status") == "REVIEW_HELD"
               and (parse_iso(p.get("created_at")) or now) >= now - timedelta(hours=24))
    state_line = "DURAKLATILDI (paused=true)" if settings.paused else "Çalışıyor"
    lines = [
        f"<b>{_e(settings.brand_name)} · Yönetici Özeti</b>",
        f"<i>{_e(format_local(now, settings.display_utc_offset_hours))}</i>",
        "",
        f"Durum: <b>{_e(state_line)}</b>",
        f"Bugünkü yayın: <b>{published}</b> / {settings.max_daily_posts}",
        f"İncelemeye takılan (yayınlanmadı): {held}",
        f"Belirsiz gönderim (elle kontrol): {uncertain}",
        _run_line(summary),
        f"Etkileşim analizi: {_e(str(insights.get('status', 'YETERSİZ VERİ')))}",
        "Görüntülenme/iletilme: Bot API ile ölçülemiyor (unavailable)",
    ]
    if summary.get("error_classes"):
        lines.append(f"Hatalar: {_e(', '.join(sorted(set(summary['error_classes']))))}")
    recent = _recent_published(history, now, settings)
    if recent:
        lines += ["", "<b>Bugün yayınlananlar</b>", *recent]
    return "\n".join(lines)


def render_alert(error_class: str, detail: str, settings: Settings, now: datetime) -> str:
    """Acil uyarı metni (Telegram HTML)."""
    return (f"⚠️ <b>{_e(settings.brand_name)} · ACİL UYARI</b>\n"
            f"Sınıf: <code>{_e(error_class)}</code>\n{_e(detail)}\n"
            f"<i>{_e(format_local(now, settings.display_utc_offset_hours))} · aynı uyarı "
            f"{settings.alert_dedup_hours} saat tekrarlanmaz</i>")


def send_admin(telegram: "MessageSender | None", admin_chat_id: str | None, text: str) -> bool:
    """Yönetici sohbetine mesaj gönderir; tanımlı değilse yalnızca loglar."""
    if not telegram or not admin_chat_id:
        log.info("ADMIN_CHAT_ID tanımlı değil; yönetici mesajı yalnızca loglandı")
        return False
    try:
        telegram.send_message(admin_chat_id, text, disable_preview=True)
        return True
    except TelegramError as exc:
        log.warning("Yönetici mesajı gönderilemedi: %s", exc.error_class.value)
        return False


__all__ = ["render_post", "publish_post", "posts_in_last_24h", "posts_today", "minutes_since_last_post", "due_digest_key",
           "mark_digest_sent", "should_alert", "mark_alert", "render_digest", "render_alert", "send_admin",
           "ErrorClass"]
