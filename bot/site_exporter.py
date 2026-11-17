"""Bot verisinden statik haber sitesi için güvenli ``docs/data/feed.json`` (+ ``feed.js``) üretir.

Güvenlik sözleşmesi:

* Yalnızca ``PUBLISHED`` durumundaki gönderiler dışa aktarılır (incelemeye takılan, reddedilen,
  belirsiz gönderimler sitede görünmez).
* **Beyaz liste** yaklaşımı: çıktıya yalnızca açıkça seçilen alanlar girer. ``chat_id``,
  ``content_hashes``, ``publish_error``, kaynak orijinal başlıkları, iç durum alanları ve hiçbir
  ortam değişkeni dışa aktarılmaz.
* Tüm metinler HTML'den arındırılır (etiket, varlık, görünmez karakter), uzunluk sınırlanır.
  Sitede veriler yalnızca ``textContent`` ile basılır (ikinci savunma katmanı).
* Bağlantılar yalnızca ``https://`` ve canonical; ``javascript:``/``data:``/``http:`` atılır.
* Telegram bağlantısı yalnızca herkese açık kanal kullanıcı adı ayarlıysa
  (``public_channel_username``) ``https://t.me/<ad>/<message_id>`` olarak üretilir; sayısal
  chat_id asla kullanılmaz.
* Görüntülenme/iletilme sayısı Bot API'de olmadığından dışa aktarılmaz; reaksiyon toplamı
  yalnızca ölçülmüşse verilir.
* ``feed.js``: dosyayı doğrudan diskten açarken (file://) ``fetch`` engellendiği için aynı veri
  ``window.__GTA6_FEED__`` olarak da yazılır; ``<`` karakterleri ``\\u003c`` olarak kaçırılır
  (``</script>`` kırılması olmaz).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import iso, parse_iso
from .collector import canonicalize_url
from .config import Settings, Source
from .labels import LABEL_TEXT, Label
from .storage import write_if_changed
from .textutil import normalize_text, strip_html, truncate

FEED_SCHEMA_VERSION = 1
MAX_TITLE = 160
MAX_SUMMARY = 700
MAX_REASON = 300
MAX_SOURCES = 5
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")

CATEGORY_TR: dict[str, str] = {
    "OFFICIAL_ANNOUNCEMENT": "Duyuru", "TRAILER_MEDIA": "Fragman", "GAMEPLAY_TECH": "Oynanış",
    "RELEASE_PLATFORMS": "Çıkış/Platform", "INDUSTRY_BUSINESS": "Analiz", "COMMUNITY_RUMOR": "Sızıntı",
    "OTHER": "Gündem",
}
TRUST_GROUP: dict[str, str] = {
    "OFFICIAL": "official", "MULTI_SOURCE": "multi", "SINGLE_SOURCE": "single",
    "LEAK_CLAIM": "claim", "COMMUNITY_CLAIM": "claim",
}

# ---- Leonida haritası: haber → konum eşlemesi ------------------------------------------------
LocationId = Literal["vice_city", "leonida_keys", "grassrivers", "port_gellhorn", "mount_kalaga"]
REGION_NAME: dict[str, str] = {
    "vice_city": "Vice City", "leonida_keys": "Leonida Keys", "grassrivers": "Grassrivers",
    "port_gellhorn": "Port Gellhorn & Ambrosia", "mount_kalaga": "Mount Kalaga · Genel Merkez",
}
_CATEGORY_REGION: dict[str, str] = {
    "TRAILER_MEDIA": "vice_city", "GAMEPLAY_TECH": "leonida_keys", "COMMUNITY_RUMOR": "grassrivers",
    "RELEASE_PLATFORMS": "mount_kalaga", "OFFICIAL_ANNOUNCEMENT": "mount_kalaga",
    "INDUSTRY_BUSINESS": "mount_kalaga", "OTHER": "vice_city",
}
# Başlık/özette geçen terimler (normalize_text sonrası, Türkçe + İngilizce). Eşleşme kategori varsayılanını ezer.
_REGION_TERMS: dict[str, tuple[str, ...]] = {
    "vice_city": ("vice city", "ocean drive", "fragman", "trailer", "ekran goruntu", "screenshot", "neon",
                  "plaj", "beach", "radyo", "radio", "soundtrack", "muzik"),
    "leonida_keys": ("leonida keys", "oynanis", "gameplay", "arac", "vehicle", "araba", "tekne", "boat",
                     "fizik", "physics", "surus", "driving", "fotograf modu", "photo mode", "erisilebilirlik",
                     "accessibility", "silah", "weapon"),
    "grassrivers": ("grassrivers", "bataklik", "swamp", "harita", "map", "timsah", "alligator", "vahsi",
                    "wildlife", "ada", "island", "kesif", "exploration", "dunya boyutu", "world size"),
    "port_gellhorn": ("port gellhorn", "ambrosia", "jason", "lucia", "hikaye", "story", "karakter", "character",
                      "gorev", "mission", "seslendir", "voice actor", "oyuncu kadro", "cast"),
    "mount_kalaga": ("mount kalaga", "cikis tarihi", "release date", "on yukleme", "preload", "pre-load",
                     "on siparis", "pre-order", "preorder", "fiyat", "price", "ps5", "playstation", "xbox",
                     "pc", "platform", "gb", "boyut", "file size", "take two", "take-two", "gelir", "earnings",
                     "inceleme", "review", "erteleme", "delay"),
}


def classify_location(title: str, summary: str, category: str) -> str:
    """Haberi beş Leonida konumundan birine bağlar (deterministik).

    Başlıktaki eşleşme 2, özetteki 1 puan; en yüksek puanlı konum seçilir. Eşitlikte veya hiç eşleşme
    yoksa kategori varsayılanı kazanır. Yapay zekâ kullanılmaz."""
    default = _CATEGORY_REGION.get(category, "vice_city")
    t, sm = f" {normalize_text(title)} ", f" {normalize_text(summary)} "
    scores = {loc: 0 for loc in REGION_NAME}
    for loc, terms in _REGION_TERMS.items():
        for term in terms:
            word = normalize_text(term)
            if not word:
                continue
            # 5+ harfli terimlerde Türkçe ekleri yakalamak için kelime başı eşleşmesi (radyo → radyolarını)
            needle = f" {word}" if len(word) >= 5 else f" {word} "
            if needle in t:
                scores[loc] += 2
            elif needle in sm:
                scores[loc] += 1
    scores[default] += 1  # kategori eşitliği bozar
    return max(scores, key=lambda k: (scores[k], k == default))


LabelName = Literal["OFFICIAL", "MULTI_SOURCE", "SINGLE_SOURCE", "LEAK_CLAIM", "COMMUNITY_CLAIM"]


class FeedSource(BaseModel):
    """Sitede gösterilen tek kaynak bağlantısı."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)
    url: str = Field(pattern=r"^https://[^\s<>\"']+$", max_length=600)


