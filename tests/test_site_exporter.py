"""Aşama 4: site beslemesi (docs/data/feed.json + feed.js) — şema, XSS temizliği, gizli veri sızıntısı,
manşet/vitrin seçimi, atomik yazım ve bot hattı entegrasyonu."""
import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from bot.config import Source
from bot.site_exporter import (
    CATEGORY_TR,
    Feed,
    FeedItem,
    build_feed,
    build_item,
    clean_text,
    export_site_feed,
    feed_js,
    pick_hero,
    safe_url,
    telegram_url,
)
from tests.conftest import DUMMY_GEMINI_KEY, DUMMY_TELEGRAM_TOKEN, NOW
from tests.test_publisher import CHAT, FakeGenerator, FakeTelegram, go, items, make_env


def post(i=1, **over):
    p = {"publish_status": "PUBLISHED", "label": "MULTI_SOURCE", "content_id": f"cid{i:05d}",
         "title_tr": f"GTA VI haberi {i}", "summary_tr": "Kısa özet metni.", "category": "TRAILER_MEDIA",
         "title_style": "FACTUAL", "published_at": (NOW - timedelta(hours=i)).isoformat(),
         "source_urls": ["https://ign.com/a", "https://eurogamer.net/b"], "source_names": {"https://ign.com/a": "IGN"},
         "why_this_label": "2 bağımsız yayın: IGN, Eurogamer", "source_strength": 75, "editorial_priority": 70,
         "independent_origins": ["ign", "eurogamer"], "chat_id": CHAT, "message_id": 42 + i,
         "content_hashes": ["deadbeef"], "source_titles": ["Original EN title"], "publish_error": None,
         "metrics": {"views": "unavailable", "forwards": "unavailable", "reaction_snapshots": []}}
    p.update(over)
    return p


SOURCES = [Source(id="ign", name="IGN", trust_class="ESTABLISHED_MEDIA", feed_url="https://x.test/f",
                  allowed_domains=["ign.com"], origin_group="ign"),
           Source(id="off", name="Kapalı", trust_class="ESTABLISHED_MEDIA", feed_url="https://y.test/f",
                  allowed_domains=["y.test"], origin_group="y", enabled=False)]


# ---- şema -------------------------------------------------------------------------------------------

def test_feed_validates_against_schema(settings):
    feed = build_feed({"posts": [post(1), post(2)]}, {"last_run_at": "2026-11-16T11:00:00Z"}, settings, SOURCES, NOW)
    again = Feed.model_validate(json.loads(feed.model_dump_json()))
    assert again.schema_version == 1 and len(again.items) == 2 and again.demo is False


def test_schema_rejects_unknown_fields_and_bad_urls(settings):
    base = build_item(post(), settings, {}).model_dump()
    with pytest.raises(ValidationError):
        FeedItem.model_validate({**base, "chat_id": CHAT})
    with pytest.raises(ValidationError):
        FeedItem.model_validate({**base, "sources": [{"name": "x", "url": "javascript:alert(1)"}]})


def test_only_published_posts_are_exported(settings):
    posts = [post(1), post(2, publish_status="REVIEW_HELD"), post(3, publish_status="UNCERTAIN"),
             post(4, publish_status="REJECTED"), post(5, publish_status="SENDING"), post(6, publish_status="FAILED")]
    feed = build_feed({"posts": posts}, {}, settings, SOURCES, NOW)
    assert [i.id for i in feed.items] == ["cid00001"]
    assert feed.status.verified_total == 1


def test_items_sorted_newest_first_and_capped(settings):
    settings.site_max_items = 5
    feed = build_feed({"posts": [post(i) for i in range(1, 12)]}, {}, settings, SOURCES, NOW)
    assert len(feed.items) == 5
    assert [i.published_at for i in feed.items] == sorted([i.published_at for i in feed.items], reverse=True)


