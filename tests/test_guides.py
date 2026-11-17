"""Rehber motoru: gönderilen içerik geçerli, iki dilli sayfalar + hreflang, otomatik ilgili haberler,
reklam yuvaları kimlik yokken gizli, ads.txt yalnızca kimlik varsa, XSS kaçışı, site haritası."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from bot.monetization import Monetization, public_payload
from bot.site_exporter import build_feed
from bot.site_guides import all_paths, export_guides, load_guides, related_news, render_guide
from tests.conftest import NOW
from tests.test_site_exporter import SOURCES, post

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://oguzhan-olucak.github.io/gta6-haber-botu/"


def _guides():
    return load_guides(ROOT / "config" / "guides.json")


def test_shipped_guides_are_valid_bilingual_and_sourced():
    gs = _guides()
    assert len(gs) >= 6
    for g in gs:
        assert g.en.slug != g.tr.slug and g.sources and g.en.answer and g.tr.answer
    assert len(set(all_paths(gs))) == len(all_paths(gs))


def test_guide_pages_link_languages_and_pull_related_news(settings, tmp_path):
    p = post(1, title_tr="GTA 6 ön yükleme boyutu 212 GB olarak açıklandı")
    feed = build_feed({"posts": [p, post(2)]}, {}, settings, SOURCES, NOW)
    gs = _guides()
    size = next(g for g in gs if g.id == "file-size")
    assert [i.id for i in related_news(feed, size)] == ["cid00001"]
    n = export_guides(feed, tmp_path, gs, site_url=SITE, money={})
    assert n >= len(gs) * 2 + 2 + 4
    en = (tmp_path / "guides" / f"{size.en.slug}.html").read_text()
    assert f'hreflang="tr" href="{SITE}tr/rehber/{size.tr.slug}.html"' in en
    assert 'hreflang="x-default"' in en and '"@type": "FAQPage"' in en
    assert "../haber/cid00001.html" in en
    assert 'class="ad-slot"' in en and 'data-slot="guide-top" hidden' in en
    assert not (tmp_path / "ads.txt").exists()
    for name in ("privacy.html", "about.html", "tr/gizlilik.html", "tr/hakkinda.html", "guides/index.html", "tr/rehber/index.html"):
        assert (tmp_path / name).exists()
    assert export_guides(feed, tmp_path, gs, site_url=SITE, money={}) == 0     # değişmediyse yazmaz


def test_ads_txt_and_payload_only_with_client(settings, tmp_path):
    m = Monetization.model_validate({"ads": {"adsense_client": "ca-pub-1234567890123456", "slots": {"guide-top": "1234567"}}})
    money = public_payload(m, date(2026, 11, 17))
    assert money["ads"] == {"client": "ca-pub-1234567890123456", "auto": True, "slots": {"guide-top": "1234567"}}
    feed = build_feed({"posts": []}, {}, settings, SOURCES, NOW)
    export_guides(feed, tmp_path, _guides(), site_url=SITE, money=money)
    assert (tmp_path / "ads.txt").read_text() == "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n"


def test_guide_text_is_escaped(settings):
    g = _guides()[0].model_copy(deep=True)
    g.en.title = "<script>alert(1)</script>"
    feed = build_feed({"posts": []}, {}, settings, SOURCES, NOW)
    html = render_guide(g, "en", feed, [g], site_url=SITE, money={})
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_bot_run_writes_guides_and_sitemap_lists_them(tmp_path):
    from tests.test_publisher import FakeGenerator, FakeTelegram, go, items, make_env
    cfg, data, session = make_env(tmp_path, items(1), site_url=SITE)
    (cfg / "guides.json").write_text((ROOT / "config" / "guides.json").read_text(encoding="utf-8"), encoding="utf-8")
    code, _ = go(cfg, data, session, FakeTelegram(), FakeGenerator())
    docs = tmp_path / "docs"
    assert code == 0 and (docs / "guides" / "gta-6-cheat-codes.html").exists()
    sm = (docs / "sitemap.xml").read_text()
    assert f"{SITE}guides/gta-6-cheat-codes.html" in sm and f"{SITE}tr/rehber/gta-6-hile-kodlari.html" in sm
    json.loads((docs / "data" / "feed.json").read_text())
