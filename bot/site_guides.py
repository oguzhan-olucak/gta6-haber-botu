"""Rehber sayfaları (EN + TR), yasal sayfalar ve reklam yuvaları.

* ``config/guides.json`` → ``docs/guides/<slug>.html`` (İngilizce) ve ``docs/tr/rehber/<slug>.html`` (Türkçe),
  ayrıca iki dizin sayfası. Her sayfa birbirine ``hreflang`` ile bağlanır; ``FAQPage`` + ``Article`` JSON-LD taşır.
* Bot her çalışmada sayfaları yeniden üretir: ``topics`` kelimeleriyle eşleşen yayınlanmış haberler
  "Latest news / Son haberler" bölümüne kendiliğinden eklenir (rehberler kendini günceller).
* Reklam: sayfalarda sabit yükseklikli ``.ad-slot`` yuvaları vardır; ``assets/ads.js`` yalnızca
  ``monetization.json → ads.adsense_client`` doluysa AdSense'i yükler. Boşken yuvalar gizlidir.
* Gizlilik/çerez, hakkında/iletişim sayfaları AdSense başvurusu ve KVKK/GDPR için üretilir.

Tüm metin ``html.escape`` ile kaçırılır; bağlantılar yalnızca ``https://``.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .site_exporter import Feed
from .site_pages import base_url, page_csp
from .storage import write_text_if_changed
from .textutil import normalize_text

_SLUG = r"^[a-z0-9-]{3,80}$"
_HTTPS = r"^https://[^\s<>\"'\\]{4,600}$"

class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=60)
    url: str = Field(pattern=_HTTPS)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    h: str = Field(max_length=120)
    p: list[str] = Field(default_factory=list, max_length=8)
    bullets: list[str] = Field(default_factory=list, max_length=12, alias="list")


class Faq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(max_length=200)
    a: str = Field(max_length=600)


class Lang(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=_SLUG)
    title: str = Field(max_length=110)
    description: str = Field(max_length=200)
    kicker: str = Field(max_length=40)
    answer: str = Field(max_length=600)
    sections: list[Section] = Field(default_factory=list, max_length=10)
    faq: list[Faq] = Field(default_factory=list, max_length=8)


class Guide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]{2,40}$")
    updated: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    topics: list[str] = Field(default_factory=list, max_length=30)
    sources: list[Source] = Field(min_length=1, max_length=8)
    en: Lang
    tr: Lang


class GuideFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    guides: list[Guide] = Field(default_factory=list, max_length=40)


def load_guides(path: Path) -> list[Guide]:
    if not path.exists():
        return []
    return GuideFile.model_validate(json.loads(path.read_text(encoding="utf-8"))).guides


UI = {
    "en": {"home": "Home", "guides": "Guides", "news": "Latest news", "sources": "Sources", "faq": "FAQ",
           "updated": "Updated", "answer": "Short answer", "ad": "Advertisement", "join": "Join the Telegram channel",
           "join_sub": "Verified GTA 6 news the moment it breaks.", "other": "More guides", "lang": "Türkçe",
           "privacy": "Privacy & cookies", "about": "About & contact", "map": "Leonida map",
           "disclaimer": "An independent fan site. Not affiliated with Rockstar Games or Take-Two Interactive.",
           "no_news": "No related news yet. This section updates automatically.",
           "hub_title": "GTA 6 guides: file size, release time, price, cheats and settings",
           "hub_desc": "Fact-checked GTA 6 guides that update automatically as verified news comes in.",
           "hub_h1": "GTA 6 guides"},
    "tr": {"home": "Ana sayfa", "guides": "Rehberler", "news": "Son haberler", "sources": "Kaynaklar", "faq": "SSS",
           "updated": "Güncellendi", "answer": "Kısa cevap", "ad": "Reklam", "join": "Telegram kanalına katıl",
           "join_sub": "Doğrulanmış GTA 6 haberleri düştüğü anda.", "other": "Diğer rehberler", "lang": "English",
           "privacy": "Gizlilik ve çerezler", "about": "Hakkında ve iletişim", "map": "Leonida haritası",
           "disclaimer": "Bağımsız bir hayran sitesidir; Rockstar Games veya Take-Two Interactive ile bağlantılı değildir.",
           "no_news": "Henüz ilgili haber yok. Bu bölüm kendiliğinden güncellenir.",
           "hub_title": "GTA 6 rehberleri: boyut, çıkış saati, fiyat, hileler ve ayarlar",
           "hub_desc": "Doğrulanmış haber geldikçe kendiliğinden güncellenen GTA 6 rehberleri.",
           "hub_h1": "GTA 6 rehberleri"},
}
DIRS = {"en": "guides", "tr": "tr/rehber"}
LEGAL = {"en": {"privacy": "privacy.html", "about": "about.html"}, "tr": {"privacy": "tr/gizlilik.html", "about": "tr/hakkinda.html"}}


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def guide_path(lang: str, slug: str) -> str:
    return f"{DIRS[lang]}/{slug}.html"


def _rel(from_path: str, to_path: str) -> str:
    depth = from_path.count("/")
    return "../" * depth + to_path


def related_news(feed: Feed, guide: Guide, limit: int = 5) -> list[Any]:
    keys = [normalize_text(t).lower() for t in guide.topics if t.strip()]
    out = []
    for it in feed.items:
        hay = " " + normalize_text(f"{it.title} {it.summary} {it.title_en or ''} {it.summary_en or ''}").lower() + " "
        if any((" " + k) in hay for k in keys):
            out.append(it)
        if len(out) >= limit:
            break
    return out


def ad_slot(name: str, lang: str, tall: bool = False) -> str:
    return (f'<div class="ad-slot{" ad-slot--tall" if tall else ""}" data-slot="{_e(name)}" hidden>'
            f'<span class="ad-slot__label">{_e(UI[lang]["ad"])}</span></div>')


def _head(path: str, lang: str, title: str, desc: str, site_url: str, alt: dict[str, str], og_image: str,
          json_ld: str = "") -> str:
    base = base_url(site_url)
    canon = base + path if base else ""
    alts = "".join(f'<link rel="alternate" hreflang="{_e(lg)}" href="{_e(base + p)}">' for lg, p in alt.items()) if base else ""
    if base and "en" in alt:
        alts += f'<link rel="alternate" hreflang="x-default" href="{_e(base + alt["en"])}">'
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{_e(page_csp())}">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{_e(title)}</title>
<meta name="description" content="{_e(desc)}">
<meta name="theme-color" content="#15132E">
<meta property="og:type" content="article"><meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}"><meta property="og:image" content="{_e(og_image)}">
<meta name="twitter:card" content="summary_large_image">
{f'<link rel="canonical" href="{_e(canon)}"><meta property="og:url" content="{_e(canon)}">' if canon else ''}
{alts}
<link rel="icon" href="{_rel(path, 'assets/icon.svg')}" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800;900&amp;family=Manrope:wght@500;600;700;800&amp;display=swap">
<link rel="stylesheet" href="{_rel(path, 'assets/guide.css')}">
{json_ld}
</head>
<body>
"""


