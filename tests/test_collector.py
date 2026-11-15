"""Kabul testi #2 (bozuk RSS izolasyonu) + canonicalization, alan adı, SSRF ve atıf zinciri."""
import socket

import pytest

from bot.collector import (FetchError, canonicalize_url, collect, detect_cited_origins, domain_allowed,
                           parse_feed, verify_source_url)
from tests.conftest import NOW, FakeResponse, rss


def test_canonicalize_url_strips_tracking_and_normalizes():
    a = canonicalize_url("http://WWW.IGN.com/articles/gta-6-trailer/?utm_source=x&b=2&a=1#top")
    b = canonicalize_url("https://ign.com/articles/gta-6-trailer?a=1&b=2&fbclid=zzz")
    assert a == b == "https://ign.com/articles/gta-6-trailer?a=1&b=2"
    assert canonicalize_url("javascript:alert(1)") == ""


def test_domain_allowed_requires_dot_boundary():
    assert domain_allowed("https://www.ign.com/x", ["ign.com"])
    assert domain_allowed("https://uk.ign.com/x", ["ign.com"])
    assert not domain_allowed("https://evilign.com/x", ["ign.com"])
    assert not domain_allowed("https://ign.com.evil.net/x", ["ign.com"])


def test_parse_feed_rejects_xxe_and_garbage():
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss><channel><item><title>&x;</title></item></channel></rss>'
    with pytest.raises(FetchError):
        parse_feed(xxe)
    with pytest.raises(FetchError):
        parse_feed(b"<html><body>not a feed")


def test_parse_atom_feed():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>GTA 6 news</title>
    <link rel="alternate" href="https://www.eurogamer.net/gta-6-news"/><summary>GTA 6 text</summary>
    <published>2026-11-16T09:00:00Z</published></entry></feed>"""
    entries = parse_feed(atom)
    assert entries[0]["link"] == "https://www.eurogamer.net/gta-6-news"


def test_broken_feed_does_not_stop_other_sources(settings, sources):
    """KABUL #2: Bozuk RSS kaynağı diğer kaynakları durdurmaz."""
    good = rss([{"title": "GTA 6 launch trailer gets new date details",
                 "link": "https://www.eurogamer.net/gta-6-trailer-date", "description": "GTA 6 trailer story"}])
    feeds = {
        sources[1].feed_url: b"<rss><channel><item><title>bozuk",          # IGN: bozuk XML
        sources[2].feed_url: good,                                         # Eurogamer: sağlam
    }

    def fetch(url):
        if url in feeds:
            return feeds[url]
        raise FetchError(__import__("bot").ErrorClass.NETWORK_TRANSIENT, "zaman aşımı")

    res = collect(sources, settings, session=None, now=NOW, fetch=fetch)
    assert res.source_status["ign"]["ok"] is False
    assert res.source_status["ign"]["error_class"] == "RSS_PARSE_ERROR"
    assert res.source_status["eurogamer"]["ok"] is True
    assert [i.source_id for i in res.items] == ["eurogamer"]
    assert res.sources_ok == 1 and res.sources_checked == len(sources)


def test_unexpected_exception_in_one_source_is_isolated(settings, sources):
    def fetch(url):
        if "eurogamer" in url:
            return rss([{"title": "GTA 6 map size discussed by developers",
                         "link": "https://www.eurogamer.net/gta-6-map", "description": "GTA 6"}])
        raise ZeroDivisionError("beklenmeyen")

    res = collect(sources, settings, session=None, now=NOW, fetch=fetch)
    assert len(res.items) == 1
    assert res.source_status["ign"]["error_class"] == "UNEXPECTED_ERROR"


def test_items_off_domain_old_or_irrelevant_are_dropped(settings, sources):
    feed = rss([
        {"title": "GTA 6 story on wrong domain", "link": "https://evil.example.com/gta-6"},
        {"title": "GTA 6 very old news item here", "link": "https://www.eurogamer.net/old",
         "pubDate": "Mon, 02 Nov 2026 10:00:00 GMT"},
        {"title": "Some other game news entirely", "link": "https://www.eurogamer.net/other"},
        {"title": "GTA 6 relevant fresh news item", "link": "https://www.eurogamer.net/fresh"},
    ])
    res = collect([sources[2]], settings, session=None, now=NOW, fetch=lambda u: feed)
    assert [i.url for i in res.items] == ["https://eurogamer.net/fresh"]


def test_cited_origin_detection(sources):
    text = "GTA 6 budget detailed, according to Bloomberg; via IGN"
    assert set(detect_cited_origins(text, sources, own_group="eurogamer")) == {"bloomberg", "ign"}
    assert detect_cited_origins("IGN reports on GTA 6", sources, own_group="ign") == []


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        return self.responses[url]


def _public_resolver(host, port, proto=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _private_resolver(host, port, proto=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]


def test_verify_source_url_follows_safe_redirect_and_checks_canonical(settings):
    s = _Session({
        "https://ign.com/a": FakeResponse(301, headers={"Location": "https://www.ign.com/articles/a"}),
        "https://www.ign.com/articles/a": FakeResponse(
            200, content=b'<html><head><link rel="canonical" href="https://www.ign.com/articles/a"></head>'),
    })
    ok, info = verify_source_url("https://ign.com/a", ["ign.com"], s, settings, resolver=_public_resolver)
    assert ok and info == "https://ign.com/articles/a"


def test_verify_source_url_blocks_redirect_to_other_domain_and_private_ip(settings):
    s = _Session({"https://ign.com/a": FakeResponse(302, headers={"Location": "http://169.254.169.254/latest"})})
    ok, _ = verify_source_url("https://ign.com/a", ["ign.com"], s, settings, resolver=_public_resolver)
    assert not ok
    ok, info = verify_source_url("https://ign.com/a", ["ign.com"], _Session({}), settings, resolver=_private_resolver)
    assert not ok and "genel IP" in info


def test_verify_source_url_rejects_foreign_canonical(settings):
    s = _Session({"https://ign.com/a": FakeResponse(
        200, content=b'<link rel="canonical" href="https://copycat.example.net/a">')})
    ok, info = verify_source_url("https://ign.com/a", ["ign.com"], s, settings, resolver=_public_resolver)
    assert not ok and "canonical" in info
