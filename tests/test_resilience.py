"""Faz 2: bozuk UTF-8 / Türkçe karakter, uzun metin kırpma, veri dosyası kurtarma, saat dilimi limitleri
ve resmî kaynak (Google News / HTML liste) doğrulaması."""
import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from bot import main as bot_main
from bot.collector import collect, parse_feed
from bot.config import Source
from bot.official import clean_google_news_title, decode_google_news_offline, is_google_news_url, parse_html_listing
from bot.publisher import posts_today, render_post
from bot.storage import CorruptDataError, lastgood_path, read_json_recovering, write_json_atomic
from bot.textutil import fix_mojibake, normalize_text, strip_html, tr_upper, truncate
from tests.conftest import NOW, rss
from tests.test_publisher import FakeGenerator, FakeTelegram, go, items, make_env

# ---- UTF-8 / Türkçe -----------------------------------------------------------------------


def test_invalid_utf8_bytes_in_feed_are_repaired_not_fatal():
    good = rss([{"title": "GTA 6 haberi: çığ öğüş", "link": "https://www.eurogamer.net/a"}])
    broken = good.replace("çığ".encode(), b"\xff\xfe\xc3")  # geçersiz UTF-8 dizisi
    entries = parse_feed(broken)
    assert entries and entries[0]["link"] == "https://www.eurogamer.net/a"
    assert "öğüş" in entries[0]["title"]


def test_windows_1254_declared_feed_parses_turkish():
    xml = ('<?xml version="1.0" encoding="windows-1254"?><rss><channel><item><title>GTA 6 şımarık ığdır'
           '</title><link>https://www.eurogamer.net/b</link></item></channel></rss>').encode("cp1254")
    assert parse_feed(xml)[0]["title"] == "GTA 6 şımarık ığdır"


def test_mojibake_is_repaired():
    assert fix_mojibake("GTA 6 Ä±ÅŸÄ±k ve Ã§ark") == "GTA 6 ışık ve çark"
    assert fix_mojibake("Düz Türkçe metin ğüşiöç") == "Düz Türkçe metin ğüşiöç"


def test_invisible_and_bidi_characters_are_stripped():
    text = strip_html("GTA​ 6‮ kcatta‬ <b>haber</b>\x00")
    assert "​" not in text and "‮" not in text and "\x00" not in text and "haber" in text


def test_turkish_upper_and_normalize():
    assert tr_upper("oynanış & teknoloji") == "OYNANIŞ & TEKNOLOJİ"
    assert normalize_text("İstanbul'da IŞIK") == "istanbul da isik"


# ---- Kırpma ------------------------------------------------------------------------------------


def test_truncate_respects_limit_and_word_boundary():
    t = truncate("kelime " * 200, 50)
    assert len(t) <= 50 and t.endswith("…") and not t[:-1].endswith(" ")
    assert truncate("kısa", 50) == "kısa"
    assert len(truncate("x" * 500, 10)) == 10


def test_overlong_feed_fields_are_safely_truncated(settings, sources):
    huge = "GTA 6 " + ("çok uzun özet metni " * 5000)
    feed = rss([{"title": "GTA 6 " + "başlık " * 400, "link": "https://www.eurogamer.net/long", "description": huge}])
    res = collect([sources[2]], settings, session=None, now=NOW, fetch=lambda u: feed)
    it = res.items[0]
    assert len(it.title) <= 300 and len(it.summary) <= settings.content_limits.source_text_max_chars


def test_rendered_post_never_exceeds_telegram_limit(settings):
    from bot.processor import GeneratedContent, Label
    c = GeneratedContent(title_tr="GTA VI " + "ş" * 100, summary_tr="ğ" * 470, category="OTHER",
                         title_style="FACTUAL", claim_type="REPORTED", source_urls=["https://ign.com/a"],
                         why_this_label="t", needs_review=False)
    src = [{"name": "Kaynak & <adı> " * 20, "url": "https://ign.com/a?" + "x=1&" * 300}] * 3
    assert len(render_post(c, Label.MULTI_SOURCE, src, settings, NOW)) <= 4096


# ---- Veri dosyası kurtarma ---------------------------------------------------------------------


def test_half_written_state_is_recovered_from_last_good(tmp_path):
    p = tmp_path / "state.json"
    write_json_atomic(p, {"seen_items": {"a": 1}}, keep_last_good=True)
    p.write_text('{"seen_items": {"a": 1', encoding="utf-8")  # yarım yazılmış
    data, err = read_json_recovering(p, dict)
    assert data == {"seen_items": {"a": 1}} and err is not None
    assert json.loads(p.read_text()) == {"seen_items": {"a": 1}}  # ana dosya onarıldı
    assert list(tmp_path.glob("state.json.corrupt.*.bak"))


