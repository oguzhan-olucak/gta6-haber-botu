"""RSS/Atom toplama, URL canonicalization, alan adı eşleşmesi ve SSRF korumalı URL doğrulama.

- XML ``defusedxml`` ile ayrıştırılır (XXE / billion laughs koruması).
- Her kaynak izole işlenir: bir kaynağın hatası diğerlerini durdurmaz.
- Öğe bağlantısı, kaynağın ``allowed_domains`` listesine uymuyorsa atılır.
- Kaynak sınıfı (trust_class) yalnızca sources.json'dan gelir; LLM'ye sorulmaz.
"""
from __future__ import annotations

import hashlib
import html
import ipaddress
import logging
import re
import socket
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from defusedxml import ElementTree as DET
from defusedxml.common import DefusedXmlException

from . import ErrorClass, backoff_delay, iso
from .config import Settings, Source

log = logging.getLogger("gta6bot")

USER_AGENT = "GTA6-TR-NewsBot/1.0 (+RSS reader; contact via repository)"
TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "cmpid", "icid",
                   "ito", "taid", "ocid", "_ga"}
ATOM_NS = "{http://www.w3.org/2005/Atom}"


class FetchError(Exception):
    def __init__(self, error_class: ErrorClass, message: str, status: int | None = None):
        self.error_class = error_class
        self.status = status
        super().__init__(message)


@dataclass
class Item:
    id: str                 # canonical URL'nin sha256'sı
    source_id: str
    source_name: str
    trust_class: str
    origin_group: str
    title: str
    url: str                # canonical URL
    summary: str
    published_at: str | None
    content_hash: str
    cited_origins: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CollectResult:
    items: list[Item]
    source_status: dict[str, dict]
    sources_checked: int
    sources_ok: int
    errors: list[str]


# ---- URL yardımcıları -------------------------------------------------------------

def canonicalize_url(url: str) -> str:
    """Şema/host küçük harf, https'e zorla, fragment ve takip parametrelerini at, sorguyu sırala."""
    url = (url or "").strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", netloc, path, urlencode(sorted(query)), ""))


