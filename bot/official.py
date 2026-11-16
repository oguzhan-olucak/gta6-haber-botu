"""Resmî kaynak (Rockstar Games / Take-Two) toplama yardımcıları.

Doğrulanmış bir resmî RSS adresi bulunamadığı için iki ek yol desteklenir:

1. **Google News RSS, alan adı kısıtlı sorgu** (``kind: "google_news"``), ör.
   ``https://news.google.com/rss/search?q=site:rockstargames.com+%22Grand+Theft+Auto+VI%22``.
   Google News bağlantıları ``news.google.com/rss/articles/<id>`` biçimindedir. 2024'ten beri
   bu kimliklerin çoğu çevrimdışı çözülemeyen imzalı kimliklerdir. Bu modül önce eski
   (base64 içinde URL taşıyan) biçimi çevrimdışı çözmeyi dener, olmazsa yönlendirmeyi SSRF
   korumalı olarak takip eder. Takip edilen sayfa 200 dönüp JavaScript ile yönlendiriyorsa
   (imzalı biçim), sayfadaki ``data-n-a-sg`` / ``data-n-a-ts`` imzasıyla Google News'in
   ``batchexecute`` uç noktasından yayıncı URL'si istenir (``gn_*`` yardımcıları burada saf
   fonksiyonlardır; ağ çağrısı ``collector`` içindedir). **Nihai URL resmî alan adında değilse
   öğe atılır.**
2. **HTML liste sayfası ayrıştırıcı** (``kind: "html_listing"``): sayfadaki ``<a href>``
   bağlantıları ve JSON-LD verisinden, ``link_pattern`` düzenli ifadesine uyan makale
   bağlantıları çıkarılır. İstemci tarafında (JavaScript ile) çizilen sayfalarda sonuç boş
   olabilir; bu durumda kaynak durumu ``entries: 0`` olarak raporlanır.

Her iki yolda da bir öğenin ``OFFICIAL`` sayılması için URL'nin doğrulanması
(``url_verified=True``) ve resmî alan adında olması şarttır; bu kontrol ``collector`` ve
``processor.assess`` içinde iki kez yapılır.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

from .textutil import strip_html

GOOGLE_NEWS_HOSTS: tuple[str, ...] = ("news.google.com",)
_GN_ARTICLE_RE = re.compile(r"^/(?:rss/)?(?:__i/rss/rd/)?articles/([A-Za-z0-9_-]+)")
_URL_IN_BYTES_RE = re.compile(rb"https?://[\x21-\x7e]+")
_PUBLISHER_SUFFIX_RE = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,60}$")


# ---- Google News -------------------------------------------------------------------

def is_google_news_url(url: str) -> bool:
    """Bağlantı bir Google News yönlendirme bağlantısı mı?"""
    parts = urlsplit(url)
    return (parts.hostname or "").lower() in GOOGLE_NEWS_HOSTS and bool(_GN_ARTICLE_RE.match(parts.path))


def decode_google_news_offline(url: str) -> str | None:
    """Eski biçimli Google News kimliğini (base64 içinde düz URL) çevrimdışı çözer.

    Yeni (imzalı) biçimde URL baytları bulunmaz; bu durumda ``None`` döner ve çağıran taraf
    yönlendirme takibine geçer. Bu fonksiyon ağ erişimi yapmaz."""
    m = _GN_ARTICLE_RE.match(urlsplit(url).path)
    if not m:
        return None
    token = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    found = _URL_IN_BYTES_RE.search(raw)
    if not found:
        return None
    candidate = found.group(0)
    # protobuf alan ayırıcı baytları URL'ye karışmış olabilir: ilk kontrol baytına kadar kes
    candidate = re.split(rb"[\x00-\x20\x7f]", candidate, maxsplit=1)[0]
    try:
        return candidate.decode("ascii")
    except UnicodeDecodeError:
        return None


_GN_SIG_RE = re.compile(rb'data-n-a-sg="([^"]{8,400})"')
_GN_TS_RE = re.compile(rb'data-n-a-ts="(\d{6,13})"')
GN_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def gn_article_id(url: str) -> str | None:
    """``news.google.com/(rss/)articles/<id>`` bağlantısından makale kimliği."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != "news.google.com":
        return None
    m = _GN_ARTICLE_RE.match(parts.path)
    return m.group(1) if m else None


def gn_signature(page: bytes) -> tuple[str, str] | None:
    """İmzalı Google News sayfasından (imza, zaman damgası) çifti; yoksa ``None``."""
    sig, ts = _GN_SIG_RE.search(page), _GN_TS_RE.search(page)
    if not sig or not ts:
        return None
    return sig.group(1).decode("ascii", "ignore"), ts.group(1).decode("ascii")