def test_both_main_and_last_good_corrupt_raises(tmp_path):
    p = tmp_path / "history.json"
    p.write_text("{", encoding="utf-8")
    lastgood_path(p).write_text("[", encoding="utf-8")
    with pytest.raises(CorruptDataError):
        read_json_recovering(p, dict)


def test_end_to_end_corrupt_history_auto_recovers_and_keeps_dedup(tmp_path):
    cfg, data, session = make_env(tmp_path, items(1))
    tg, gen = FakeTelegram(), FakeGenerator()
    go(cfg, data, session, tg, gen)
    assert len(tg.channel_posts) == 1
    (data / "history.json").write_text('{"posts": [', encoding="utf-8")       # bozuldu
    code, s = go(cfg, data, session, tg, gen, now=NOW + timedelta(minutes=20))
    assert code == 0 and "history.json" in s["recovered"]
    assert len(tg.channel_posts) == 1  # kurtarılan geçmiş sayesinde tekrar yayın yok
    assert any("kurtarıldı" in m["text"] for m in tg.admin_msgs)


def test_end_to_end_corrupt_state_without_backup_is_safe_mode(tmp_path):
    cfg, data, session = make_env(tmp_path, items(1))
    (data / "state.json").write_text("{bozuk", encoding="utf-8")
    code, s = go(cfg, data, session, FakeTelegram(), FakeGenerator())
    assert code == 2 and s["safe_mode"]


# ---- Saat dilimi / günlük limit ---------------------------------------------------------------


def _post_at(dt):
    return {"publish_status": "PUBLISHED", "published_at": dt.astimezone(timezone.utc).isoformat()}


def test_calendar_limit_resets_at_trt_midnight_not_utc(settings):
    trt = timezone(timedelta(hours=3))
    history = {"posts": [_post_at(datetime(2026, 11, 16, 23, 30, tzinfo=trt))]}   # TRT 23:30 = UTC 20:30
    assert posts_today(history, datetime(2026, 11, 16, 23, 50, tzinfo=trt), settings) == 1
    assert posts_today(history, datetime(2026, 11, 17, 0, 10, tzinfo=trt), settings) == 0  # TRT gece yarısı
    # UTC gece yarısı (TRT 03:00) yeni günü başlatmaz: TRT 02:00 ve 04:00 aynı yerel gün
    history2 = {"posts": [_post_at(datetime(2026, 11, 17, 2, 0, tzinfo=trt))]}
    assert posts_today(history2, datetime(2026, 11, 17, 4, 0, tzinfo=trt), settings) == 1


def test_rolling_mode_counts_last_24_hours(settings):
    settings.daily_limit_mode = "rolling_24h"
    trt = timezone(timedelta(hours=3))
    history = {"posts": [_post_at(datetime(2026, 11, 16, 23, 30, tzinfo=trt))]}
    assert posts_today(history, datetime(2026, 11, 17, 0, 10, tzinfo=trt), settings) == 1
    assert posts_today(history, datetime(2026, 11, 17, 23, 31, tzinfo=trt), settings) == 0


def test_end_to_end_limit_resets_after_trt_midnight(tmp_path):
    cfg, data, session = make_env(tmp_path, items(4), max_daily_posts=1)
    tg, gen = FakeTelegram(), FakeGenerator()
    late = datetime(2026, 11, 16, 20, 40, tzinfo=timezone.utc)          # TRT 23:40
    go(cfg, data, session, tg, gen, now=late)
    go(cfg, data, session, tg, gen, now=late + timedelta(minutes=10))  # TRT 23:50 — limit dolu
    assert len(tg.channel_posts) == 1
    go(cfg, data, session, tg, gen, now=late + timedelta(minutes=30))  # TRT 00:10 — yeni gün
    assert len(tg.channel_posts) == 2


# ---- Resmî kaynaklar --------------------------------------------------------------------------


def _legacy_gn_url(target: str) -> str:
    payload = b"\x08\x13\"" + bytes([len(target)]) + target.encode() + b"\xd2\x01\x00"
    return "https://news.google.com/rss/articles/" + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_google_news_legacy_link_decodes_offline():
    url = _legacy_gn_url("https://www.rockstargames.com/newswire/article/abc/gta-vi")
    assert is_google_news_url(url)
    assert decode_google_news_offline(url) == "https://www.rockstargames.com/newswire/article/abc/gta-vi"
    assert decode_google_news_offline("https://news.google.com/rss/articles/CBMiAU_yqLsignedopaque") is None


def test_google_news_title_suffix_removed():
    assert clean_google_news_title("Grand Theft Auto VI Trailer 3 - Rockstar Games") == "Grand Theft Auto VI Trailer 3"


def _gn_source(**kw):
    base = dict(id="rockstar_gn", name="Rockstar Games", trust_class="OFFICIAL", kind="google_news",
                feed_url="https://news.google.com/rss/search?q=site:rockstargames.com", allowed_domains=["rockstargames.com"],
                origin_group="rockstar")
    base.update(kw)
    return Source(**base)