# ---- XSS / temizlik ---------------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>Başlık", "<img src=x onerror=alert(1)>Başlık", "&lt;svg onload=alert(1)&gt;Başlık",
    "&amp;lt;iframe src=javascript:alert(1)&amp;gt;Başlık", "Başlık‮​<b>kalın</b>",
])
def test_text_fields_are_sanitized(settings, payload):
    item = build_item(post(title_tr=payload, summary_tr=payload, why_this_label=payload), settings, {})
    for text in (item.title, item.summary, item.why_this_label):
        assert "<" not in text and ">" not in text and "‮" not in text and "​" not in text


@pytest.mark.parametrize("url,ok", [
    ("https://www.ign.com/a?utm_source=x", "https://ign.com/a"), ("http://ign.com/a", None),
    ("javascript:alert(1)", None), ("data:text/html,<script>", None), ("https://ign.com/a\"onmouseover=x", None),
    (" JAVASCRIPT:alert(1)", None), (12, None),
])
def test_safe_url(url, ok):
    assert safe_url(url) == ok


def test_unsafe_sources_dropped_and_item_without_safe_source_skipped(settings):
    item = build_item(post(source_urls=["javascript:alert(1)", "https://ign.com/a"]), settings, {})
    assert [s.url for s in item.sources] == ["https://ign.com/a"]
    assert build_item(post(source_urls=["javascript:alert(1)", "http://ign.com/a"]), settings, {}) is None


def test_feed_js_cannot_break_out_of_script_tag():
    js = feed_js(json.dumps({"t": "</script><script>alert(1)</script>", "u": "a b"}, ensure_ascii=False))
    assert "</script>" not in js and "<" not in js and " " not in js
    assert js.startswith("window.__GTA6_FEED__ = ")


def test_clean_text_limits_length_and_non_strings():
    assert len(clean_text("ş" * 1000, 50)) <= 50
    assert clean_text(None, 10) == "" and clean_text({"x": 1}, 10) == ""


# ---- gizli veri ---------------------------------------------------------------------------------------

def test_no_sensitive_fields_or_values_in_output(settings, tmp_path):
    state = {"telegram_update_offset": 99, "seen_items": {"x": {}}, "alerts_last_sent": {"A": "t"},
             "last_run_at": "2026-11-16T11:00:00Z"}
    feed = build_feed({"posts": [post(1)]}, state, settings, SOURCES, NOW)
    export_site_feed(feed, tmp_path)
    blob = (tmp_path / "feed.json").read_text() + (tmp_path / "feed.js").read_text()
    for needle in (CHAT, "chat_id", "content_hashes", "deadbeef", "publish_error", "Original EN title",
                   "telegram_update_offset", "seen_items", "alerts_last_sent", DUMMY_TELEGRAM_TOKEN, DUMMY_GEMINI_KEY,
                   "source_titles", "\"views\"", "forwards"):
        assert needle not in blob, needle


def test_telegram_link_only_with_public_username(settings):
    assert telegram_url("", 5) is None
    assert telegram_url("-1001234567890", 5) is None
    assert telegram_url("gta6turkiye", 0) is None
    assert telegram_url("@gta6turkiye", 7) == "https://t.me/gta6turkiye/7"
    settings.public_channel_username = "gta6turkiye"
    assert build_item(post(1), settings, {}).telegram_url == "https://t.me/gta6turkiye/43"


def test_reactions_never_fabricated(settings):
    assert build_item(post(), settings, {}).reactions_total is None
    inferred = post(metrics={"reactions_24h": 0, "reactions_24h_inferred_zero": True, "reaction_snapshots": []})
    assert build_item(inferred, settings, {}).reactions_total is None
    measured = post(metrics={"reactions_24h": 12, "reaction_snapshots": [{"total": 12}]})
    assert build_item(measured, settings, {}).reactions_total == 12


# ---- seçimler ve durum ------------------------------------------------------------------------------

def test_hero_prefers_fresh_official_over_higher_priority(settings):
    feed = build_feed({"posts": [post(1, label="MULTI_SOURCE", editorial_priority=99),
                                 post(5, label="OFFICIAL", editorial_priority=60)]}, {}, settings, SOURCES, NOW)
    assert feed.hero_id == "cid00005"


