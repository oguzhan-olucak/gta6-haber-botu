"""Kaynak toplama: RSS/Atom, Google News (alan adı kısıtlı) ve HTML liste sayfaları.

- XML ``defusedxml`` ile ayrıştırılır (XXE / billion laughs koruması). Geçersiz UTF-8 baytları
  içeren besleme reddedilmez; bayt düzeyinde onarılıp yeniden ayrıştırılır.
- Her kaynak izole işlenir: bir kaynağın hatası diğerlerini durdurmaz.
- Öğe bağlantısı, kaynağın ``allowed_domains`` listesine uymuyorsa atılır.
- Kaynak sınıfı (``trust_class``) yalnızca ``sources.json``'dan gelir; LLM'ye sorulmaz.
- ``OFFICIAL`` sınıfındaki her öğenin URL'si SSRF korumalı olarak doğrulanır; nihai URL resmî
  alan adında değilse öğe atılır (``url_verified=True`` yalnızca bu kontrolden geçenlere verilir).
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import logging
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

from . import ErrorClass, backoff_delay, iso
from .config import Settings, Source
from .official import (
    GN_BATCHEXECUTE_URL,
    clean_google_news_title,
    decode_google_news_offline,
    gn_article_id,
    gn_batch_form,
    gn_parse_batch_response,
    gn_signature,
    google_news_source_url,
    is_google_news_url,
    parse_html_listing,
)
from .textutil import normalize_text, repair_feed_bytes, strip_html, truncate

__all__ = ["Item", "CollectResult", "FetchError", "canonicalize_url", "domain_allowed", "collect", "parse_feed",
           "verify_source_url", "strip_html", "normalize_text", "content_hash", "url_id", "detect_cited_origins"]

log = logging.getLogger("gta6bot")

USER_AGENT = "GTA6-TR-NewsBot/1.0 (+RSS reader; contact via repository)"
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "cmpid", "icid",
                   "ito", "taid", "ocid", "_ga"}
ATOM_NS = "{http://www.w3.org/2005/Atom}"
TITLE_MAX_CHARS = 300


Verifier = Callable[[str, Sequence[str], Sequence[str]], tuple[bool, str]]
"""URL doğrulayıcı: (url, nihai izinli alan adları, ara adım alan adları) → (geçti mi, nihai URL/neden)."""


class FetchError(Exception):
    """Kaynak alınamadı veya ayrıştırılamadı."""

    def __init__(self, error_class: ErrorClass, message: str, status: int | None = None):
        self.error_class = error_class
        self.status = status
        super().__init__(message)


@dataclass
class Item:
    """Toplanan tek haber öğesi (normalize edilmiş)."""
    id: str
    source_id: str
    source_name: str
    trust_class: str
    origin_group: str
    title: str
    url: str
    summary: str
    published_at: str | None
    content_hash: str
    cited_origins: list[str] = field(default_factory=list)
    url_verified: bool = False
    via: str = "rss"
    raw_id: str = ""  # doğrulama öncesi ham bağlantının kimliği (tekrar doğrulamayı önlemek için)

    def to_dict(self) -> dict[str, Any]:
        """JSON'a yazılabilir sözlük."""
        return asdict(self)


@dataclass
class CollectResult:
    """Bir toplama turunun sonucu."""
    items: list[Item]
    source_status: dict[str, dict[str, Any]]
    sources_checked: int
    sources_ok: int
    errors: list[str]
    known_skipped: int = 0


# ---- URL yardımcıları -------------------------------------------------------------

def canonicalize_url(url: str) -> str:
    """Şema/host küçük harf, https'e zorla, ``www.`` ve fragment'i at, takip parametrelerini sil,
    sorguyu sırala. Geçersiz/desteklenmeyen şemada boş dize döner."""
    parts = urlsplit((url or "").strip())
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", netloc, path, urlencode(sorted(query)), ""))