def host_of(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def domain_allowed(url: str, allowed_domains: Iterable[str]) -> bool:
    host = host_of(url)
    if not host:
        return False
    for d in allowed_domains:
        d = d.lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


def url_id(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]


# ---- Metin yardımcıları ---------------------------------------------------------

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def strip_html(text: str) -> str:
    if not text:
        return ""
    p = _TextExtractor()
    try:
        p.feed(text)
        p.close()
        out = " ".join(p.parts)
    except Exception:
        out = re.sub(r"<[^>]+>", " ", text)
    out = html.unescape(out)
    out = unicodedata.normalize("NFC", out)
    out = "".join(ch for ch in out if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    return re.sub(r"\s+", " ", out).strip()


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def content_hash(title: str, summary: str) -> str:
    return hashlib.sha256(f"{normalize_text(title)}|{normalize_text(summary)[:300]}".encode()).hexdigest()[:24]


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
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


def detect_cited_origins(text: str, known_sources: list[Source], own_group: str) -> list[str]:
    """Metinde başka bir kaynağa atıf varsa (\"via IGN\", \"according to Bloomberg\") o kaynağın
    origin_group'unu döndürür. Böylece aynı ilk haberi kopyalayan siteler tek köken sayılır."""
    found: list[str] = []
    low = text.lower()
    names: dict[str, str] = {}
    for s in known_sources:
        names[s.name.lower()] = s.origin_group
    # Kaynak listesinde olmayan ama sık atıf yapılan birincil kaynaklar
    for extra, group in (("bloomberg", "bloomberg"), ("jason schreier", "bloomberg"), ("kotaku", "kotaku"),
                         ("the verge", "the_verge"), ("reuters", "reuters"), ("rockstar games", "rockstar"),
                         ("rockstar newswire", "rockstar"), ("take-two", "take_two"), ("ign", "ign"),
                         ("insider gaming", "insider_gaming"), ("tom henderson", "insider_gaming")):
        names.setdefault(extra, group)
    for name, group in names.items():
        if group == own_group:
            continue
        esc = re.escape(name)
        if any(re.search(p.format(name=esc), low) for p in _CITE_PATTERNS):
            if group not in found:
                found.append(group)
    return found


# ---- HTTP -------------------------------------------------------------------------

def _read_limited(resp: requests.Response, max_bytes: int) -> bytes:
    chunks, total = [], 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise FetchError(ErrorClass.RSS_PARSE_ERROR, "yanıt boyut sınırını aştı")
        chunks.append(chunk)
    return b"".join(chunks)


def http_get(session: requests.Session, url: str, settings: Settings, *,
             sleep: Callable[[float], None] = time.sleep) -> bytes:
    """Geçici hatalarda (429/5xx/timeout) backoff + jitter ile sınırlı yeniden deneme."""
    attempt = 0
    while True:
        try:
            resp = session.get(url, timeout=settings.http_timeout_seconds, stream=True,
                               headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5"},
                               allow_redirects=True)
        except requests.exceptions.Timeout:
            err = FetchError(ErrorClass.NETWORK_TRANSIENT, "zaman aşımı")
        except requests.exceptions.ConnectionError:
            err = FetchError(ErrorClass.NETWORK_TRANSIENT, "bağlantı hatası")
        except requests.exceptions.RequestException as exc:
            raise FetchError(ErrorClass.UNEXPECTED_ERROR, type(exc).__name__) from None
        else:
            try:
                status = resp.status_code
                if status == 200:
                    return _read_limited(resp, settings.http_max_response_bytes)
                if status in (401, 403):
                    raise FetchError(ErrorClass.AUTH_PERMISSION, f"HTTP {status}", status)
                if status == 429:
                    err = FetchError(ErrorClass.RATE_LIMIT_QUOTA, "HTTP 429", status)
                elif 500 <= status < 600:
                    err = FetchError(ErrorClass.NETWORK_TRANSIENT, f"HTTP {status}", status)
                else:
                    raise FetchError(ErrorClass.RSS_PARSE_ERROR, f"HTTP {status}", status)
            finally:
                resp.close()
        if attempt >= settings.http_max_retries:
            raise err
        sleep(backoff_delay(attempt))
        attempt += 1


# ---- Ayrıştırma ---------------------------------------------------------------------

def _text(el) -> str:
    return (el.text or "").strip() if el is not None else ""


def parse_feed(content: bytes) -> list[dict]:
    """RSS 2.0 ve Atom destekler. Bozuk XML -> FetchError(RSS_PARSE_ERROR)."""
    try:
        root = DET.fromstring(content, forbid_dtd=True)
    except (DET.ParseError, DefusedXmlException, ValueError) as exc:
        raise FetchError(ErrorClass.RSS_PARSE_ERROR, f"XML ayrıştırılamadı: {type(exc).__name__}") from None
    entries: list[dict] = []
    tag = root.tag.lower()
    if tag.endswith("rss") or tag.endswith("rdf"):
        for it in root.iter():
            if not (it.tag == "item" or it.tag.endswith("}item")):
                continue
            def child(name):
                for c in it:
                    if c.tag == name or c.tag.endswith("}" + name):
                        return c
                return None
            link = _text(child("link"))
            if not link:
                guid = child("guid")
                if guid is not None and (guid.get("isPermaLink", "true").lower() == "true"):
                    link = _text(guid)
            desc = _text(child("description")) or _text(child("encoded"))
            entries.append({"title": _text(child("title")), "link": link, "summary": desc,
                            "published": _text(child("pubDate")) or _text(child("date"))})
    elif root.tag == f"{ATOM_NS}feed":
        for e in root.findall(f"{ATOM_NS}entry"):
            link = ""
            for l in e.findall(f"{ATOM_NS}link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
                    break
            summary = _text(e.find(f"{ATOM_NS}summary")) or _text(e.find(f"{ATOM_NS}content"))
            entries.append({"title": _text(e.find(f"{ATOM_NS}title")), "link": link, "summary": summary,
                            "published": _text(e.find(f"{ATOM_NS}published")) or _text(e.find(f"{ATOM_NS}updated"))})
    else:
        raise FetchError(ErrorClass.RSS_PARSE_ERROR, "RSS/Atom kök öğesi bulunamadı")
    return entries


def is_relevant(title: str, summary: str, settings: Settings) -> bool:
    text = f" {normalize_text(title)} {normalize_text(summary)} "
    for kw in settings.relevance_keywords.strong:
        if f" {normalize_text(kw)} " in text:
            return True
    return False


def collect(sources: list[Source], settings: Settings, session: requests.Session, now: datetime, *,
            fetch: Callable[[str], bytes] | None = None) -> CollectResult:
    fetch = fetch or (lambda url: http_get(session, url, settings))
    items: list[Item] = []
    status: dict[str, dict] = {}
    errors: list[str] = []
    checked = ok = 0
    min_dt = now - timedelta(hours=settings.max_item_age_hours)
    seen_ids: set[str] = set()
    for src in sources:
        if not src.enabled or not src.feed_url:
            continue
        checked += 1
        try:
            raw_entries = parse_feed(fetch(src.feed_url))
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
        kept = 0
        for e in raw_entries:
            title = strip_html(e.get("title", ""))[:300]
            link = canonicalize_url(urljoin(src.feed_url, e.get("link", "")))
            if not title or not link:
                continue
            if not domain_allowed(link, src.allowed_domains):
                continue
            summary = strip_html(e.get("summary", ""))[: settings.content_limits.source_text_max_chars]
            pub = parse_date(e.get("published"))
            if pub is not None and (pub < min_dt or pub > now + timedelta(hours=1)):
                continue
            if not is_relevant(title, summary, settings):
                continue
            iid = url_id(link)
            if iid in seen_ids:
                continue
            seen_ids.add(iid)
            items.append(Item(id=iid, source_id=src.id, source_name=src.name, trust_class=src.trust_class,
                              origin_group=src.origin_group, title=title, url=link, summary=summary,
                              published_at=iso(pub), content_hash=content_hash(title, summary),
                              cited_origins=detect_cited_origins(f"{title} {summary}", sources, src.origin_group)))
            kept += 1
        status[src.id] = {"ok": True, "entries": len(raw_entries), "relevant": kept, "checked_at": iso(now)}
    items.sort(key=lambda i: i.published_at or "", reverse=True)
    return CollectResult(items=items[: settings.max_rss_items_per_run], source_status=status,
                         sources_checked=checked, sources_ok=ok, errors=errors)


# ---- SSRF korumalı URL doğrulama ------------------------------------------------------

def _is_public_host(host: str, resolver: Callable = socket.getaddrinfo) -> bool:
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


def verify_source_url(url: str, allowed_domains: list[str], session: requests.Session, settings: Settings, *,
                      resolver: Callable = socket.getaddrinfo, max_redirects: int = 3) -> tuple[bool, str]:
    """URL'nin erişilebilir olduğunu ve her yönlendirme adımının + canonical bağlantının izinli
    alan adında kaldığını doğrular. Yalnızca https; özel/iç ağ IP'lerine giden host reddedilir.

    Kalan risk: DNS çözümü ile bağlantı arasındaki DNS rebinding penceresi tamamen kapatılamaz;
    alan adı allowlist'i bu riski büyük ölçüde sınırlar.
    """
    current = url
    for _ in range(max_redirects + 1):
        parts = urlsplit(current)
        if parts.scheme != "https" or not domain_allowed(current, allowed_domains):
            return False, "izinli olmayan şema/alan adı"
        if not _is_public_host(parts.hostname or "", resolver):
            return False, "host genel IP'ye çözülmedi"
        try:
            resp = session.get(current, timeout=settings.http_timeout_seconds, stream=True, allow_redirects=False,
                               headers={"User-Agent": USER_AGENT})
        except requests.exceptions.RequestException as exc:
            return False, f"erişilemedi: {type(exc).__name__}"
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location", "")
                if not loc:
                    return False, "boş yönlendirme"
                current = urljoin(current, loc)
                continue
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}"
            head = b""
            for chunk in resp.iter_content(chunk_size=65536):
                head += chunk
                if len(head) >= 262_144:
                    break
        finally:
            resp.close()
        m = _CANON_RE.search(head)
        if m:
            h = _HREF_RE.search(m.group(0))
            if h:
                canonical = urljoin(current, html.unescape(h.group(1).decode("utf-8", "ignore")))
                if not domain_allowed(canonical, allowed_domains):
                    return False, "canonical bağlantı izinli alan adı dışında"
        return True, canonicalize_url(current)
    return False, "çok fazla yönlendirme"
