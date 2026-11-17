"""Statik SEO ve paylaşım katmanı: her haber için kendi adresi olan sayfa, ``sitemap.xml`` ve ``rss.xml``.

Neden: Ana site tek sayfalık bir uygulama; haber bağlantıları ``#haber-<id>`` biçiminde olduğu için
arama motorları haberleri ayrı sayfa olarak indeksleyemez, WhatsApp/X/Telegram paylaşımlarında da
haberin görseli çıkmaz. Bu modül her yayınlanmış haber için ``docs/haber/<id>.html`` üretir:

* ``<title>``, açıklama, ``canonical``, Open Graph / Twitter kartı (``og:image`` = kaynağın kendi
  basın görseli; yoksa sitenin varsayılan kapağı) ve ``NewsArticle`` JSON-LD.
* JavaScript gerektirmez (CSP: betik yok); tüm dinamik metin ``html.escape`` ile kaçırılır, bağlantılar
  ``FeedItem`` şemasında zaten yalnızca ``https://``.
* Gelir bileşenleri (sponsor, bağlam içi Lansman Kiti, Telegram katılım çağrısı) sunucu tarafında,
  yalnızca ``monetization.public_payload`` içinde etkin olanlar için basılır.

Eski haber sayfaları silinmez (kırık bağlantı = kaybedilen arama trafiği); ``sitemap.xml`` mevcut
tüm haber sayfalarını listeler.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from . import parse_iso
from .monetization import kit_for_text
from .site_exporter import Feed, FeedItem
from .storage import write_text_if_changed

ADS_CSP = ("https://pagead2.googlesyndication.com https://*.googlesyndication.com https://*.doubleclick.net "
           "https://*.google.com https://*.gstatic.com https://*.adtrafficquality.google https://fundingchoicesmessages.google.com")


def page_csp(with_ads: bool = True) -> str:
    ads = f" {ADS_CSP}" if with_ads else ""
    return ("default-src 'self'; "
            f"script-src 'self'{ads}; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
            f"img-src 'self' data: https:; connect-src 'self'{ads}; frame-src https://www.youtube-nocookie.com{ads}; "
            "base-uri 'none'; form-action 'none'; object-src 'none'")


ARTICLE_DIR = "haber"
DEFAULT_OG = "assets/og-default.png"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
           "Kasım", "Aralık")
TRUST_CLASS = {"official": "official", "multi": "multi", "single": "single", "claim": "claim"}


def _e(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def base_url(site_url: str) -> str:
    return site_url.rstrip("/") + "/" if site_url else ""


def article_path(item_id: str) -> str:
    if not _ID_RE.fullmatch(item_id):
        raise ValueError("geçersiz haber id")
    return f"{ARTICLE_DIR}/{item_id}.html"


def article_url(site_url: str, item_id: str) -> str | None:
    """Haberin kalıcı sayfa adresi; ``site_url`` ayarlı değilse None."""
    if not site_url or not _ID_RE.fullmatch(item_id):
        return None
    return base_url(site_url) + article_path(item_id)


def tr_date(iso_str: str, offset_hours: int) -> str:
    d = parse_iso(iso_str)
    if not d:
        return ""
    loc = d.astimezone(timezone.utc) + timedelta(hours=offset_hours)
    return f"{loc.day} {_MONTHS[loc.month - 1]} {loc.year}, {loc:%H:%M}"


def _json_ld(item: FeedItem, url: str, image: str, brand: str, site: str) -> str:
    data = {
        "@context": "https://schema.org", "@type": "NewsArticle", "headline": item.title[:110],
        "description": item.summary[:300], "datePublished": item.published_at, "dateModified": item.published_at,
        "image": [image], "mainEntityOfPage": url, "inLanguage": "tr-TR",
        "author": {"@type": "Organization", "name": brand, "url": site},
        "publisher": {"@type": "Organization", "name": brand, "url": site},
        "isBasedOn": [s.url for s in item.sources],
    }
    raw = json.dumps(data, ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _kit_block(items: list[dict[str, Any]], kit: dict[str, Any], heading: str) -> str:
    cards = []
    for i in items:
        meta = " · ".join(x for x in (i.get("partner"), i.get("price_hint")) if x)
        cards.append(
            f'<a class="kit__item" href="{_e(i["url"])}" rel="sponsored noopener" target="_blank">'
            f'<b>{_e(i["title"])}</b><span>{_e(i.get("why"))}</span>'
            + (f'<small>{_e(meta)}</small>' if meta else "") + "</a>")
    return (f'<section class="kit glass" aria-label="{_e(heading)}"><p class="eyebrow">İşbirliği · {_e(heading)}</p>'
            f'<div class="kit__grid">{"".join(cards)}</div><p class="fine">{_e(kit["disclosure"])}</p></section>')


def render_article(item: FeedItem, *, site_url: str, brand: str, offset_hours: int,
                   money: dict[str, Any]) -> str:
    base = base_url(site_url)
    url = article_url(site_url, item.id) or ""
    image = item.image or (base + DEFAULT_OG if base else "")
    desc = item.summary[:200] or item.title
    when = tr_date(item.published_at, offset_hours)
    trust = TRUST_CLASS.get(item.trust_group, "single")
    sources = "".join(f'<li><a href="{_e(s.url)}" rel="noopener" target="_blank">{_e(s.name)}</a></li>'
                      for s in item.sources)
    media = ""
    if item.image:
        credit = item.image_credit or "kaynak"
        media = (f'<figure class="art__media"><img src="{_e(item.image)}" alt="" referrerpolicy="no-referrer" '
                 f'decoding="async" width="1200" height="675"><figcaption>Görsel: {_e(credit)}</figcaption></figure>')
    else:
        media = (f'<figure class="art__media art__media--empty" data-region="{_e(item.location_id or "vice_city")}">'
                 f'<span>{_e(item.region or "Leonida")}</span></figure>')
    tg = money.get("telegram")
    sponsor = money.get("sponsor")
    kit = money.get("kit")
    blocks: list[str] = []
    if sponsor:
        blocks.append(f'<a class="sponsorbar glass" href="{_e(sponsor["url"])}" rel="sponsored noopener" target="_blank">'
                      f'<span class="eyebrow">Sponsor</span><b>{_e(sponsor["name"])}</b>'
                      f'<span>{_e(sponsor.get("tagline"))}</span></a>')
    if kit:
        related = kit_for_text(money, f"{item.title} {item.summary}")
        if related:
            blocks.append(_kit_block(related, kit, "Bu haberle ilgili"))
    if tg:
        blocks.append(f'<a class="tgcta glass" href="{_e(tg["url"])}" rel="noopener" target="_blank">'
                      f'<span class="tgcta__icon" aria-hidden="true"></span><span><b>Telegram kanalına katıl</b>'
                      f'<small>{_e(tg["cta"])}</small></span><span class="tgcta__go">{_e(tg["handle"])}</span></a>')
    tg_post = (f'<a class="btn" href="{_e(item.telegram_url)}" rel="noopener" target="_blank">Telegram gönderisi</a>'
               if item.telegram_url else "")
    share = "https://t.me/share/url?url=" + _e(_q(url)) + "&amp;text=" + _e(_q(item.title)) if url else ""
    head_extra = ""
    if url:
        head_extra += f'<link rel="canonical" href="{_e(url)}">\n<meta property="og:url" content="{_e(url)}">\n'
    if image:
        head_extra += (f'<meta property="og:image" content="{_e(image)}">\n'
                       f'<meta name="twitter:image" content="{_e(image)}">\n')
    if base:
        head_extra += f'<link rel="alternate" type="application/rss+xml" title="{_e(brand)}" href="{_e(base)}rss.xml">\n'
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{_e(page_csp())}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{_e(item.title)} · {_e(brand)}</title>
<meta name="description" content="{_e(desc)}">
<meta name="theme-color" content="#07080d">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{_e(brand)}">
<meta property="og:locale" content="tr_TR">
<meta property="og:title" content="{_e(item.title)}">
<meta property="og:description" content="{_e(desc)}">
<meta property="article:published_time" content="{_e(item.published_at)}">
<meta name="twitter:card" content="summary_large_image">
{head_extra}<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&amp;family=Plus+Jakarta+Sans:wght@400;500;600;700;800&amp;display=swap">
<link rel="icon" href="../assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../assets/article.css">
<script type="application/ld+json">{_json_ld(item, url, image, brand, base)}</script>
</head>
<body>
<header class="bar"><a class="bar__brand" href="../">← <b>GTA VI</b> Türkiye Bülteni</a>
<a class="bar__map" href="../#haber-{_e(item.id)}">Haritada gör</a></header>
<main class="art">
{media}
<div class="art__body glass">
<p class="art__badges"><span class="badge badge--{trust}">{_e(item.label_text)}</span><span class="chip">{_e(item.category_tr)}</span><span class="chip">{_e(item.region or "")}</span></p>
<h1>{_e(item.title)}</h1>
<p class="art__meta"><time datetime="{_e(item.published_at)}">{_e(when)}</time></p>
<p class="art__lead">{_e(item.summary)}</p>
<div class="ad-slot" data-slot="article-mid" hidden><span class="ad-slot__label">Reklam</span></div>
<div class="art__why"><b>Neden bu etiket?</b><p>{_e(item.why_this_label)}</p></div>
<div class="art__src"><b>Kaynaklar</b><ul>{sources}</ul></div>
<p class="art__actions"><a class="btn btn--glow" href="../#haber-{_e(item.id)}">Leonida haritasında aç</a>{tg_post}{f'<a class="btn" href="{share}" rel="noopener" target="_blank">Paylaş</a>' if share else ""}</p>
</div>
{"".join(blocks)}
</main>
<footer class="foot"><p>{_e(brand)} bağımsız bir hayran bültenidir; Rockstar Games veya Take-Two Interactive ile bağlantılı değildir. Özet yapay zekâ ile kaynaklardan üretilir ve kural tabanlı denetimden geçer; ayrıntı için kaynak bağlantılarına bakın.</p>
<p><a href="../">Ana sayfa</a> · <a href="../tr/rehber/index.html">Rehberler</a> · <a href="../guides/index.html">English guides</a> · <a href="../tr/gizlilik.html">Gizlilik</a> · <a href="../rss.xml">RSS</a></p></footer>
<script src="../data/monetization.js"></script><script src="../assets/ads.js"></script>
</body>
</html>
"""