def test_hero_never_a_claim_when_alternatives_exist(settings):
    items_ = [build_item(post(1, label="LEAK_CLAIM", editorial_priority=99), settings, {}),
              build_item(post(2, label="SINGLE_SOURCE", editorial_priority=40), settings, {})]
    assert pick_hero(items_, NOW) == "cid00002"


def test_status_band_values(settings):
    state = {"last_run_at": "2026-11-16T11:40:00Z", "last_successful_fetch_at": "2026-11-16T11:40:00Z",
             "source_status": {"ign": {"ok": True}, "x": {"ok": False}, "y": "bozuk"}}
    feed = build_feed({"posts": [post(1), post(2)]}, state, settings, SOURCES, NOW)
    assert feed.status.active_sources == 1 and feed.status.sources_ok_last_run == 1
    assert feed.status.verified_total == 2 and feed.status.last_run_at == "2026-11-16T11:40:00Z"


def test_category_mapping_and_unknown_category(settings):
    assert set(CATEGORY_TR) >= {"TRAILER_MEDIA", "GAMEPLAY_TECH", "RELEASE_PLATFORMS", "COMMUNITY_RUMOR",
                                "INDUSTRY_BUSINESS"}
    item = build_item(post(category="<b>HACK</b>"), settings, {})
    assert item.category == "OTHER" and item.category_tr == "Gündem"


def test_malformed_posts_are_skipped_not_crashing(settings):
    posts = [post(1), {"publish_status": "PUBLISHED"}, post(2, label="OFFICIAL_BUT_FAKE"), post(3, published_at="dün"),
             post(4, content_id="../../etc"), "metin", post(5, title_tr="")]
    feed = build_feed({"posts": posts}, {}, settings, SOURCES, NOW)
    assert [i.id for i in feed.items] == ["cid00001"]   # eksik/bozuk/yol enjeksiyonlu kayıtlar atlandı


# ---- yazım ve entegrasyon ------------------------------------------------------------------------

def test_export_is_atomic_and_skips_unchanged(settings, tmp_path):
    feed = build_feed({"posts": [post(1)]}, {}, settings, SOURCES, NOW)
    assert export_site_feed(feed, tmp_path) is True
    later = build_feed({"posts": [post(1)]}, {}, settings, SOURCES, NOW + timedelta(minutes=20))
    assert export_site_feed(later, tmp_path) is False          # yalnızca generated_at değişti
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob(".*.tmp"))
    data = json.loads((tmp_path / "feed.json").read_text())
    assert Feed.model_validate(data).items[0].id == "cid00001"


def test_bot_run_exports_site_feed(tmp_path):
    cfg, data, session = make_env(tmp_path, items(2))
    tg = FakeTelegram()
    code, s = go(cfg, data, session, tg, FakeGenerator())
    feed_path = tmp_path / "docs" / "data" / "feed.json"
    assert code == 0 and feed_path.exists() and (tmp_path / "docs" / "data" / "feed.js").exists()
    feed = Feed.model_validate(json.loads(feed_path.read_text()))
    assert len(feed.items) == len(tg.channel_posts) == 2
    assert all(i.summary for i in feed.items)


def test_safe_mode_does_not_export(tmp_path):
    cfg, data, session = make_env(tmp_path, items(1))
    (data / "history.json").write_text("{bozuk", encoding="utf-8")
    go(cfg, data, session, FakeTelegram(), FakeGenerator())
    assert not (tmp_path / "docs" / "data" / "feed.json").exists()


def test_demo_feed_in_repo_is_valid_and_rich():
    """docs/data/feed.json (simülatörle üretilen demo) şemaya uyar ve siteyi doldurur."""
    from tests.conftest import ROOT
    data = json.loads((ROOT / "docs" / "data" / "feed.json").read_text(encoding="utf-8"))
    feed = Feed.model_validate(data)
    assert feed.demo is True and len(feed.items) == 12
    assert {i.trust_group for i in feed.items} == {"official", "multi", "single", "claim"}
    assert feed.hero_id in {i.id for i in feed.items if i.label == "OFFICIAL"}
    js = (ROOT / "docs" / "data" / "feed.js").read_text(encoding="utf-8")
    assert json.loads(js.split("=", 1)[1].strip().rstrip(";")) == data