def _bar(path: str, lang: str, other_href: str | None) -> str:
    u = UI[lang]
    home = _rel(path, "index.html" if lang == "en" else "index.html")
    hub = _rel(path, f"{DIRS[lang]}/index.html")
    other = f'<a class="bar__lang" href="{_e(other_href)}" hreflang="{"tr" if lang == "en" else "en"}">{u["lang"]}</a>' if other_href else ""
    return (f'<header class="bar"><a class="bar__brand" href="{home}"><b>GTA</b> <span>Türkiye Bülteni</span></a>'
            f'<nav class="bar__nav" aria-label="Menu"><a href="{home}#harita">{u["map"]}</a><a href="{hub}">{u["guides"]}</a>{other}</nav></header>'
            '<div class="band">' + ("Pre-load open · Unlocks Nov 19, midnight local time" if lang == "en"
                                    else "Ön yükleme açık · 19 Kasım 00.00'da açılıyor") + "</div>")


def _foot(path: str, lang: str) -> str:
    u = UI[lang]
    lg = LEGAL[lang]
    return (f'<footer class="foot"><p>{_e(u["disclaimer"])}</p><p><a href="{_rel(path, lg["privacy"])}">{_e(u["privacy"])}</a> · '
            f'<a href="{_rel(path, lg["about"])}">{_e(u["about"])}</a> · <a href="{_rel(path, "rss.xml")}">RSS</a></p></footer>'
            f'<script src="{_rel(path, "data/monetization.js")}"></script><script src="{_rel(path, "assets/ads.js")}"></script>'
            "</body></html>\n")