class FeedItem(BaseModel):
    """Sitedeki tek haber kartı."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{4,64}$")
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    summary: str = Field(max_length=MAX_SUMMARY)
    label: LabelName
    label_text: str
    trust_group: Literal["official", "multi", "single", "claim"]
    category: str
    category_tr: str
    title_style: str
    published_at: str
    why_this_label: str = Field(max_length=MAX_REASON)
    source_strength: int = Field(ge=0, le=100)
    editorial_priority: int = Field(ge=0, le=100)
    independent_origins: int = Field(ge=0)
    sources: list[FeedSource] = Field(min_length=1, max_length=MAX_SOURCES)
    telegram_url: str | None = Field(default=None, pattern=r"^https://t\.me/[A-Za-z0-9_]{5,32}/\d+$")
    reactions_total: int | None = None
    # Opsiyonel (şema v1 ile geriye uyumlu): Leonida haritası konumu
    location_id: LocationId | None = None
    region: str | None = Field(default=None, max_length=60)
    # Opsiyonel: kaynağın kendi paylaşım görseli (hotlink; sitede kaynağa atıfla gösterilir)
    image: str | None = Field(default=None, pattern=r"^https://[^\s<>\"'\\]+$", max_length=600)
    image_credit: str | None = Field(default=None, max_length=80)
    # Opsiyonel (global sürüm): aynı haberin İngilizce başlığı ve özeti; yoksa alan hiç yazılmaz
    title_en: str | None = Field(default=None, max_length=MAX_TITLE)
    summary_en: str | None = Field(default=None, max_length=MAX_SUMMARY)


class FeedSourceStatus(BaseModel):
    """Kaynak nabzı: tek kaynağın son çalışmadaki durumu (iç hata ayrıntısı içermez)."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_]{2,40}$")
    name: str = Field(max_length=80)
    trust_class: Literal["OFFICIAL", "ESTABLISHED_MEDIA", "COMMUNITY", "UNKNOWN"]
    state: Literal["ok", "empty", "error", "pending"]
    entries: int = Field(ge=0)
    relevant: int = Field(ge=0)
    checked_at: str | None = None


