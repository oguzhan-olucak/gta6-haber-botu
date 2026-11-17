"""Gelir altyapısı ve SEO katmanı: monetization.json doğrulaması (varsayılan kapalı, şeffaflık zorunlu,
yalnızca https), Telegram sponsor/site satırları, statik haber sayfaları (XSS, OG etiketleri, betiksiz CSP),
sitemap/rss ve tam bot çalışması entegrasyonu."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from bot.labels import Label
from bot.monetization import (
    Monetization,
    export_monetization,
    js_wrap,
    kit_for_text,
    load_monetization,
    public_payload,
    sponsor_line,
)
from bot.publisher import render_post
from bot.site_exporter import build_feed
from bot.site_pages import article_url, export_site_pages, render_article, render_rss, render_sitemap
from tests.conftest import NOW
from tests.test_arena import _content
from tests.test_publisher import FakeGenerator, FakeTelegram, go, items, make_env
from tests.test_site_exporter import SOURCES, post

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 17)
SITE = "https://oguzhan-olucak.github.io/gta6-haber-botu/"


def _money(**over):
    base = {
        "telegram_channel": "@gta6turkiye",
        "sponsor": {"enabled": True, "name": "Örnek E-pin", "tagline": "PSN kodu anında", "url": "https://ornek.test/p",
                    "starts": "2026-11-15", "ends": "2026-11-30"},
        "kit": {"enabled": True, "disclosure": "İşbirliği: satış ortaklığı bağlantısı.",
                "items": [{"id": "ssd", "title": "SSD", "why": "Yer aç", "url": "https://shop.test/ssd?aff=1",
                           "topics": ["boyut", "gb"]},
                          {"id": "kol", "title": "Kol", "url": ""}]},
        "media_kit": {"contact_telegram": "@reklamci"},
    }
    base.update(over)
    return Monetization.model_validate(base)


# ---- yapılandırma ------------------------------------------------------------------------------

def test_shipped_config_is_valid_and_everything_is_off_by_default():
    m, err = load_monetization(ROOT / "config" / "monetization.json")
    assert err is None
    payload = public_payload(m, TODAY)
    assert set(payload) == {"schema_version", "media_kit"}          # sponsor/kit/telegram/destek kapalı
    assert sponsor_line(m, TODAY) is None


def test_missing_or_broken_file_disables_monetization_without_crashing(tmp_path):
    m, err = load_monetization(tmp_path / "yok.json")
    assert err is None and public_payload(m, TODAY) == {"schema_version": 1, "media_kit": {"contact": {}, "price_note": ""}}
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps({"sponsor": {"enabled": True, "name": "X", "url": "http://duz-http.test"}}))
    m, err = load_monetization(bad)
    assert err and "kapalı" in err and "sponsor" not in public_payload(m, TODAY)
    bad.write_text("{bozuk")
    assert load_monetization(bad)[1]


def test_sponsor_respects_date_window_and_requires_url():
    m = _money()
    assert public_payload(m, TODAY)["sponsor"]["name"] == "Örnek E-pin"
    assert "sponsor" not in public_payload(m, date(2026, 12, 1))
    assert "sponsor" not in public_payload(m, date(2026, 11, 14))
    m2 = _money(sponsor={"enabled": True, "name": "X", "url": ""})
    assert "sponsor" not in public_payload(m2, TODAY)


def test_kit_needs_disclosure_and_hides_items_without_link():
    payload = public_payload(_money(), TODAY)
    assert [i["id"] for i in payload["kit"]["items"]] == ["ssd"]     # url'siz ürün görünmez
    no_disc = _money(kit={"enabled": True, "disclosure": "", "items": [{"id": "ssd", "title": "SSD",
                                                                          "url": "https://shop.test/x"}]})
    assert "kit" not in public_payload(no_disc, TODAY)


def test_contextual_kit_matching():
    payload = public_payload(_money(), TODAY)
    assert [i["id"] for i in kit_for_text(payload, "GTA VI ön yükleme boyutu 210 GB olarak listelendi")] == ["ssd"]
    assert kit_for_text(payload, "Lucia'nın seslendirmeni konuştu") == []


def test_payload_text_is_sanitized_and_js_is_script_safe():
    m = _money(sponsor={"enabled": True, "name": "<b>X</b>", "tagline": "</script><script>alert(1)</script>",
                        "url": "https://ornek.test"})
    p = public_payload(m, TODAY)
    assert "<" not in p["sponsor"]["name"] and "<script" not in p["sponsor"]["tagline"]
    js = js_wrap({"a": "</script>"}, "__GTA6_MONETIZATION__")
    assert "</script>" not in js and js.startswith("window.__GTA6_MONETIZATION__ = ")


def test_export_monetization_is_idempotent(tmp_path):
    payload = public_payload(_money(), TODAY)
    assert export_monetization(payload, tmp_path) is True
    assert export_monetization(payload, tmp_path) is False
    assert (tmp_path / "monetization.js").read_text().startswith("window.__GTA6_MONETIZATION__")


# ---- Telegram ----------------------------------------------------------------------------------

def test_telegram_post_gets_site_link_and_labelled_sponsor_line(settings):
    sp = sponsor_line(_money(), TODAY)
    text = render_post(_content("RELEASE_PLATFORMS"), Label.SINGLE_SOURCE,
                       [{"name": "IGN", "url": "https://ign.com/a"}], settings, NOW,
                       site_link=SITE + "haber/abc123.html", sponsor=sp)
    assert f'<a href="{SITE}haber/abc123.html">' in text
    assert "<i>Sponsor:</i>" in text and "https://ornek.test/p" in text
    assert text.index("Doğrulama") < text.index("Sponsor")       # haber önce, sponsor en sonda
    plain = render_post(_content("RELEASE_PLATFORMS"), Label.SINGLE_SOURCE,
                        [{"name": "IGN", "url": "https://ign.com/a"}], settings, NOW,
                        site_link="javascript:alert(1)", sponsor=None)
    assert "javascript:" not in plain and "Sponsor" not in plain


def test_long_post_with_extras_stays_under_telegram_limit(settings):
    c = _content("OTHER")
    c = c.model_copy(update={"summary_tr": "uzun " * 900})
    srcs = [{"name": f"Kaynak {i}", "url": f"https://ign.com/{i}"} for i in range(40)]
    text = render_post(c, Label.MULTI_SOURCE, srcs, settings, NOW, site_link=SITE + "haber/x1234.html",
                       sponsor=("S", "t" * 140, "https://s.test"))
    assert len(text) <= 4096


# ---- statik haber sayfaları -----------------------------------------------------------------------

def test_article_page_has_seo_tags_and_escapes_everything(settings):
    p = post(1, title_tr="GTA VI <script>alert(1)</script> ön yükleme 210 GB", image_url="https://ign.com/i.jpg",
             image_credit="IGN")
    feed = build_feed({"posts": [p]}, {}, settings, SOURCES, NOW)
    item = feed.items[0]
    html = render_article(item, site_url=SITE, brand="GTA VI Türkiye Bülteni", offset_hours=3,
                          money=public_payload(_money(), TODAY))
    import re as _re
    body_scripts = _re.findall(r"<script[^>]*>", html.split("<body>")[1])
    assert "<script>alert" not in html
    assert body_scripts == ['<script src="../data/monetization.js">', '<script src="../assets/ads.js">']
    assert f'<link rel="canonical" href="{SITE}haber/{item.id}.html">' in html
    assert '<meta property="og:image" content="https://ign.com/i.jpg">' in html
    assert "script-src &#x27;self&#x27; https://pagead2" in html and '"@type": "NewsArticle"' in html
    assert 'rel="sponsored noopener"' in html and "İşbirliği" in html     # bağlam içi kit, ibareli
    assert "Sponsor" in html and "t.me/gta6turkiye" in html


def test_article_without_image_uses_default_cover(settings):
    feed = build_feed({"posts": [post(2)]}, {}, settings, SOURCES, NOW)
    html = render_article(feed.items[0], site_url=SITE, brand="B", offset_hours=3, money={})
    assert f'content="{SITE}assets/og-default.png"' in html and "art__media--empty" in html
    assert "Sponsor" not in html and "kit__item" not in html


def test_sitemap_and_rss(settings, tmp_path):
    feed = build_feed({"posts": [post(1), post(2)]}, {}, settings, SOURCES, NOW)
    n = export_site_pages(feed, tmp_path, site_url=SITE, brand="B & C", offset_hours=3, money={}, now=NOW)
    assert n == 4 and (tmp_path / "haber" / "cid00001.html").exists()
    sm = (tmp_path / "sitemap.xml").read_text()
    assert sm.count("<url>") == 3 and f"<loc>{SITE}haber/cid00002.html</loc>" in sm
    rss = (tmp_path / "rss.xml").read_text()
    assert "B &amp; C" in rss and rss.count("<item>") == 2
    assert export_site_pages(feed, tmp_path, site_url=SITE, brand="B & C", offset_hours=3, money={}, now=NOW) == 0
    assert render_sitemap(SITE, []).count("<url>") == 1 and "<rss" in render_rss(feed, SITE, "B", NOW)
    assert article_url("", "cid00001") is None and article_url(SITE, "../../etc") is None


# ---- tam bot çalışması ----------------------------------------------------------------------------

def test_bot_run_generates_pages_monetization_and_linked_posts(tmp_path):
    cfg, data, session = make_env(tmp_path, items(2), site_url=SITE)
    (cfg / "monetization.json").write_text(json.dumps(_money().model_dump(mode="json")), encoding="utf-8")
    tg = FakeTelegram()
    code, summary = go(cfg, data, session, tg, FakeGenerator())
    docs = tmp_path / "docs"
    assert code == 0 and len(tg.channel_posts) == 2
    pages = sorted((docs / "haber").glob("*.html"))
    assert len(pages) == 2 and (docs / "sitemap.xml").exists() and (docs / "rss.xml").exists()
    money = json.loads((docs / "data" / "monetization.json").read_text())
    assert money["sponsor"]["name"] == "Örnek E-pin" and money["telegram"]["handle"] == "@gta6turkiye"
    first = tg.channel_posts[0]
    text = first["text"] if isinstance(first, dict) else str(first)
    assert f"{SITE}haber/" in text and "Sponsor:" in text