def _tg(money: dict[str, Any], lang: str) -> str:
    tg = money.get("telegram")
    if not tg:
        return ""
    u = UI[lang]
    return (f'<a class="tg" href="{_e(tg["url"])}" rel="noopener" target="_blank"><b>{_e(u["join"])}</b>'
            f'<span>{_e(u["join_sub"])}</span><em>{_e(tg["handle"])}</em></a>')


def render_guide(g: Guide, lang: str, feed: Feed, guides: list[Guide], *, site_url: str, money: dict[str, Any]) -> str:
    L: Lang = getattr(g, lang)
    other_lang = "tr" if lang == "en" else "en"
    path = guide_path(lang, L.slug)
    other_path = guide_path(other_lang, getattr(g, other_lang).slug)
    base = base_url(site_url)
    og = base + "assets/og-default.png" if base else ""
    u = UI[lang]
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage",
              "mainEntity": [{"@type": "Question", "name": f.q, "acceptedAnswer": {"@type": "Answer", "text": f.a}}
                             for f in L.faq]}
    art_ld = {"@context": "https://schema.org", "@type": "Article", "headline": L.title[:110], "description": L.description,
              "dateModified": g.updated, "inLanguage": "en" if lang == "en" else "tr-TR",
              "isBasedOn": [s.url for s in g.sources]}
    ld = "".join('<script type="application/ld+json">' + json.dumps(x, ensure_ascii=False).replace("<", "\\u003c")
                 + "</script>" for x in (art_ld, faq_ld) if x.get("mainEntity", True))
    body = []
    for i, s in enumerate(L.sections):
        body.append(f"<h2>{_e(s.h)}</h2>" + "".join(f"<p>{_e(p)}</p>" for p in s.p)
                    + (("<ul>" + "".join(f"<li>{_e(x)}</li>" for x in s.bullets) + "</ul>") if s.bullets else ""))
        if i == 0:
            body.append(ad_slot("guide-mid", lang))
    news = related_news(feed, g)
    news_html = "".join(
        f'<li><a href="{_e(_rel(path, f"haber/{it.id}.html"))}">{_e((it.title_en if lang == "en" and it.title_en else it.title))}</a>'
        f'<small>{_e(it.label_text if lang == "tr" else it.trust_group.title())} · {_e(it.published_at[:10])}</small></li>'
        for it in news) or f'<li class="muted">{_e(u["no_news"])}</li>'
    faq_html = "".join(f"<details><summary>{_e(f.q)}</summary><p>{_e(f.a)}</p></details>" for f in L.faq)
    srcs = "".join(f'<li><a href="{_e(s.url)}" rel="noopener" target="_blank">{_e(s.name)}</a></li>' for s in g.sources)
    others = "".join(f'<a href="{_e(_rel(path, guide_path(lang, getattr(o, lang).slug)))}">{_e(getattr(o, lang).title)}</a>'
                     for o in guides if o.id != g.id)
    return (_head(path, lang, L.title, L.description, site_url, {"en": guide_path("en", g.en.slug), "tr": guide_path("tr", g.tr.slug)}, og, ld)
            + _bar(path, lang, _rel(path, other_path))
            + f'<main class="wrap"><article class="doc"><p class="kicker">{_e(L.kicker)}</p><h1>{_e(L.title)}</h1>'
            f'<p class="meta">{_e(u["updated"])}: {_e(g.updated)}</p>'
            f'<div class="answer"><b>{_e(u["answer"])}</b><p>{_e(L.answer)}</p></div>'
            + ad_slot("guide-top", lang) + "".join(body)
            + f'<h2>{_e(u["news"])}</h2><ul class="news">{news_html}</ul>'
            + (f'<h2>{_e(u["faq"])}</h2>{faq_html}' if faq_html else "")
            + _tg(money, lang)
            + f'<h2>{_e(u["sources"])}</h2><ul class="src">{srcs}</ul>' + ad_slot("guide-end", lang)
            + f'</article><aside class="side">{ad_slot("guide-side", lang, tall=True)}<nav class="others" aria-label="{_e(u["other"])}"><b>{_e(u["other"])}</b>{others}</nav></aside></main>'
            + _foot(path, lang))