def _gn_feed(link, source_url="https://www.rockstargames.com"):
    return (f'<rss><channel><item><title>Grand Theft Auto VI Launch Trailer - Rockstar Games</title><link>{link}</link>'
            f'<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate><source url="{source_url}">Rockstar Games</source>'
            '</item></channel></rss>').encode()


def test_google_news_official_item_requires_verified_official_final_url(settings):
    link = "https://news.google.com/rss/articles/CBMiAU_yqLsignedopaque"
    calls = []

    def verifier_ok(url, allowed, hops):
        calls.append((url, tuple(hops)))
        return True, "https://rockstargames.com/newswire/article/abc/gta-vi"

    res = collect([_gn_source()], settings, None, NOW, fetch=lambda u: _gn_feed(link), verifier=verifier_ok)
    it = res.items[0]
    assert it.url_verified and it.url == "https://rockstargames.com/newswire/article/abc/gta-vi"
    assert calls[0][1] == ("news.google.com",)

    def verifier_offsite(url, allowed, hops):
        return True, "https://fan-site.example.com/gta-vi"      # yönlendirme resmî alan adı dışına çıktı

    assert collect([_gn_source()], settings, None, NOW, fetch=lambda u: _gn_feed(link),
                   verifier=verifier_offsite).items == []
    assert collect([_gn_source()], settings, None, NOW, fetch=lambda u: _gn_feed(link), verifier=None).items == []


def test_google_news_item_from_non_official_publisher_is_dropped(settings):
    feed = _gn_feed("https://news.google.com/rss/articles/x", source_url="https://www.gta-fans.example.net")
    res = collect([_gn_source()], settings, None, NOW, fetch=lambda u: feed, verifier=lambda *a: (True, "x"))
    assert res.items == []


def test_html_listing_parser_extracts_matching_articles():
    page = b"""<html><body>
      <a href="/newswire/article/k1a2/grand-theft-auto-vi-launch-trailer">Grand Theft Auto VI Launch Trailer</a>
      <a href="/newswire/article/z9/gta-online-weekly"><img src="x.jpg"></a>
      <a href="/careers">Careers</a>
      <script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"@type":"NewsArticle",
        "url":"https://www.rockstargames.com/newswire/article/q7/grand-theft-auto-vi-preload",
        "headline":"Grand Theft Auto VI Preload Now Live","datePublished":"2026-11-12T00:00:00Z"}]}</script>
    </body></html>"""
    entries = parse_html_listing(page, "https://www.rockstargames.com/newswire", r"^/newswire/article/")
    links = [e["link"] for e in entries]
    assert "https://www.rockstargames.com/newswire/article/k1a2/grand-theft-auto-vi-launch-trailer" in links
    assert "https://www.rockstargames.com/newswire/article/q7/grand-theft-auto-vi-preload" in links
    assert all("careers" not in l for l in links) and len(entries) == 2


def test_html_listing_official_end_to_end_gets_official_label(tmp_path):
    cfg, data, session = make_env(tmp_path, [])
    srcs = json.loads((cfg / "sources.json").read_text())
    srcs["sources"].append({"id": "rockstar_html", "name": "Rockstar Newswire", "trust_class": "OFFICIAL",
                            "kind": "html_listing", "feed_url": "https://www.rockstargames.com/newswire",
                            "link_pattern": "^/newswire/article/", "allowed_domains": ["rockstargames.com"],
                            "origin_group": "rockstar"})
    (cfg / "sources.json").write_text(json.dumps(srcs))
    session.feeds["https://www.rockstargames.com/newswire"] = (
        b'<a href="/newswire/article/k1/grand-theft-auto-vi-launch-trailer">Grand Theft Auto VI Launch Trailer</a>')
    tg = FakeTelegram()
    code, s = bot_main.run(now=NOW, env=__import__("tests.test_publisher", fromlist=["ENV"]).ENV, session=session,
                           telegram=tg, generator=FakeGenerator(), data_dir=data, config_dir=cfg,
                           url_verifier=lambda u, a, h: (True, u))
    assert code == 0 and len(tg.channel_posts) == 1
    assert "🟩 <b>RESMÎ AÇIKLAMA</b>" in tg.channel_posts[0]["text"]


def test_empty_html_listing_is_reported_not_crashing(settings):
    src = Source(id="rs", name="Rockstar Newswire", trust_class="OFFICIAL", kind="html_listing",
                 feed_url="https://www.rockstargames.com/newswire", link_pattern="^/newswire/article/",
                 allowed_domains=["rockstargames.com"], origin_group="rockstar")
    res = collect([src], settings, None, NOW, fetch=lambda u: b"<div id='root'></div>", verifier=lambda *a: (True, ""))
    assert res.source_status["rs"]["ok"] and "boş" in res.source_status["rs"]["warning"]