def gn_batch_form(article_id: str, timestamp: str, signature: str) -> dict[str, str]:
    """``batchexecute`` (rpc ``Fbv4je``) için form gövdesi."""
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                                        None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        article_id, int(timestamp), signature], separators=(",", ":"))
    return {"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":"))}


def gn_parse_batch_response(text: str) -> str | None:
    """``batchexecute`` yanıtından yayıncı URL'sini çıkarır (yalnızca https). Bozuk yanıtta ``None``."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        for env in data if isinstance(data, list) else []:
            if not (isinstance(env, list) and len(env) > 2 and env[0] == "wrb.fr" and env[1] == "Fbv4je"
                    and isinstance(env[2], str)):
                continue
            try:
                inner = json.loads(env[2])
            except (json.JSONDecodeError, ValueError):
                return None
            if isinstance(inner, list) and len(inner) > 1 and inner[0] == "garturlres" and isinstance(inner[1], str):
                return inner[1] if inner[1].startswith("https://") else None
    return None


def clean_google_news_title(title: str) -> str:
    """Google News başlıklarının sonundaki " - Yayıncı" ekini kaldırır."""
    return _PUBLISHER_SUFFIX_RE.sub("", title).strip()


def google_news_source_url(item_el: Any) -> str:
    """Google News ``<source url="...">`` öğesinden yayıncı ana sayfasını döndürür."""
    for child in item_el:
        if child.tag == "source" or str(child.tag).endswith("}source"):
            return str(child.get("url") or "")
    return ""


# ---- HTML liste sayfası ------------------------------------------------------------------

class _AnchorCollector(HTMLParser):
    """Sayfadaki bağlantıları (href, metin) ve JSON-LD betiklerini toplar."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self.jsonld: list[str] = []
        self._href: str | None = None
        self._label: str = ""
        self._text: list[str] = []
        self._in_jsonld = False
        self._script: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """HTMLParser geri çağrısı: açılış etiketi."""
        a = {k: (v or "") for k, v in attrs}
        if tag == "a" and a.get("href"):
            self._href, self._text = a["href"], []
            self._label = a.get("aria-label") or a.get("title") or ""
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_jsonld, self._script = True, []

    def handle_endtag(self, tag: str) -> None:
        """HTMLParser geri çağrısı: kapanış etiketi."""
        if tag == "a" and self._href is not None:
            text = " ".join(self._text).strip() or self._label
            self.anchors.append((self._href, text))
            self._href = None
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._script))
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        """HTMLParser geri çağrısı: metin verisi."""
        if self._in_jsonld:
            self._script.append(data)
        elif self._href is not None:
            self._text.append(data)


def _walk_jsonld(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_jsonld(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_jsonld(v)


def parse_html_listing(content: bytes, base_url: str, link_pattern: str) -> list[dict[str, str]]:
    """Liste sayfasından makale girdileri çıkarır: ``{"title", "link", "summary", "published"}``.

    ``link_pattern`` bağlantının *yolu* (path) üzerinde aranır. Aynı bağlantı bir kez alınır.
    Başlıksız bağlantılar (yalnızca görsel) atlanır."""
    text = content.decode("utf-8", errors="replace")
    parser = _AnchorCollector()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # bozuk HTML: o ana kadar toplananlarla devam
        pass
    pattern = re.compile(link_pattern) if link_pattern else None
    seen: set[str] = set()
    entries: list[dict[str, str]] = []

    def add(href: str, title: str, published: str = "", summary: str = "") -> None:
        """Girdiyi (desene uyuyor ve tekrar değilse) ekler."""
        url = urljoin(base_url, href.strip())
        path = urlsplit(url).path
        title = strip_html(title)
        if not title or url in seen or (pattern and not pattern.search(path)):
            return
        seen.add(url)
        entries.append({"title": title, "link": url, "summary": strip_html(summary), "published": published})

    for script in parser.jsonld:
        try:
            data = json.loads(script)
        except (json.JSONDecodeError, ValueError):
            continue
        for obj in _walk_jsonld(data):
            href = obj.get("url") or obj.get("@id")
            title = obj.get("headline") or obj.get("name")
            if isinstance(href, str) and isinstance(title, str):
                add(href, title, str(obj.get("datePublished") or ""), str(obj.get("description") or ""))
    for href, title in parser.anchors:
        add(href, title)
    if pattern is not None and not entries:
        # İstemci tarafında çizilen sayfalar bağlantıları çoğu zaman gömülü JSON/betik içinde taşır:
        # desene uyan yolları yakala, başlığı adres kısaltmasından (slug) türet.
        for m in _EMBEDDED_PATH_RE.finditer(text):
            path = m.group(1).replace("\\/", "/")
            if pattern.search(path):
                add(path, slug_title(path))
    return entries


_EMBEDDED_PATH_RE = re.compile(r'["\']((?:\\)?/(?:[A-Za-z0-9_.~-]+(?:/|\\/)){1,6}[A-Za-z0-9_.~-]+)["\']')


def slug_title(path: str) -> str:
    """``/newswire/article/k1a2/grand-theft-auto-vi-trailer-3`` → ``Grand Theft Auto VI Trailer 3``."""
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    if not re.search(r"[a-z]-[a-z]", slug):
        return ""
    words = [w for w in slug.split("-") if w]
    roman = {"vi", "v", "iv", "iii", "ii", "gta", "gtavi"}
    return " ".join(w.upper() if w in roman else w.capitalize() for w in words)