def render_hub(lang: str, guides: list[Guide], *, site_url: str, money: dict[str, Any]) -> str:
    u = UI[lang]
    path = f"{DIRS[lang]}/index.html"
    base = base_url(site_url)
    cards = "".join(
        f'<a class="card card--{i % 6}" href="{_e(getattr(g, lang).slug)}.html"><small>{_e(getattr(g, lang).kicker)}</small>'
        f'<b>{_e(getattr(g, lang).title)}</b><span>{_e(getattr(g, lang).description)}</span></a>'
        for i, g in enumerate(guides))
    return (_head(path, lang, u["hub_title"], u["hub_desc"], site_url,
                  {"en": "guides/index.html", "tr": "tr/rehber/index.html"}, base + "assets/og-default.png" if base else "")
            + _bar(path, lang, _rel(path, f"{DIRS['tr' if lang == 'en' else 'en']}/index.html"))
            + f'<main class="wrap wrap--hub"><h1 class="hub">{_e(u["hub_h1"])}</h1><p class="lead">{_e(u["hub_desc"])}</p>'
            f'{ad_slot("hub-top", lang)}<div class="cards">{cards}</div>{_tg(money, lang)}</main>' + _foot(path, lang))


LEGAL_TEXT = {
    "en": {
        "privacy": ("Privacy & cookies", [
            ("What we collect", "This site has no accounts and no forms. We do not collect your name, email or other personal data."),
            ("Advertising cookies", "We show ads through Google AdSense. Google and its partners may use cookies to show ads based on your visits to this and other sites. Visitors in the EEA, UK and Switzerland are asked for consent through Google's certified consent message. You can opt out of personalised ads at https://adssettings.google.com."),
            ("Hosting", "The site is served as static files by GitHub Pages, which may log technical data such as IP addresses for security."),
            ("Contact", "Questions about privacy: open an issue at https://github.com/oguzhan-olucak/gta6-haber-botu/issues."),
        ]),
        "about": ("About & contact", [
            ("What this is", "An independent fan news site about Grand Theft Auto VI. A bot checks official channels and major games media, labels each story by how well it is sourced, and summarises it in English and Turkish."),
            ("How stories are labelled", "Official: from Rockstar or Take-Two. Multi-source: two or more independent outlets. Single source: one outlet. Claim: reported but unconfirmed. Every story links to its sources."),
            ("Not affiliated", "Grand Theft Auto, GTA and Rockstar Games are trademarks of Take-Two Interactive. This site is not affiliated with or endorsed by them."),
            ("Contact", "Corrections and questions: https://github.com/oguzhan-olucak/gta6-haber-botu/issues"),
        ]),
    },
    "tr": {
        "privacy": ("Gizlilik ve çerezler", [
            ("Topladığımız veriler", "Bu sitede hesap ya da form yoktur. Adınızı, e-postanızı veya başka bir kişisel verinizi toplamayız."),
            ("Reklam çerezleri", "Reklamlar Google AdSense ile gösterilir. Google ve iş ortakları, bu ve diğer sitelere yaptığınız ziyaretlere göre reklam göstermek için çerez kullanabilir. Kişiselleştirilmiş reklamlardan https://adssettings.google.com adresinden çıkabilirsiniz. 6698 sayılı KVKK kapsamındaki haklarınız için aşağıdaki iletişim kanalını kullanabilirsiniz."),
            ("Barındırma", "Site, GitHub Pages tarafından statik dosya olarak sunulur; GitHub güvenlik amacıyla IP adresi gibi teknik verileri kaydedebilir."),
            ("İletişim", "Gizlilikle ilgili sorular: https://github.com/oguzhan-olucak/gta6-haber-botu/issues"),
        ]),
        "about": ("Hakkında ve iletişim", [
            ("Bu site nedir?", "Grand Theft Auto VI hakkında bağımsız bir hayran haber sitesi. Bir bot resmî kanalları ve büyük oyun basınını tarar, her haberi kaynağının gücüne göre etiketler ve İngilizce ile Türkçe özetler."),
            ("Etiketler", "Resmî: Rockstar veya Take-Two kaynaklı. Çoklu kaynak: iki veya daha fazla bağımsız yayın. Tek kaynak: tek yayın. İddia: bildirilen ama doğrulanmayan. Her haber kaynaklarına bağlanır."),
            ("Bağlantı yok", "Grand Theft Auto, GTA ve Rockstar Games, Take-Two Interactive'in ticari markalarıdır. Bu site onlarla bağlantılı değildir ve onlar tarafından desteklenmez."),
            ("İletişim", "Düzeltme ve sorular: https://github.com/oguzhan-olucak/gta6-haber-botu/issues"),
        ]),
    },
}