class FeedStatus(BaseModel):
    """Site üstündeki canlı sistem durum bandı."""
    model_config = ConfigDict(extra="forbid")
    generated_at: str
    last_run_at: str | None
    last_successful_fetch_at: str | None
    active_sources: int
    sources_ok_last_run: int
    verified_total: int
    paused: bool
    measurement_note: str
    sources: list[FeedSourceStatus] = Field(default_factory=list)


class Feed(BaseModel):
    """docs/data/feed.json kök şeması."""
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    demo: bool
    brand: str
    status: FeedStatus
    hero_id: str | None
    featured_ids: list[str] = Field(default_factory=list, max_length=2)
    items: list[FeedItem]


def clean_text(value: Any, limit: int) -> str:
    """HTML/görünmez karakterleri temizler ve sınırlar. Metin olmayan değer → boş dize."""
    if not isinstance(value, str):
        return ""
    # Çift kodlanmış HTML temizlikten sonra '<img …>' metnine dönüşebilir: açılı parantezleri nötrle.
    return truncate(strip_html(value).replace("<", "‹").replace(">", "›"), limit)


def safe_url(value: Any) -> str | None:
    """Yalnızca https ve canonical URL; aksi halde None."""
    if not isinstance(value, str) or not value.strip().lower().startswith("https://"):
        return None
    url = canonicalize_url(value)
    if not url or any(ch in url for ch in "<>\"' \n\r\t"):
        return None
    return url


def telegram_url(username: str, message_id: Any) -> str | None:
    """Herkese açık kanal için mesaj bağlantısı; kullanıcı adı yoksa/geçersizse None."""
    name = (username or "").lstrip("@")
    if not _USERNAME_RE.match(name) or not isinstance(message_id, int) or message_id <= 0:
        return None
    return f"https://t.me/{name}/{message_id}"


def _sources(post: dict[str, Any], names: dict[str, str]) -> list[FeedSource]:
    out: list[FeedSource] = []
    for raw in post.get("source_urls", [])[:MAX_SOURCES]:
        url = safe_url(raw)
        if not url or any(s.url == url for s in out):
            continue
        host = url.split("/")[2]
        out.append(FeedSource(name=clean_text(names.get(url) or host, 80) or host, url=url))
    return out


def _reactions(post: dict[str, Any]) -> int | None:
    metrics = post.get("metrics") or {}
    val = metrics.get("reactions_24h")
    if isinstance(val, int) and not metrics.get("reactions_24h_inferred_zero"):
        return val
    snaps = metrics.get("reaction_snapshots") or []
    last = snaps[-1].get("total") if snaps and isinstance(snaps[-1], dict) else None
    return last if isinstance(last, int) else None


def _english_fields(post: dict[str, Any]) -> dict[str, str]:
    """İngilizce alanlar yalnızca ikisi de doluysa eklenir (feed.json eski okuyucularla uyumlu kalır)."""
    title = clean_text(post.get("title_en"), MAX_TITLE)
    summary = clean_text(post.get("summary_en"), MAX_SUMMARY)
    return {"title_en": title, "summary_en": summary} if title and summary else {}