def _q(text: str) -> str:
    from urllib.parse import quote
    return quote(text, safe="")


def render_sitemap(site_url: str, pages: list[tuple[str, str]]) -> str:
    base = base_url(site_url)
    rows = [f"  <url><loc>{xml_escape(base)}</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>"]
    for path, lastmod in pages:
        rows.append(f"  <url><loc>{xml_escape(base + path)}</loc>"
                    + (f"<lastmod>{xml_escape(lastmod)}</lastmod>" if lastmod else "") + "</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def _rfc822(iso_str: str) -> str:
    d = parse_iso(iso_str)
    return d.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000") if d else ""


def render_rss(feed: Feed, site_url: str, brand: str, now: datetime) -> str:
    base = base_url(site_url)
    items = []
    for it in feed.items[:30]:
        link = article_url(site_url, it.id) or base
        items.append(
            "    <item>"
            f"<title>{xml_escape(it.title)}</title><link>{xml_escape(link)}</link>"
            f'<guid isPermaLink="true">{xml_escape(link)}</guid><pubDate>{_rfc822(it.published_at)}</pubDate>'
            f"<category>{xml_escape(it.label_text)}</category><description>{xml_escape(it.summary)}</description>"
            "</item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            f"  <channel><title>{xml_escape(brand)}</title><link>{xml_escape(base)}</link>"
            f'<atom:link href="{xml_escape(base + "rss.xml")}" rel="self" type="application/rss+xml"/>'
            "<description>Kaynağı doğrulanmış Türkçe GTA VI haberleri</description><language>tr-tr</language>"
            f"<lastBuildDate>{now.astimezone(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>\n"
            + "\n".join(items) + "\n  </channel>\n</rss>\n")


def _write_if_different(path: Path, text: str) -> bool:
    return write_text_if_changed(path, text)


def export_site_pages(feed: Feed, docs_dir: Path, *, site_url: str, brand: str, offset_hours: int,
                      money: dict[str, Any], now: datetime, extra_paths: list[str] | None = None) -> int:
    """Haber sayfaları + sitemap + rss; değişen dosya sayısını döner. ``site_url`` yoksa yalnız sayfalar."""
    changed = 0
    if feed.demo:
        return 0
    for item in feed.items:
        page = render_article(item, site_url=site_url, brand=brand, offset_hours=offset_hours, money=money)
        changed += _write_if_different(docs_dir / article_path(item.id), page)
    if not site_url:
        return changed
    known = {it.id: it.published_at for it in feed.items}
    pages = []
    for f in sorted((docs_dir / ARTICLE_DIR).glob("*.html")) if (docs_dir / ARTICLE_DIR).exists() else []:
        if _ID_RE.fullmatch(f.stem):
            pages.append((article_path(f.stem), (known.get(f.stem) or "")[:10]))
    pages.sort(key=lambda p: p[1], reverse=True)
    pages = [(p, "") for p in (extra_paths or [])] + pages
    changed += _write_if_different(docs_dir / "sitemap.xml", render_sitemap(site_url, pages))
    rss = render_rss(feed, site_url, brand, now)
    old = (docs_dir / "rss.xml").read_text(encoding="utf-8") if (docs_dir / "rss.xml").exists() else ""
    if re.sub(r"<lastBuildDate>.*?</lastBuildDate>", "", old) != re.sub(r"<lastBuildDate>.*?</lastBuildDate>", "", rss):
        changed += _write_if_different(docs_dir / "rss.xml", rss)
    return changed