_URL_RE = re.compile(r"(https://[A-Za-z0-9./?=_%-]+)")


def _linkify(text: str) -> str:
    return _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" rel="noopener" target="_blank">{m.group(1)}</a>', _e(text))


def render_legal(lang: str, kind: str, *, site_url: str) -> str:
    title, blocks = LEGAL_TEXT[lang][kind]
    path = LEGAL[lang][kind]
    other = LEGAL["tr" if lang == "en" else "en"][kind]
    body = "".join(f"<h2>{_e(h)}</h2><p>{_linkify(t)}</p>" for h, t in blocks)
    return (_head(path, lang, title + " · GTA Türkiye Bülteni", title, site_url, {"en": LEGAL["en"][kind], "tr": LEGAL["tr"][kind]}, "")
            + _bar(path, lang, _rel(path, other))
            + f'<main class="wrap wrap--hub"><article class="doc"><h1>{_e(title)}</h1>{body}</article></main>' + _foot(path, lang))


def all_paths(guides: list[Guide]) -> list[str]:
    out = ["guides/index.html", "tr/rehber/index.html"]
    for g in guides:
        out += [guide_path("en", g.en.slug), guide_path("tr", g.tr.slug)]
    return out + [p for lg in LEGAL.values() for p in lg.values()]


def export_guides(feed: Feed, docs: Path, guides: list[Guide], *, site_url: str, money: dict[str, Any]) -> int:
    changed = 0
    for lang in ("en", "tr"):
        for g in guides:
            changed += write_text_if_changed(docs / guide_path(lang, getattr(g, lang).slug),
                                             render_guide(g, lang, feed, guides, site_url=site_url, money=money))
        changed += write_text_if_changed(docs / DIRS[lang] / "index.html", render_hub(lang, guides, site_url=site_url, money=money))
        for kind in ("privacy", "about"):
            changed += write_text_if_changed(docs / LEGAL[lang][kind], render_legal(lang, kind, site_url=site_url))
    client = (money.get("ads") or {}).get("client", "")
    if client:
        changed += write_text_if_changed(docs / "ads.txt", f"google.com, {client.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    return changed
