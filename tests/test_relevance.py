"""Kaynak yakalama düzeltmeleri: genişletilmiş GTA VI ilgi filtresi, kaynak başına yaş sınırı,
tanılama sayaçları, imzalı Google News çözümü ve istemci tarafında çizilen liste sayfası."""
from __future__ import annotations

import json
import socket

import pytest

from bot.collector import collect, is_relevant, verify_source_url
from bot.config import Source
from bot.official import (
    gn_article_id,
    gn_batch_form,
    gn_parse_batch_response,
    gn_signature,
    parse_html_listing,
    slug_title,
)
from tests.conftest import NOW, FakeResponse, rss


@pytest.mark.parametrize("title", [
    "GTA 6 gets a new trailer", "GTA VI preload is live", "Grand Theft Auto VI: The Final Trailer",
    "Grand Theft Auto 6 release date confirmed", "Rockstar shares GTA 6’s Leonida map", "#GTA6 hype",
    "Leonida awaits: new screenshots", "GTAVI file size revealed",
])
def test_strong_terms_and_variants_are_relevant(settings, title):
    assert is_relevant(title, "", settings)


def test_specific_terms_need_brand_or_official_source(settings):
    assert is_relevant("Vice City returns in new Rockstar screenshots", "", settings)
    assert is_relevant("Lucia and Jason star in the new Rockstar Games trailer", "", settings)
    assert is_relevant("Jason and Lucia: a closer look", "", settings, official=True)
    assert not is_relevant("Jason Momoa joins new film", "", settings)          # marka yok
    assert not is_relevant("Lucia's cafe opens in Miami", "", settings)


def test_exclusions_apply_only_without_strong_term(settings):
    assert not is_relevant("GTA Vice City Definitive Edition patch from Rockstar", "", settings)
    assert not is_relevant("GTA Online weekly update: Vice City nightclub, Rockstar says", "", settings)
    assert not is_relevant("Red Dead Redemption 2 hits new milestone for Rockstar", "", settings, official=True)
    assert is_relevant("GTA 6 vs GTA 5: Vice City compared", "", settings)


def _official_src(**kw):
    base = dict(id="rockstar", name="Rockstar Newswire", trust_class="OFFICIAL",
                feed_url="https://www.rockstargames.com/feed.xml", allowed_domains=["rockstargames.com"],
                origin_group="rockstar")
    base.update(kw)
    return Source(**base)


def test_official_source_has_longer_age_window_and_counts_matches(settings):
    old = "Tue, 10 Nov 2026 10:00:00 GMT"   # ~6 gün önce: 48 saatten eski, 168 saatten yeni
    feed = rss([{"title": "Grand Theft Auto VI: new screenshots", "link": "https://www.rockstargames.com/n/1",
                 "pubDate": old},
                {"title": "Red Dead Online bonuses", "link": "https://www.rockstargames.com/n/2", "pubDate": old}])
    ok = lambda url, allowed, hops: (True, url)  # noqa: E731 - sahte doğrulayıcı
    short = collect([_official_src()], settings, None, NOW, fetch=lambda u: feed, verifier=ok)
    assert short.source_status["rockstar"]["relevant"] == 1 and short.source_status["rockstar"]["new"] == 0
    longer = collect([_official_src(max_item_age_hours=168)], settings, None, NOW, fetch=lambda u: feed, verifier=ok)
    assert len(longer.items) == 1 and longer.source_status["rockstar"]["new"] == 1


def test_gn_helpers_parse_signed_page_and_batch_response():
    page = b'<c-wiz><div jscontroller="x" data-n-a-sg="AU_yqLsig123456" data-n-a-ts="1763290000"></div></c-wiz>'
    assert gn_signature(page) == ("AU_yqLsig123456", "1763290000")
    assert gn_signature(b"<html></html>") is None
    assert gn_article_id("https://news.google.com/rss/articles/CBMiXYZ?oc=5") == "CBMiXYZ"
    assert gn_article_id("https://evil.example/rss/articles/CBMiXYZ") is None
    form = gn_batch_form("CBMiXYZ", "1763290000", "AU_yqLsig123456")
    req = json.loads(form["f.req"])
    assert req[0][0][0] == "Fbv4je" and "CBMiXYZ" in req[0][0][1] and "AU_yqLsig123456" in req[0][0][1]
    inner = json.dumps(["garturlres", "https://www.rockstargames.com/newswire/article/k1/gta-vi", 1])
    body = ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"]]) + "\n"
    assert gn_parse_batch_response(body) == "https://www.rockstargames.com/newswire/article/k1/gta-vi"
    bad = json.dumps(["garturlres", "javascript:alert(1)", 1])
    assert gn_parse_batch_response(json.dumps([["wrb.fr", "Fbv4je", bad]])) is None
    assert gn_parse_batch_response("garbage") is None


class _GNSession:
    """news.google.com imzalı sayfası → batchexecute → Rockstar makalesi."""

    def __init__(self, target):
        self.target = target
        self.posts = []

    def get(self, url, **kw):
        if url.startswith("https://news.google.com/rss/articles/"):
            return FakeResponse(200, content=b'<div data-n-a-sg="AU_yqLsig123456" data-n-a-ts="1763290000"></div>')
        if url == self.target:
            return FakeResponse(200, content=f'<link rel="canonical" href="{self.target}">'.encode())
        raise AssertionError(url)

    def post(self, url, data=None, **kw):
        self.posts.append(url)
        inner = json.dumps(["garturlres", self.target, 1])
        return FakeResponse(200, content=(")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner]])).encode())


def _public(host, port, proto=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_verify_resolves_signed_google_news_to_official_url(settings):
    target = "https://www.rockstargames.com/newswire/article/k1/gta-vi"
    s = _GNSession(target)
    ok, final = verify_source_url("https://news.google.com/rss/articles/CBMiSigned?oc=5", ["rockstargames.com"], s,
                                  settings, hop_domains=["news.google.com"], resolver=_public)
    assert ok and final == "https://rockstargames.com/newswire/article/k1/gta-vi"
    assert s.posts == ["https://news.google.com/_/DotsSplashUi/data/batchexecute"]


def test_signed_google_news_pointing_to_foreign_domain_is_rejected(settings):
    s = _GNSession("https://copycat.example.net/gta-vi")
    ok, _ = verify_source_url("https://news.google.com/rss/articles/CBMiSigned", ["rockstargames.com"], s,
                              settings, hop_domains=["news.google.com"], resolver=_public)
    assert not ok


def test_client_rendered_listing_falls_back_to_embedded_paths():
    page = (b'<html><body><div id="root"></div><script>window.__DATA__={"posts":[{"url":"'
            b'/newswire/article/k1a2/grand-theft-auto-vi-the-final-trailer"},{"url":"\\/newswire\\/article\\/z9\\/'
            b'gta-online-weekly-bonuses"},{"url":"/careers/open-roles"}]}</script></body></html>')
    entries = parse_html_listing(page, "https://www.rockstargames.com/newswire", r"^/newswire/article/")
    titles = {e["title"]: e["link"] for e in entries}
    assert titles["Grand Theft Auto VI The Final Trailer"] == \
        "https://www.rockstargames.com/newswire/article/k1a2/grand-theft-auto-vi-the-final-trailer"
    assert "GTA Online Weekly Bonuses" in titles and len(entries) == 2
    assert slug_title("/newswire/article/abc123") == ""
