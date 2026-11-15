"""Olay kümeleme, tekrar önleme, prompt injection şüphelilerinin ayıklanması ve deterministik puanlama.

Yayın kararı tamamen Python kurallarıyla verilir:

* ``source_strength``: kaynak sınıfı + bağımsız köken sayısı (0-100)
* ``editorial_priority``: güncellik + GTA VI ilgisi + kaynak gücü (0-100)

LLM yalnızca kısa Türkçe başlık/özet ve stil/kategori önerir; etiketi ve eşiği belirleyemez.
Gemini ile ilgili her şey ``bot.gemini`` modülündedir; geriye dönük uyumluluk için buradan da
dışa aktarılır.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from . import parse_iso
from .clustering import Doc, best_match, cluster_docs
from .collector import Item, domain_allowed
from .config import Settings
from .gemini import (
    CATEGORIES,
    LEAK_WORDS,
    RESPONSE_JSON_SCHEMA,
    SYSTEM_INSTRUCTION,
    TITLE_STYLES,
    GeminiError,
    GeminiGenerator,
    GeneratedContent,
    Generator,
    ValidationOutcome,
    build_prompt,
    load_style_hints,
    validate_generated,
)
from .labels import LABEL_NOTE, LABEL_TEXT, OFFICIAL_DOMAINS, STRENGTH_KEY, Assessment, Label
from .textutil import fold_confusables, normalize_text

__all__ = ["Label", "LABEL_TEXT", "LABEL_NOTE", "Assessment", "assess", "cluster_items", "titles_similar",
           "is_duplicate_of_history", "injection_suspect", "GeneratedContent", "RESPONSE_JSON_SCHEMA",
           "SYSTEM_INSTRUCTION", "GeminiError", "GeminiGenerator", "Generator", "ValidationOutcome", "build_prompt",
           "load_style_hints", "validate_generated", "TITLE_STYLES", "CATEGORIES", "LEAK_WORDS"]

log = logging.getLogger("gta6bot")

_LABEL_TIER: dict[Label, tuple[str, ...]] = {
    Label.OFFICIAL: ("OFFICIAL",),
    Label.MULTI_SOURCE: ("ESTABLISHED_MEDIA",),
    Label.SINGLE_SOURCE: ("ESTABLISHED_MEDIA",),
    Label.LEAK_CLAIM: ("ESTABLISHED_MEDIA", "COMMUNITY"),
    Label.COMMUNITY_CLAIM: ("COMMUNITY",),
}
_TRUST_RANK: dict[str, int] = {"OFFICIAL": 0, "ESTABLISHED_MEDIA": 1, "COMMUNITY": 2, "UNKNOWN": 3}

# Kaynak verisine gömülmüş talimat kalıpları (İngilizce + Türkçe). Normalize metinde aranır.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in (
    r"\b(ignore|disregard|forget|override)\b.{0,30}\b(previous|prior|above|earlier|all|system)\b.{0,20}"
    r"\b(instruction|prompt|rule|message|direction)s?\b",
    r"\b(system|developer)\s+(prompt|message|instruction)s?\b",
    r"\byou\s+are\s+now\b",
    r"\bnew\s+instructions?\b",
    r"\b(mark|label|tag|classify|flag)\b.{0,25}\bas\s+(official|verified|confirmed)\b",
    r"\b(set|change)\b.{0,20}\b(label|claim\s*type|trust\s*class)\b",
    r"\bclaim\s*type\b.{0,10}\bofficial\b",
    r"\bneeds\s*review\b.{0,10}\bfalse\b",
    r"\b(onceki|yukaridaki)\s+(talimat|komut|kural)\w*\s+(yok\s+say|unut|gormezden\s+gel)",
    r"\bresmi\s+(olarak\s+)?(isaretle|etiketle)\b",
    r"\bjailbreak\b",
))
_OVERRIDE_VERB = re.compile(r"\b(ignore|disregard|forget|override|bypass|yok\s+say|gormezden\s+gel|unut)\b")
_INSTRUCTION_NOUN = re.compile(r"\b(instructions?|prompts?|directives?|system\s+messages?|talimat\w*|komut\w*)\b")
_INJECTION_RAW = re.compile(r"<\s*/?\s*(untrusted_source_data|system|instructions?)\b|\[\s*/?\s*INST\s*\]|"
                            r"<\|im_(start|end)\|>", re.I)


# ---- Prompt injection şüphelileri -----------------------------------------------------

def injection_suspect(item: Item) -> bool:
    """Öğenin başlık/özetinde LLM'e yönelik gömülü talimat izi var mı?"""
    raw = fold_confusables(f"{item.title} {item.summary}")
    if _INJECTION_RAW.search(raw):
        return True
    norm = normalize_text(raw)
    if any(p.search(norm) for p in _INJECTION_PATTERNS):
        return True
    # Sıradan ve mesafeden bağımsız: geçersiz kılma fiili + talimat ismi 150 karakter içinde
    for m in _OVERRIDE_VERB.finditer(norm):
        window = norm[max(0, m.start() - 150): m.end() + 150]
        if _INSTRUCTION_NOUN.search(window):
            return True
    return False