def host_of(url: str) -> str:
    """``www.`` öneki atılmış küçük harfli host."""
    h = (urlsplit(url).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def domain_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    """Host, izinli alan adlarından birine eşit veya onun alt alan adı mı (nokta sınırıyla)?"""
    host = host_of(url)
    if not host:
        return False
    for d in allowed_domains:
        d = d.lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


def url_id(canonical_url: str) -> str:
    """Canonical URL'nin kısa sha256 özeti (öğe kimliği)."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]


def content_hash(title: str, summary: str) -> str:
    """Başlık + özet başından normalize edilmiş içerik özeti."""
    return hashlib.sha256(f"{normalize_text(title)}|{normalize_text(summary)[:300]}".encode()).hexdigest()[:24]


def parse_date(value: str | None) -> datetime | None:
    """RFC 822 (RSS) veya ISO 8601 (Atom) tarihini UTC datetime'a çevirir."""
    if not value:
        return None
    value = value.strip()
    dt: datetime | None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- Alıntı zinciri (kaynak bağımsızlığı) ------------------------------------------

_CITE_PATTERNS = [
    r"\bvia\s+{name}\b",
    r"\baccording to\s+(?:a\s+(?:new\s+)?report\s+(?:from|by)\s+)?{name}\b",
    r"\b(?:as\s+)?(?:first\s+)?reported\s+by\s+{name}\b",
    r"\b{name}\s+(?:first\s+)?reported\b",
    r"\b{name}\s+(?:has\s+)?(?:learned|reports|claims)\b",
    r"\bkaynak:\s*{name}\b",
]
_EXTRA_ORIGINS = (("bloomberg", "bloomberg"), ("jason schreier", "bloomberg"), ("kotaku", "kotaku"),
                  ("the verge", "the_verge"), ("reuters", "reuters"), ("rockstar games", "rockstar"),
                  ("rockstar newswire", "rockstar"), ("take-two", "take_two"), ("ign", "ign"),
                  ("insider gaming", "insider_gaming"), ("tom henderson", "insider_gaming"))


def detect_cited_origins(text: str, known_sources: list[Source], own_group: str) -> list[str]:
    """Metinde başka bir yayına atıf varsa ("via IGN", "according to Bloomberg") o kaynağın
    ``origin_group`` değerini döndürür. Aynı ilk haberi kopyalayan siteler tek köken sayılır."""
    low = text.lower()
    names: dict[str, str] = {s.name.lower(): s.origin_group for s in known_sources}
    for extra, group in _EXTRA_ORIGINS:
        names.setdefault(extra, group)
    found: list[str] = []
    for name, group in names.items():
        if group == own_group or group in found:
            continue
        esc = re.escape(name)
        if any(re.search(p.format(name=esc), low) for p in _CITE_PATTERNS):
            found.append(group)
    return found


# ---- HTTP -------------------------------------------------------------------------

def _read_limited(resp: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(ErrorClass.RSS_PARSE_ERROR, "yanıt boyut sınırını aştı")
        chunks.append(chunk)
    return b"".join(chunks)


def _classify_status(status: int) -> FetchError:
    if status in (401, 403):
        return FetchError(ErrorClass.AUTH_PERMISSION, f"HTTP {status}", status)
    if status == 429:
        return FetchError(ErrorClass.RATE_LIMIT_QUOTA, "HTTP 429", status)
    if 500 <= status < 600:
        return FetchError(ErrorClass.NETWORK_TRANSIENT, f"HTTP {status}", status)
    return FetchError(ErrorClass.RSS_PARSE_ERROR, f"HTTP {status}", status)


def http_get(session: requests.Session, url: str, settings: Settings, *,
             sleep: Callable[[float], None] = time.sleep) -> bytes:
    """Besleme/sayfa indirir. 429/5xx/zaman aşımında backoff + jitter ile sınırlı yeniden deneme;
    401/403 ve diğer 4xx için yeniden deneme yok."""
    attempt = 0
    while True:
        err: FetchError
        try:
            resp = session.get(url, timeout=settings.http_timeout_seconds, stream=True, allow_redirects=True,
                               headers={"User-Agent": USER_AGENT,
                                        "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                                                  "text/xml;q=0.9, text/html;q=0.8, */*;q=0.5"})
        except requests.exceptions.Timeout:
            err = FetchError(ErrorClass.NETWORK_TRANSIENT, "zaman aşımı")
        except requests.exceptions.ConnectionError:
            err = FetchError(ErrorClass.NETWORK_TRANSIENT, "bağlantı hatası")
        except requests.exceptions.RequestException as exc:
            raise FetchError(ErrorClass.UNEXPECTED_ERROR, type(exc).__name__) from None
        else:
            try:
                if resp.status_code == 200:
                    return _read_limited(resp, settings.http_max_response_bytes)
                err = _classify_status(resp.status_code)
            finally:
                resp.close()
            if err.error_class not in (ErrorClass.RATE_LIMIT_QUOTA, ErrorClass.NETWORK_TRANSIENT):
                raise err
        if attempt >= settings.http_max_retries:
            raise err
        sleep(backoff_delay(attempt))
        attempt += 1


# ---- Ayrıştırma ---------------------------------------------------------------------

def _text(el: Any) -> str:
    return (el.text or "").strip() if el is not None else ""


def _child(parent: Any, name: str) -> Any:
    for c in parent:
        if c.tag == name or str(c.tag).endswith("}" + name):
            return c
    return None


def _parse_xml(content: bytes) -> Any:
    """Önce baytları olduğu gibi, olmazsa onarılmış metni ayrıştırır."""
    try:
        return DET.fromstring(content, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise FetchError(ErrorClass.RSS_PARSE_ERROR, f"güvensiz XML: {type(exc).__name__}") from None
    except (DET.ParseError, ValueError):
        pass
    try:
        return DET.fromstring(repair_feed_bytes(content), forbid_dtd=True)
    except (DET.ParseError, DefusedXmlException, ValueError) as exc:
        raise FetchError(ErrorClass.RSS_PARSE_ERROR, f"XML ayrıştırılamadı: {type(exc).__name__}") from None


def _rss_entries(root: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for it in root.iter():
        if not (it.tag == "item" or str(it.tag).endswith("}item")):
            continue
        link = _text(_child(it, "link"))
        guid = _child(it, "guid")
        if not link and guid is not None and guid.get("isPermaLink", "true").lower() == "true":
            link = _text(guid)
        entries.append({"title": _text(_child(it, "title")), "link": link,
                        "summary": _text(_child(it, "description")) or _text(_child(it, "encoded")),
                        "published": _text(_child(it, "pubDate")) or _text(_child(it, "date")),
                        "source_url": google_news_source_url(it)})
    return entries


def _atom_entries(root: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for e in root.findall(f"{ATOM_NS}entry"):
        link = ""
        for ln in e.findall(f"{ATOM_NS}link"):
            if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                link = ln.get("href")
                break
        entries.append({"title": _text(e.find(f"{ATOM_NS}title")), "link": link,
                        "summary": _text(e.find(f"{ATOM_NS}summary")) or _text(e.find(f"{ATOM_NS}content")),
                        "published": _text(e.find(f"{ATOM_NS}published")) or _text(e.find(f"{ATOM_NS}updated")),
                        "source_url": ""})
    return entries


def parse_feed(content: bytes) -> list[dict[str, str]]:
    """RSS 2.0 / RDF / Atom ayrıştırır. Bozuk XML → ``FetchError(RSS_PARSE_ERROR)``."""
    root = _parse_xml(content)
    tag = str(root.tag).lower()
    if tag.endswith("rss") or tag.endswith("rdf"):
        return _rss_entries(root)
    if root.tag == f"{ATOM_NS}feed":
        return _atom_entries(root)
    raise FetchError(ErrorClass.RSS_PARSE_ERROR, "RSS/Atom kök öğesi bulunamadı")


def entries_for_source(src: Source, content: bytes) -> list[dict[str, str]]:
    """Kaynak türüne göre ham girdileri çıkarır."""
    if src.kind == "html_listing":
        return parse_html_listing(content, src.feed_url, src.link_pattern)
    entries = parse_feed(content)
    if src.kind == "google_news":
        kept = []
        for e in entries:
            # Google News yayıncı etiketi resmî alan adını göstermiyorsa baştan ele
            if e.get("source_url") and not domain_allowed(e["source_url"], src.allowed_domains):
                continue
            e["title"] = clean_google_news_title(e.get("title", ""))
            kept.append(e)
        return kept
    return entries


def is_relevant(title: str, summary: str, settings: Settings, *, official: bool = False) -> bool:
    """Haber GTA VI ile ilgili mi?

    1. Güçlü terim (GTA VI / GTA 6 / Grand Theft Auto VI / Leonida...) → ilgili.
    2. Güçlü terim yokken dışlama terimi (GTA Online, Definitive Edition...) → ilgisiz.
    3. Özgül terim (Vice City, Lucia, Jason...) + marka (Rockstar/Take-Two) veya resmî kaynak → ilgili.
    """
    kw = settings.relevance_keywords
    text = f" {normalize_text(title)} {normalize_text(summary)} "

    def hit(terms: list[str]) -> bool:
        return any(f" {normalize_text(t)} " in text for t in terms if normalize_text(t))

    if hit(kw.strong):
        return True
    if hit(kw.exclude):
        return False
    return hit(kw.specific) and (official or hit(kw.brand))


# ---- Öğe oluşturma ---------------------------------------------------------------------

def _resolve_link(src: Source, raw_link: str, verifier: Verifier | None) -> tuple[str, bool] | None:
    """Ham bağlantıyı canonical hale getirir; gerekiyorsa (resmî kaynak veya Google News)
    doğrular. Dönüş: (canonical_url, doğrulandı_mı) ya da atılacaksa None."""
    link = canonicalize_url(urljoin(src.feed_url or "", raw_link))
    if not link:
        return None
    if is_google_news_url(link):
        decoded = decode_google_news_offline(link)
        if decoded and domain_allowed(decoded, src.allowed_domains):
            link = canonicalize_url(decoded)
        elif verifier is None:
            return None
        else:
            ok, final = verifier(link, src.allowed_domains, ["news.google.com"])
            return (final, True) if ok and domain_allowed(final, src.allowed_domains) else None
    if not domain_allowed(link, src.allowed_domains):
        return None
    if src.trust_class == "OFFICIAL":
        if verifier is None:
            return None
        ok, final = verifier(link, src.allowed_domains, [])
        return (final, True) if ok and domain_allowed(final, src.allowed_domains) else None
    return link, False


def _build_item(src: Source, entry: dict[str, str], settings: Settings, sources: list[Source],
                now: datetime, stats: dict[str, int] | None = None) -> Item | None:
    """Filtrelerden (başlık, ilgi, tarih) geçen girdiden URL çözümlemesi ÖNCESİ taslak öğe üretir.
    ``stats["matched"]`` tarihten bağımsız olarak ilgili bulunan girdileri sayar (tanılama için)."""
    title = truncate(strip_html(entry.get("title", "")), TITLE_MAX_CHARS)
    if not title:
        return None
    summary = truncate(strip_html(entry.get("summary", "")), settings.content_limits.source_text_max_chars)
    if not is_relevant(title, summary, settings, official=src.trust_class == "OFFICIAL"):
        return None
    if stats is not None:
        stats["matched"] = stats.get("matched", 0) + 1
    pub = parse_date(entry.get("published"))
    max_age = src.max_item_age_hours or settings.max_item_age_hours
    min_dt = now - timedelta(hours=max_age)
    if pub is not None and (pub < min_dt or pub > now + timedelta(hours=1)):
        return None
    return Item(id="", source_id=src.id, source_name=src.name, trust_class=src.trust_class,
                origin_group=src.origin_group, title=title, url="", summary=summary, published_at=iso(pub),
                content_hash=content_hash(title, summary),
                cited_origins=detect_cited_origins(f"{title} {summary}", sources, src.origin_group),
                via=src.kind)


def _items_from_source(src: Source, entries: list[dict[str, str]], settings: Settings, sources: list[Source],
                       now: datetime, verifier: Verifier | None, seen_ids: set[str],
                       known_ids: set[str] | frozenset[str] = frozenset(),
                       stats: dict[str, int] | None = None) -> list[Item]:
    stats = stats if stats is not None else {"known": 0}
    items: list[Item] = []
    verifications = 0
    for e in entries:
        draft = _build_item(src, e, settings, sources, now, stats)
        if draft is None:
            continue
        raw = canonicalize_url(urljoin(src.feed_url or "", e.get("link", "")))
        draft.raw_id = url_id(raw) if raw else ""
        if draft.raw_id and draft.raw_id in known_ids:
            stats["known"] += 1
            continue  # daha önce görüldü: yeniden ağ doğrulaması yapma
        needs_net = src.trust_class == "OFFICIAL" or src.kind == "google_news"
        if needs_net:
            if verifications >= src.max_verifications_per_run:
                break
            verifications += 1
        resolved = _resolve_link(src, e.get("link", ""), verifier)
        if resolved is None:
            continue
        draft.url, draft.url_verified = resolved
        draft.id = url_id(draft.url)
        if draft.id in seen_ids:
            continue
        seen_ids.add(draft.id)
        items.append(draft)
    return items


def collect(sources: list[Source], settings: Settings, session: requests.Session | None, now: datetime, *,
            fetch: Callable[[str], bytes] | None = None, verifier: Verifier | None = None,
            clock: Callable[[], float] = time.monotonic, deadline_at: float | None = None,
            known_ids: set[str] | frozenset[str] = frozenset()) -> CollectResult:
    """Tüm etkin kaynakları sırayla toplar; her kaynak hatası izole edilir. Çalışma süresi sınırı
    (``deadline_at`` veya başlangıç + ``run_deadline_seconds``) dolunca kalan kaynaklar atlanır."""
    deadline = deadline_at if deadline_at is not None else clock() + settings.run_deadline_seconds
    if fetch is None:
        if session is None:
            raise ValueError("fetch veya session verilmeli")
        sess = session

        def fetch(url: str) -> bytes:
            """Kaynağı HTTP ile indirir."""
            return http_get(sess, url, settings)

    items: list[Item] = []
    status: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    checked = ok = 0
    seen_ids: set[str] = set()
    stats = {"known": 0}
    for src in sources:
        if not src.enabled or not src.feed_url:
            continue
        if clock() >= deadline:
            status[src.id] = {"ok": False, "skipped": "deadline", "checked_at": iso(now)}
            continue
        checked += 1
        try:
            entries = entries_for_source(src, fetch(src.feed_url))
            stats["matched"] = 0
            got = _items_from_source(src, entries, settings, sources, now, verifier, seen_ids, known_ids, stats)
        except FetchError as exc:
            status[src.id] = {"ok": False, "error_class": exc.error_class.value, "detail": str(exc)[:120],
                              "http_status": exc.status, "checked_at": iso(now)}
            errors.append(exc.error_class.value)
            log.warning("Kaynak %s başarısız: %s", src.id, exc.error_class.value)
            continue
        except Exception as exc:  # bir kaynağın beklenmeyen hatası diğerlerini durdurmasın
            status[src.id] = {"ok": False, "error_class": ErrorClass.UNEXPECTED_ERROR.value,
                              "detail": type(exc).__name__, "checked_at": iso(now)}
            errors.append(ErrorClass.UNEXPECTED_ERROR.value)
            log.warning("Kaynak %s beklenmeyen hata: %s", src.id, type(exc).__name__)
            continue
        ok += 1
        items.extend(got)
        # relevant: GTA VI ile ilgili bulunan girdi (tarihten bağımsız) · new: bu çalışmada eklenen yeni öğe
        status[src.id] = {"ok": True, "entries": len(entries), "relevant": stats["matched"], "new": len(got),
                          "checked_at": iso(now)}
        if not entries:
            status[src.id]["warning"] = "kaynak boş döndü (istemci tarafında çizilen sayfa veya yanlış adres?)"
    items.sort(key=lambda i: i.published_at or "", reverse=True)
    return CollectResult(items=items[: settings.max_rss_items_per_run], source_status=status,
                         sources_checked=checked, sources_ok=ok, errors=errors, known_skipped=stats["known"])


# ---- SSRF korumalı URL doğrulama ------------------------------------------------------

Resolver = Callable[..., list[tuple[Any, ...]]]


def _is_public_host(host: str, resolver: Resolver = socket.getaddrinfo) -> bool:
    """Host'un çözüldüğü TÜM adresler genel (public) IP mi?"""
    try:
        infos = resolver(host, 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    if not infos:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
                or ip.is_unspecified or not ip.is_global):
            return False
    return True


_CANON_RE = re.compile(rb"<link[^>]+rel=[\"']canonical[\"'][^>]*>", re.I)
_HREF_RE = re.compile(rb"href=[\"']([^\"']+)[\"']", re.I)


def _canonical_ok(head: bytes, current: str, allowed_domains: Sequence[str]) -> bool:
    m = _CANON_RE.search(head)
    if not m:
        return True
    h = _HREF_RE.search(m.group(0))
    if not h:
        return True
    canonical = urljoin(current, html.unescape(h.group(1).decode("utf-8", "ignore")))
    return domain_allowed(canonical, allowed_domains)


def _gn_resolve_signed(url: str, resp: Any, session: requests.Session, settings: Settings) -> str | None:
    """İmzalı Google News makale sayfası (HTTP 200, JavaScript yönlendirmesi) için yayıncı URL'sini
    ``batchexecute`` uç noktasından ister. Yalnızca news.google.com sayfalarında çalışır; sonuç
    çağıran döngüde yeniden alan adı/IP/canonical denetiminden geçer."""
    article_id = gn_article_id(url)
    if article_id is None:
        return None
    page = b""
    for chunk in resp.iter_content(chunk_size=65536):
        page += chunk
        if len(page) >= 524_288:
            break
    sig = gn_signature(page)
    if sig is None:
        return None
    signature, timestamp = sig
    try:
        r = session.post(GN_BATCHEXECUTE_URL, data=gn_batch_form(article_id, timestamp, signature),
                         timeout=settings.http_timeout_seconds, allow_redirects=False,
                         headers={"User-Agent": USER_AGENT,
                                  "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    except requests.exceptions.RequestException:
        return None
    try:
        if r.status_code != 200:
            return None
        body = _read_limited(r, 262_144)
    except FetchError:
        return None
    finally:
        r.close()
    return gn_parse_batch_response(body.decode("utf-8", "replace"))


def _hop(current: str, resp: Any, final_ok: bool, session: requests.Session,
         settings: Settings) -> tuple[str, str]:
    """Tek doğrulama adımının sonucu: ("next", yeni_url) | ("fail", neden) | ("final", "")."""
    if resp.status_code in (301, 302, 303, 307, 308):
        loc = resp.headers.get("Location", "")
        return ("next", urljoin(current, loc)) if loc else ("fail", "boş yönlendirme")
    if resp.status_code != 200:
        return "fail", f"HTTP {resp.status_code}"
    if not final_ok:
        decoded = _gn_resolve_signed(current, resp, session, settings)
        return ("next", decoded) if decoded else ("fail", "nihai adres izinli alan adında değil")
    return "final", ""


def verify_source_url(url: str, allowed_domains: Sequence[str], session: requests.Session, settings: Settings, *,
                      hop_domains: Sequence[str] = (), resolver: Resolver = socket.getaddrinfo,
                      max_redirects: int = 3) -> tuple[bool, str]:
    """URL'nin erişilebilir olduğunu ve **nihai** adresin + canonical bağlantının izinli alan adında
    olduğunu doğrular. Ara yönlendirme adımları ``allowed_domains`` veya ``hop_domains`` içinde
    olmalıdır (ör. Google News için ``news.google.com``). Yalnızca https; özel/iç ağ IP'lerine
    çözülen host reddedilir. Başarılıysa (True, nihai canonical URL) döner.

    Kalan risk: DNS çözümü ile bağlantı arasındaki DNS rebinding penceresi tamamen kapatılamaz;
    alan adı allowlist'i bu riski büyük ölçüde sınırlar."""
    current = url
    for _ in range(max_redirects + 1):
        parts = urlsplit(current)
        final_ok = domain_allowed(current, allowed_domains)
        if parts.scheme != "https" or not (final_ok or domain_allowed(current, hop_domains)):
            return False, "izinli olmayan şema/alan adı"
        if not _is_public_host(parts.hostname or "", resolver):
            return False, "host genel IP'ye çözülmedi"
        try:
            resp = session.get(current, timeout=settings.http_timeout_seconds, stream=True, allow_redirects=False,
                               headers={"User-Agent": USER_AGENT})
        except requests.exceptions.RequestException as exc:
            return False, f"erişilemedi: {type(exc).__name__}"
        try:
            step, value = _hop(current, resp, final_ok, session, settings)
            if step == "fail":
                return False, value
            if step == "next":
                current = value
                continue
            head = b""
            for chunk in resp.iter_content(chunk_size=65536):
                head += chunk
                if len(head) >= 262_144:
                    break
        finally:
            resp.close()
        if not _canonical_ok(head, current, allowed_domains):
            return False, "canonical bağlantı izinli alan adı dışında"
        return True, canonicalize_url(current)
    return False, "çok fazla yönlendirme"