def build_item(post: dict[str, Any], settings: Settings, names: dict[str, str]) -> FeedItem | None:
    """Tek geçmiş kaydını güvenli site öğesine çevirir; uygun değilse None."""
    if post.get("publish_status") != "PUBLISHED":
        return None
    label = post.get("label")
    if label not in TRUST_GROUP:
        return None
    title = clean_text(post.get("title_tr"), MAX_TITLE)
    published = parse_iso(post.get("published_at"))
    sources = _sources(post, names)
    item_id = re.sub(r"[^A-Za-z0-9_-]", "", str(post.get("content_id", "")))[:64]
    if not title or not published or not sources or len(item_id) < 4:
        return None
    category = post.get("category") if post.get("category") in CATEGORY_TR else "OTHER"
    summary = clean_text(post.get("summary_tr"), MAX_SUMMARY)
    location = classify_location(title, summary, str(category))
    return FeedItem(
        id=item_id, title=title, summary=summary,
        label=label, label_text=LABEL_TEXT[Label(label)], trust_group=TRUST_GROUP[label],
        category=str(category), category_tr=CATEGORY_TR[str(category)],
        title_style=clean_text(post.get("title_style"), 20) or "FACTUAL",
        published_at=iso(published) or "",
        why_this_label=clean_text(post.get("why_this_label") or post.get("publish_reason"), MAX_REASON),
        source_strength=max(0, min(100, int(post.get("source_strength") or 0))),
        editorial_priority=max(0, min(100, int(post.get("editorial_priority") or 0))),
        independent_origins=len(post.get("independent_origins") or []),
        sources=sources,
        telegram_url=telegram_url(settings.public_channel_username, post.get("message_id")),
        reactions_total=_reactions(post),
        location_id=location,
        region=REGION_NAME[location],
        **_image_fields(post),
        **_english_fields(post),
    )


def _image_fields(post: dict[str, Any]) -> dict[str, str]:
    """Kayıttaki görseli (bot tarafında alan adı allowlist'inden geçmiş) yeniden biçim denetiminden geçirir."""
    url = post.get("image_url")
    if not isinstance(url, str) or not re.fullmatch(r"https://[^\s<>\"'\\]{4,592}", url):
        return {}
    credit = clean_text(post.get("image_credit"), 80)
    return {"image": url, "image_credit": credit} if credit else {"image": url}


def pick_hero(items: list[FeedItem], now: datetime, fresh_hours: int = 48) -> str | None:
    """Manşet: son ``fresh_hours`` içindeki en yeni RESMÎ AÇIKLAMA; yoksa en yüksek öncelikli
    doğrulanmış (resmî/çoklu) haber; o da yoksa en yüksek öncelikli haber. İddialar manşet olmaz
    (başka haber varsa)."""
    if not items:
        return None
    recent = [i for i in items if (t := parse_iso(i.published_at)) and (now - t).total_seconds() <= fresh_hours * 3600]
    pool = recent or items
    official = [i for i in pool if i.label == "OFFICIAL"]
    if official:
        return max(official, key=lambda i: i.published_at).id
    verified = [i for i in pool if i.label in ("OFFICIAL", "MULTI_SOURCE")]
    non_claim = [i for i in pool if i.trust_group != "claim"]
    best = max(verified or non_claim or pool, key=lambda i: (i.editorial_priority, i.published_at))
    return best.id


_FEATURE_RANK: dict[str, int] = {"official": 0, "multi": 0, "single": 1, "claim": 2}


def pick_featured(items: list[FeedItem], hero_id: str | None, now: datetime, fresh_hours: int = 48) -> list[str]:
    """Vitrindeki iki büyük kart: manşet dışındaki son ``fresh_hours`` saatin haberlerinden önce
    doğrulanmışlar (resmî/çoklu), sonra tek kaynak; iddialar en sona. Eşitlikte öncelik ve yenilik."""
    recent = [i for i in items if i.id != hero_id and (t := parse_iso(i.published_at))
              and (now - t).total_seconds() <= fresh_hours * 3600]
    recent.sort(key=lambda i: (_FEATURE_RANK[i.trust_group], -i.editorial_priority, _neg_time(i.published_at)))
    return [i.id for i in recent[:2]]


def _neg_time(value: str) -> float:
    t = parse_iso(value)
    return -t.timestamp() if t else 0.0


def source_pulse(sources: list[Source], status_map: dict[str, Any]) -> list[FeedSourceStatus]:
    """Etkin kaynakların son çalışma durumu. Hata ayrıntısı/HTTP kodu dışa aktarılmaz; yalnızca
    ok / empty (yanıt verdi ama liste boş) / error / pending (henüz denenmedi)."""
    out: list[FeedSourceStatus] = []
    for s in sources:
        if not s.enabled or not s.feed_url:
            continue
        st = status_map.get(s.id)
        st = st if isinstance(st, dict) else {}
        raw_entries, raw_relevant = st.get("entries"), st.get("relevant")
        entries = raw_entries if isinstance(raw_entries, int) else 0
        relevant = raw_relevant if isinstance(raw_relevant, int) else 0
        if not st:
            state = "pending"
        elif st.get("ok") is not True:
            state = "error"
        elif st.get("warning") or entries == 0:
            state = "empty"
        else:
            state = "ok"
        checked = st.get("checked_at") if isinstance(st.get("checked_at"), str) else None
        out.append(FeedSourceStatus(id=s.id, name=clean_text(s.name, 80), trust_class=s.trust_class, state=state,
                                    entries=max(0, entries), relevant=max(0, relevant), checked_at=checked))
    return out


