"""Otomatik haber görselleri: kaynağın kendi görseli (og:image / RSS media) yalnızca güvenli https ve
izinli ana makineden alınır; topluluk kaynaklarından alınmaz; Telegram önizlemesi kaynak sayfasından
büyük görselle gösterilir; site beslemesine yalnızca biçimi geçerli görsel yazılır."""
from __future__ import annotations

import socket

from bot.collector import collect, page_image, parse_feed, safe_image_url, verify_source_url
from bot.config import Source
from bot.site_exporter import build_item
from bot.telegram_client import TelegramClient
from tests.conftest import DUMMY_TELEGRAM_TOKEN, NOW, FakeResponse
from tests.test_publisher import CHAT, _Resp
from tests.test_site_exporter import post

RSS_MEDIA = b"""<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>GTA 6 launch trailer breakdown</title><link>https://www.ign.com/articles/gta-6-a</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate>
<media:content url="https://assets-prd.ignimgs.com/2026/11/16/gta6.jpg" medium="image"/></item>
<item><title>GTA 6 map leak</title><link>https://www.ign.com/articles/gta-6-b</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate>
<description>&lt;img src="https://assets-prd.ignimgs.com/x/inline.png"&gt; text</description></item>
<item><title>GTA 6 tracker pixel</title><link>https://www.ign.com/articles/gta-6-c</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate>
<enclosure url="https://evil.example.net/pixel.gif" type="image/gif"/></item>
</channel></rss>"""


def test_rss_media_extraction_and_host_allowlist(settings):
    entries = parse_feed(RSS_MEDIA)
    assert entries[0]["image"] == "https://assets-prd.ignimgs.com/2026/11/16/gta6.jpg"
    assert entries[1]["image"] == "https://assets-prd.ignimgs.com/x/inline.png"
    assert entries[2]["image"] == "https://evil.example.net/pixel.gif"
    src = Source(id="ign", name="IGN", trust_class="ESTABLISHED_MEDIA", feed_url="https://feeds.ign.com/x",
                 allowed_domains=["ign.com"], origin_group="ign")
    res = collect([src], settings, None, NOW, fetch=lambda u: RSS_MEDIA)
    imgs = {i.url.rsplit("/", 1)[-1]: i.image_url for i in res.items}
    assert imgs["gta-6-a"].startswith("https://assets-prd.ignimgs.com/")
    assert imgs["gta-6-c"] == ""                       # izinli olmayan ana makine reddedilir


def test_safe_image_url_rejects_unsafe_forms(settings):
    ok = "https://cdn.mos.cms.futurecdn.net/abc.jpg"
    assert safe_image_url(ok, ["gamesradar.com"], settings) == ok
    assert safe_image_url("//media-rockstargames-com.akamaized.net/a.jpg", [], settings).startswith("https://")
    for bad in ("http://cdn.mos.cms.futurecdn.net/a.jpg", "javascript:alert(1)", "https://u:p@ign.com/a.jpg",
                "https://ign.com:8443/a.jpg", 'https://ign.com/a".jpg', "https://futurecdn.net.evil.io/a.jpg",
                "data:image/png;base64,AAAA", "https://ign.com/" + "a" * 700):
        assert safe_image_url(bad, ["ign.com"], settings) == "", bad


def test_community_sources_never_provide_images(settings):
    feed = RSS_MEDIA.replace(b"https://www.ign.com", b"https://www.reddit.com")
    src = Source(id="reddit", name="r/GTA6", trust_class="COMMUNITY", feed_url="https://www.reddit.com/r/GTA6/.rss",
                 allowed_domains=["reddit.com", "ignimgs.com"], origin_group="reddit")
    res = collect([src], settings, None, NOW, fetch=lambda u: feed)
    assert res.items and all(i.image_url == "" for i in res.items)


def _public(host, port, proto=0):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_verified_page_exposes_og_image(settings):
    page = (b'<html><head><meta content="https://media-rockstargames-com.akamaized.net/vi/key.jpg" '
            b'property="og:image"><link rel="canonical" href="https://www.rockstargames.com/n/1"></head>')

    class S:
        def get(self, url, **kw):
            return FakeResponse(200, content=page)
    meta: dict[str, str] = {}
    ok, _ = verify_source_url("https://www.rockstargames.com/n/1", ["rockstargames.com"], S(), settings,
                              resolver=_public, meta=meta)
    assert ok and meta["image"] == "https://media-rockstargames-com.akamaized.net/vi/key.jpg"
    assert page_image(b'<meta name="twitter:image" content="/img/a.png">', "https://www.ign.com/x") == \
        "https://www.ign.com/img/a.png"
    assert page_image(b"<meta property='og:title' content='x'>", "https://ign.com") == ""


def test_telegram_preview_uses_source_page_with_large_media():
    sent = []

    class S:
        def post(self, url, json=None, timeout=None):
            sent.append(json)
            return _Resp(200, {"ok": True, "result": {"message_id": 1}})
    c = TelegramClient(DUMMY_TELEGRAM_TOKEN, session=S(), sleep=lambda d: None)
    c.send_message(CHAT, "x", preview_url="https://www.rockstargames.com/n/1")
    assert sent[-1]["link_preview_options"] == {"url": "https://www.rockstargames.com/n/1",
                                                "prefer_large_media": True, "show_above_text": True}
    c.send_message(CHAT, "x", disable_preview=True, preview_url="https://www.rockstargames.com/n/1")
    assert sent[-1]["link_preview_options"]["is_disabled"] is True


def test_site_feed_carries_only_well_formed_images(settings):
    good = post(1, image_url="https://media-rockstargames-com.akamaized.net/a.jpg", image_credit="Rockstar Newswire")
    item = build_item(good, settings, {})
    assert item is not None and item.image == good["image_url"] and item.image_credit == "Rockstar Newswire"
    for bad in ('https://x.com/a.jpg" onerror="alert(1)', "javascript:alert(1)", 42):
        it = build_item(post(2, image_url=bad), settings, {})
        assert it is not None and it.image is None
    assert build_item(post(3), settings, {}).image is None     # eski kayıtlar geriye uyumlu