# ---- Kümeleme ve tekrar -----------------------------------------------------------------

def _doc(item: Item) -> Doc:
    return Doc(key=item.id, title=item.title, summary=item.summary, url=item.url,
               content_hash=item.content_hash, published_at=item.published_at)


def cluster_items(items: list[Item], threshold: float, max_gap_hours: float = 72.0) -> list[list[Item]]:
    """Aynı olayı anlatan öğeleri ``bot.clustering`` motoruyla tek kümede toplar."""
    groups = cluster_docs([_doc(i) for i in items], threshold, max_gap_hours=max_gap_hours)
    return [[items[k] for k in g] for g in groups]


def titles_similar(a: str, b: str, threshold: float) -> bool:
    """İki başlık aynı olayı mı anlatıyor? (yalnızca başlık sinyalleriyle)"""
    return best_match(a, [b], threshold) > 0


def is_duplicate_of_history(cluster: list[Item], history: dict[str, Any], settings: Settings,
                            now: datetime) -> bool:
    """Küme daha önce yayınlanmış/incelemeye alınmış bir haberin tekrarı mı?
    Aynı URL veya içerik özeti süresiz; başlık benzerliği ``dedup_lookback_hours`` içinde."""
    cutoff = now - timedelta(hours=settings.dedup_lookback_hours)
    urls = {i.url for i in cluster}
    hashes = {i.content_hash for i in cluster}
    recent_titles: list[str] = []
    for post in history.get("posts", []):
        if post.get("publish_status") == "FAILED":
            continue
        if urls & set(post.get("source_urls", [])) or hashes & set(post.get("content_hashes", [])):
            return True
        published = parse_iso(post.get("published_at") or post.get("created_at"))
        if published and published >= cutoff:
            recent_titles.extend(post.get("source_titles", []))
    return any(best_match(i.title, recent_titles, settings.title_similarity_threshold) for i in cluster)


# ---- Deterministik değerlendirme --------------------------------------------------------

def _origins(items: list[Item]) -> set[str]:
    """Başka bir yayına atıf yapan haber, atıf yapılan kökenin kopyası sayılır."""
    out: set[str] = set()
    for it in items:
        out.update(it.cited_origins or [it.origin_group])
    return out


def _relevance(cluster: list[Item], settings: Settings) -> int:
    best = 0
    strong = [normalize_text(k) for k in settings.relevance_keywords.strong]
    context = [normalize_text(k) for k in settings.relevance_keywords.context]
    for it in cluster:
        t, s = f" {normalize_text(it.title)} ", f" {normalize_text(it.summary)} "
        score = 25 if any(f" {k} " in t for k in strong) else 12 if any(f" {k} " in s for k in strong) else 0
        if score and any(f" {k} " in t + s for k in context):
            score = min(25, score + 3)
        best = max(best, score)
    return best


def _recency(cluster: list[Item], settings: Settings, now: datetime) -> int:
    dates = [d for d in (parse_iso(i.published_at) for i in cluster) if d]
    if not dates:
        return 10
    hours = max(0.0, (now - max(dates)).total_seconds() / 3600)
    return round(35 * max(0.0, 1 - hours / settings.max_item_age_hours))


def is_official_item(item: Item) -> bool:
    """Resmî sayılmak için: OFFICIAL kaynak sınıfı + doğrulanmış nihai URL + resmî alan adı."""
    return item.trust_class == "OFFICIAL" and item.url_verified and domain_allowed(item.url, OFFICIAL_DOMAINS)


def _usable(cluster: list[Item], settings: Settings) -> tuple[list[Item], int]:
    """Geçerli https URL'li, tanınan, enjeksiyon şüphesi taşımayan öğeler + atılan şüpheli sayısı.
    Resmî sınıftan olup doğrulanmamış öğeler de atılır (sahte RESMÎ etiketi engeli)."""
    suspects = 0
    usable: list[Item] = []
    for i in cluster:
        if not i.url.startswith("https://") or i.trust_class == "UNKNOWN":
            continue
        if i.trust_class == "OFFICIAL" and not is_official_item(i):
            continue
        if settings.reject_injection_suspects and injection_suspect(i):
            suspects += 1
            continue
        usable.append(i)
    return usable, suspects