def build_feed(history: dict[str, Any], state: dict[str, Any], settings: Settings, sources: list[Source],
               now: datetime, *, demo: bool = False) -> Feed:
    """history/state'ten doğrulanmış site beslemesini oluşturur."""
    names = _source_names(history)
    items = [it for it in (build_item(p, settings, names) for p in history.get("posts", [])
                           if isinstance(p, dict)) if it is not None]
    items.sort(key=lambda i: i.published_at, reverse=True)
    items = items[: settings.site_max_items]
    raw_status = state.get("source_status")
    status_map: dict[str, Any] = raw_status if isinstance(raw_status, dict) else {}
    status = FeedStatus(
        generated_at=iso(now) or "",
        last_run_at=state.get("last_run_at") if isinstance(state.get("last_run_at"), str) else None,
        last_successful_fetch_at=state.get("last_successful_fetch_at")
        if isinstance(state.get("last_successful_fetch_at"), str) else None,
        active_sources=sum(1 for s in sources if s.enabled and s.feed_url),
        sources_ok_last_run=sum(1 for v in status_map.values() if isinstance(v, dict) and v.get("ok") is True),
        verified_total=sum(1 for p in history.get("posts", []) if isinstance(p, dict)
                           and p.get("publish_status") == "PUBLISHED"),
        paused=settings.paused,
        measurement_note="Görüntülenme/iletilme sayıları Telegram Bot API ile ölçülemez; gösterilmez.",
        sources=source_pulse(sources, status_map),
    )
    hero = pick_hero(items, now)
    return Feed(schema_version=FEED_SCHEMA_VERSION, demo=demo, brand=clean_text(settings.brand_name, 60),
                status=status, hero_id=hero, featured_ids=pick_featured(items, hero, now), items=items)


def _source_names(history: dict[str, Any]) -> dict[str, str]:
    """Kayıtlardaki ``source_names`` (url → yayın adı) eşlemesi."""
    names: dict[str, str] = {}
    for p in history.get("posts", []):
        if isinstance(p, dict) and isinstance(p.get("source_names"), dict):
            for url, name in p["source_names"].items():
                if isinstance(url, str) and isinstance(name, str):
                    names[canonicalize_url(url)] = name
    return names


def feed_js(feed_json: str, var_name: str = "__GTA6_FEED__") -> str:
    """``file://`` ile açılış için JS sarmalayıcı; ``<``, ``>``, ``&`` ve U+2028/2029 kaçırılır."""
    if not re.fullmatch(r"__[A-Z0-9_]+__", var_name):
        raise ValueError("geçersiz değişken adı")
    safe = (feed_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return f"window.{var_name} = {safe};\n"


def export_site_feed(feed: Feed, site_data_dir: Path, *, basename: str = "feed",
                     var_name: str = "__GTA6_FEED__") -> bool:
    """feed.json ve feed.js dosyalarını atomik yazar (değişmediyse dokunmaz). Değişti mi döner.
    ``generated_at`` her çalışmada değiştiği için karşılaştırma bu alan hariç yapılır."""
    site_data_dir.mkdir(parents=True, exist_ok=True)
    data = feed.model_dump(mode="json")
    target = site_data_dir / f"{basename}.json"
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
        old.get("status", {}).pop("generated_at", None)
        cmp_new = json.loads(json.dumps(data))
        cmp_new["status"].pop("generated_at", None)
        if old == cmp_new:
            return False
    except (OSError, ValueError, AttributeError):
        pass
    write_if_changed(target, data)
    js_path = site_data_dir / f"{basename}.js"
    payload = feed_js(json.dumps(data, ensure_ascii=False, separators=(",", ":")), var_name)
    tmp = js_path.with_suffix(".js.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(js_path)
    return True
