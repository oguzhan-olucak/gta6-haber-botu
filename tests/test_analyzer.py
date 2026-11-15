"""Kabul testleri #10, #11 + ölçüm durumu ve analiz kuralları."""
from datetime import timedelta

from bot import iso
from bot.analyzer import analyze, apply_updates, update_measurement_status
from tests.conftest import NOW

CHAT = "-1001234567890"


def post(mid, published, category="TRAILER_MEDIA", style="FACTUAL"):
    return {"content_id": f"c{mid}", "chat_id": CHAT, "message_id": mid, "publish_status": "PUBLISHED",
            "published_at": iso(published), "category": category, "title_style": style,
            "measurement_status": "PENDING",
            "metrics": {"views": "unavailable", "forwards": "unavailable", "reaction_snapshots": []}}


def reaction_update(update_id, mid, date, counts):
    return {"update_id": update_id, "message_reaction_count": {
        "chat": {"id": int(CHAT), "type": "channel"}, "message_id": mid, "date": int(date.timestamp()),
        "reactions": [{"type": {"type": "emoji", "emoji": e}, "total_count": c} for e, c in counts.items()]}}


def test_reaction_count_update_attaches_to_correct_message():
    """KABUL #10: message_reaction_count doğru message_id kaydına eklenir."""
    h = {"posts": [post(10, NOW - timedelta(hours=2)), post(11, NOW - timedelta(hours=1))]}
    state = {}
    u = reaction_update(500, 11, NOW - timedelta(minutes=30), {"👍": 3, "🔥": 2})
    stats = apply_updates([u], h, state)
    assert stats["matched"] == 1
    assert h["posts"][0]["metrics"]["reaction_snapshots"] == []
    snap = h["posts"][1]["metrics"]["reaction_snapshots"][0]
    assert snap["total"] == 5 and snap["by_type"] == {"emoji:👍": 3, "emoji:🔥": 2}
    assert state["telegram_update_offset"] == 501
    # Aynı update tekrar gelirse (idempotent) ikinci snapshot eklenmez
    apply_updates([u], h, state)
    assert len(h["posts"][1]["metrics"]["reaction_snapshots"]) == 1
    # Bilinmeyen mesaj eşleşmez, çökmez
    assert apply_updates([reaction_update(501, 999, NOW, {"👍": 1})], h, state)["unmatched"] == 1


def test_views_and_forwards_stay_unavailable(settings):
    """KABUL #11: Bot API'den alınamayan views/forwards sahte değerle doldurulmaz."""
    h = {"posts": [post(10, NOW - timedelta(hours=30))]}
    state = {}
    apply_updates([reaction_update(1, 10, NOW - timedelta(hours=29), {"👍": 4})], h, state)
    update_measurement_status(h, state, settings, NOW)
    m = h["posts"][0]["metrics"]
    assert m["views"] == "unavailable" and m["forwards"] == "unavailable"
    ins = analyze(h, settings, NOW)
    assert ins["metrics_unavailable"] == {"views": "unavailable", "forwards": "unavailable"}
    assert "rate" not in str(ins["by_category"]).lower()


def test_measurement_status_transitions(settings):
    h = {"posts": [post(1, NOW - timedelta(hours=3)), post(2, NOW - timedelta(hours=30)),
                   post(3, NOW - timedelta(hours=30))]}
    state = {}
    apply_updates([reaction_update(1, 3, NOW - timedelta(hours=28), {"👍": 2})], h, state)
    update_measurement_status(h, state, settings, NOW)
    s = {p["message_id"]: p["measurement_status"] for p in h["posts"]}
    assert s[1] == "PENDING"
    assert s[3] == "COMPLETE" and h["posts"][2]["metrics"]["reactions_24h"] == 2
    # 2 numaralı gönderi için akış kanıtlı (pipeline_since <= yayın) -> 0 çıkarımı, açıkça işaretli
    assert s[2] == "COMPLETE" and h["posts"][1]["metrics"]["reactions_24h_inferred_zero"] is True


def test_no_reaction_pipeline_means_unavailable(settings):
    h = {"posts": [post(1, NOW - timedelta(hours=30))]}
    update_measurement_status(h, {}, settings, NOW)
    assert h["posts"][0]["measurement_status"] == "UNAVAILABLE"
    assert analyze(h, settings, NOW)["status"] == "YETERSİZ VERİ"


def test_small_sample_never_declares_winner(settings):
    h = {"posts": []}
    for i in range(4):
        p = post(i, NOW - timedelta(hours=40), style="QUESTION")
        p.update(measurement_status="COMPLETE")
        p["metrics"]["reactions_24h"] = 50
        h["posts"].append(p)
    ins = analyze(h, settings, NOW)
    assert ins["title_style_ranking"]["result"] == "YETERSİZ VERİ"
    assert ins["prompt_hints"] == {}


def test_enough_sample_gives_early_signal_and_style_hint_only(settings):
    h = {"posts": []}
    for i in range(12):
        style = "QUESTION" if i % 2 else "FACTUAL"
        p = post(i, NOW - timedelta(hours=40), style=style)
        p.update(measurement_status="COMPLETE")
        p["metrics"]["reactions_24h"] = 20 if style == "QUESTION" else 5
        h["posts"].append(p)
    ins = analyze(h, settings, NOW)
    assert ins["title_style_ranking"]["result"] == "ERKEN SİNYAL"
    assert ins["prompt_hints"] == {"preferred_title_styles": ["QUESTION"]}
    assert set(ins["prompt_hints"]) == {"preferred_title_styles"}  # eşik/güven sınıfına dokunmaz