def _display_names(items: list[Item], origins: list[str]) -> str:
    """Köken kimliklerini okura gösterilebilir yayın adlarına çevirir (iç kimlik sızmaz)."""
    by_group: dict[str, str] = {}
    for i in items:
        by_group.setdefault(i.origin_group, i.source_name)
    return ", ".join(by_group.get(o) or o.replace("_", " ").title() for o in origins)


def _label_for(valid: list[Item]) -> tuple[Label, int, str, list[str]]:
    """Etiket, kaynak gücü, gerekçe ve bağımsız kökenler."""
    official = [i for i in valid if i.trust_class == "OFFICIAL"]
    media = [i for i in valid if i.trust_class == "ESTABLISHED_MEDIA"]
    community = [i for i in valid if i.trust_class == "COMMUNITY"]
    leaky = any(LEAK_WORDS.search(normalize_text(i.title)) for i in valid if i.trust_class != "OFFICIAL")
    if official:
        return Label.OFFICIAL, 95, "Resmî alan adında doğrudan yayın (URL doğrulandı)", sorted(_origins(official))
    if media and not leaky:
        origins = sorted(_origins(media))
        if len(origins) >= 2:
            return (Label.MULTI_SOURCE, min(90, 75 + 5 * (len(origins) - 2)),
                    f"{len(origins)} bağımsız yayın: {_display_names(media, origins)}", origins)
        cites_official = any({"rockstar", "take_two"} & set(i.cited_origins) for i in media)
        return (Label.SINGLE_SOURCE, 55 + (10 if cites_official else 0),
                f"Tek yayın: {_display_names(media, origins)}" + (" (resmî açıklamaya atıf)" if cites_official else ""),
                origins)
    if media:
        return Label.LEAK_CLAIM, 30, "Yayın organında sızıntı/iddia haberi", sorted(_origins(media))
    label = Label.LEAK_CLAIM if leaky else Label.COMMUNITY_CLAIM
    return label, 20, "Yalnızca topluluk kaynağı", sorted(_origins(community))


def _gate(a: Assessment, settings: Settings) -> Assessment:
    """Ayar kapıları: tek kaynak / iddia izinleri, kaynak gücü ve öncelik eşikleri."""
    assert a.label is not None
    if a.label == Label.SINGLE_SOURCE and not settings.allow_single_source_media:
        a.decision, a.reason = "HOLD", a.reason + "; tek kaynak yayını kapalı, ikinci kaynak bekleniyor"
    elif a.label in (Label.LEAK_CLAIM, Label.COMMUNITY_CLAIM) and not settings.allow_community_rumors:
        a.decision, a.reason = "HOLD", a.reason + "; iddia yayını kapalı (allow_community_rumors=false)"
    elif a.source_strength < getattr(settings.min_source_strength, STRENGTH_KEY[a.label]):
        a.decision, a.reason = "HOLD", a.reason + "; kaynak gücü eşiğin altında"
    elif a.editorial_priority < settings.min_publish_threshold:
        a.decision = "HOLD"
        a.reason += f"; öncelik {a.editorial_priority} < eşik {settings.min_publish_threshold}"
    return a


def assess(cluster: list[Item], settings: Settings, now: datetime) -> Assessment:
    """Bir olay kümesi için deterministik karar: CANDIDATE / HOLD / REJECT."""
    valid, suspects = _usable(cluster, settings)
    if not valid:
        reason = "Olası prompt injection içeren kaynak metni" if suspects else \
            "Geçerli kaynak URL'si veya tanınan/doğrulanmış kaynak yok"
        return Assessment("REJECT", None, 0, 0, reason, None)
    valid.sort(key=lambda i: (_TRUST_RANK.get(i.trust_class, 9), i.published_at or "~"))
    label, strength, reason, origins = _label_for(valid)
    # Etiketi belirleyen güven katmanı dışındaki öğeler (ör. Reddit) ne isteme ne kaynak listesine girer.
    tier = _LABEL_TIER[label]
    leak_media = label == Label.LEAK_CLAIM and any(i.trust_class == "ESTABLISHED_MEDIA" for i in valid)
    valid = [i for i in valid if i.trust_class in (("ESTABLISHED_MEDIA",) if leak_media else tier)]
    if suspects:
        reason += f"; {suspects} şüpheli öğe ayıklandı"
    priority = min(100, _recency(valid, settings, now) + _relevance(valid, settings) + round(strength * 0.4))
    return _gate(Assessment("CANDIDATE", label, strength, priority, reason, valid[0], origins, valid), settings)
