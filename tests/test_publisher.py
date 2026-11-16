"""Uçtan uca (mock) testler: kabul #1, #5, #7, #8, #9, #12, #13, #14 + şablon ve Telegram istemcisi."""
import json
import logging
from datetime import timedelta

import pytest
import requests

from bot import main as bot_main
from bot.config import redact
from bot.processor import GeminiError, GeneratedContent, Label
from bot.publisher import due_digest_key, mark_digest_sent, publish_post, render_post
from bot.telegram_client import TelegramClient, TelegramUncertainError
from tests.conftest import DUMMY_GEMINI_KEY, DUMMY_TELEGRAM_TOKEN, NOW, ROOT, FakeResponse, rss

CHAT = "-1001234567890"
ENV = {"GEMINI_API_KEY": DUMMY_GEMINI_KEY, "TELEGRAM_BOT_TOKEN": DUMMY_TELEGRAM_TOKEN,
       "TELEGRAM_CHAT_ID": CHAT, "GEMINI_MODEL": "test-model-from-env", "ADMIN_CHAT_ID": "-100999"}


# ---- Sahte servisler ---------------------------------------------------------------------

class FakeTelegram:
    def __init__(self, fail_with=None, updates=None):
        self.sent = []
        self.fail_with = fail_with
        self.updates = updates or []
        self.next_id = 100

    def send_message(self, chat_id, text, disable_preview=False, preview_url=None):
        if self.fail_with and str(chat_id) == CHAT:
            exc, self.fail_with = self.fail_with, None
            raise exc
        self.next_id += 1
        self.sent.append({"chat_id": str(chat_id), "text": text, "message_id": self.next_id, "preview_url": preview_url})
        return {"message_id": self.next_id, "chat": {"id": int(chat_id)}}

    def get_updates(self, offset, allowed_updates, limit=100):
        assert allowed_updates == ["message_reaction_count"]
        out, self.updates = self.updates, []
        return out

    @property
    def channel_posts(self):
        return [m for m in self.sent if m["chat_id"] == CHAT]

    @property
    def admin_msgs(self):
        return [m for m in self.sent if m["chat_id"] == "-100999"]


class FakeGenerator:
    def __init__(self, raw=None, error=None):
        self.calls = 0
        self.raw = raw
        self.error = error

    def generate(self, system_instruction, prompt, schema):
        self.calls += 1
        assert "<untrusted_source_data>" in prompt
        if self.error:
            raise self.error
        if self.raw is not None:
            return self.raw
        start = prompt.index("<untrusted_source_data>") + len("<untrusted_source_data>")
        records = json.loads(prompt[start:prompt.index("</untrusted_source_data>")])
        return json.dumps({
            "title_tr": "GTA VI hakkında yeni bir haber yayımlandı",
            "summary_tr": "Yayın organı, GTA VI ile ilgili yeni bir gelişme bildiriyor. Ayrıntılar kaynakta "
                          "sınırlı; konu hakkında ek bilgi bekleniyor.",
            "category": "OTHER", "title_style": "FACTUAL", "claim_type": "REPORTED",
            "source_urls": [records[0]["url"]], "why_this_label": "test", "needs_review": False,
            "translations": {}}, ensure_ascii=False)


class FakeSession:
    def __init__(self, feeds):
        self.feeds = feeds

    def get(self, url, **kw):
        if url in self.feeds:
            return FakeResponse(200, content=self.feeds[url])
        return FakeResponse(404)


def make_env(tmp_path, feed_items, **settings_over):
    cfg = tmp_path / "config"
    cfg.mkdir()
    s = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    s.update({"verify_source_urls": False, "min_minutes_between_posts": 0, "digest_hours_utc": [6, 18]})
    s.update(settings_over)
    (cfg / "settings.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    sources = {"sources": [
        {"id": "eurogamer", "name": "Eurogamer", "trust_class": "ESTABLISHED_MEDIA",
         "feed_url": "https://www.eurogamer.net/feed", "allowed_domains": ["eurogamer.net"],
         "origin_group": "eurogamer"},
        {"id": "broken", "name": "Broken", "trust_class": "ESTABLISHED_MEDIA",
         "feed_url": "https://broken.example.org/feed", "allowed_domains": ["broken.example.org"],
         "origin_group": "broken"},
    ]}
    (cfg / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    feeds = {"https://www.eurogamer.net/feed": rss(feed_items),
             "https://broken.example.org/feed": b"<rss><channel><item>"}
    return cfg, data, FakeSession(feeds)


HEADLINES = [
    ("GTA 6 preload size is 150GB on PlayStation 5", "Storage requirement listed on the store page."),
    ("Take-Two CEO Strauss Zelnick talks GTA 6 marketing budget", "Zelnick spoke at an investor conference."),
    ("GTA 6 soundtrack features licensed Miami radio stations", "Radio stations and music licensing details."),
    ("Rockstar union files new tribunal claim over GTA 6 dismissals", "The IWGB union filed another claim."),
    ("GTA 6 physical edition box art spotted at retailer", "A retailer displayed the boxed edition."),
    ("Lucia voice actress interviewed about GTA 6 role", "The performer discussed motion capture sessions."),
    ("GTA 6 accessibility options detailed in support page", "Subtitles, colour filters and controls listed."),
    ("Xbox Series S performance target for GTA 6 discussed", "Digital Foundry analysed resolution targets."),
]


def items(n, prefix="Story"):
    return [{"title": t if prefix == "Story" else f"{t} ({prefix})",
             "link": f"https://www.eurogamer.net/gta-6-{prefix.lower()}-{i}",
             "description": f"GTA 6: {d}"} for i, (t, d) in enumerate(HEADLINES[:n])]


def go(cfg, data, session, tg, gen, now=NOW, env=ENV):
    return bot_main.run(now=now, env=env, session=session, telegram=tg, generator=gen, data_dir=data,
                        config_dir=cfg)


# ---- Kabul testleri ------------------------------------------------------------------------

def test_same_item_twice_processed_once(tmp_path):
    """KABUL #1: Aynı RSS öğesi iki kez geldiğinde yalnızca bir kez işlenir."""
    cfg, data, session = make_env(tmp_path, items(1))
    tg, gen = FakeTelegram(), FakeGenerator()
    code, s1 = go(cfg, data, session, tg, gen)
    code2, s2 = go(cfg, data, session, tg, gen, now=NOW + timedelta(minutes=20))
    assert code == code2 == 0
    assert gen.calls == 1 and len(tg.channel_posts) == 1
    assert s1["new_items"] == 1 and s2["new_items"] == 0 and s2["duplicates_or_filtered"] >= 1


def test_broken_model_json_end_to_end(tmp_path):
    """KABUL #5 (uçtan uca): bozuk JSON -> çökme yok, yayın yok, kayıt REJECTED."""
    cfg, data, session = make_env(tmp_path, items(1))
    tg, gen = FakeTelegram(), FakeGenerator(raw='{"title_tr": "yarım')
    code, s = go(cfg, data, session, tg, gen)
    assert code == 0 and tg.channel_posts == [] and s["published"] == 0
    hist = json.loads((data / "history.json").read_text())
    assert hist["posts"][0]["publish_status"] == "REJECTED"
    assert "GEMINI_SCHEMA_ERROR" in s["error_classes"]


def test_daily_post_limit_not_exceeded(tmp_path):
    """KABUL #7: max_daily_posts aşılmaz."""
    cfg, data, session = make_env(tmp_path, items(6), max_daily_posts=2, max_gemini_calls_per_run=10)
    tg, gen = FakeTelegram(), FakeGenerator()
    _, s = go(cfg, data, session, tg, gen)
    assert len(tg.channel_posts) == 2 and s["daily_limit_reached"] is True
    _, s2 = go(cfg, data, session, tg, gen, now=NOW + timedelta(hours=2))
    assert len(tg.channel_posts) == 2  # 24 saat dolmadan yeni gönderi yok
    _, s3 = go(cfg, data, session, tg, gen, now=NOW + timedelta(hours=25))
    assert len(tg.channel_posts) == 4


def test_paused_means_no_publish_and_no_gemini(tmp_path):
    """KABUL #8: paused=true iken hiçbir içerik yayınlanmaz ve Gemini çağrısı yapılmaz."""
    cfg, data, session = make_env(tmp_path, items(3), paused=True)
    tg, gen = FakeTelegram(), FakeGenerator()
    code, s = go(cfg, data, session, tg, gen)
    assert code == 0 and s["paused"] is True
    assert gen.calls == 0 and tg.channel_posts == []


def test_telegram_timeout_does_not_cause_duplicate_post(tmp_path):
    """KABUL #9: Telegram timeout sonrası tekrar çalışmada aynı haber ikinci kez yayınlanmaz."""
    cfg, data, session = make_env(tmp_path, items(1))
    tg = FakeTelegram(fail_with=TelegramUncertainError(bot_main.ErrorClass.NETWORK_TRANSIENT, "timeout"))
    gen = FakeGenerator()
    _, s1 = go(cfg, data, session, tg, gen)
    assert s1["uncertain"] == 1 and tg.channel_posts == []
    hist = json.loads((data / "history.json").read_text())
    assert hist["posts"][0]["publish_status"] == "UNCERTAIN"
    # Yeni çalışma: aynı haber feed'de hâlâ var, Telegram artık sağlıklı
    _, s2 = go(cfg, data, session, tg, gen, now=NOW + timedelta(minutes=20))
    assert tg.channel_posts == [] and gen.calls == 1 and s2["published"] == 0


def test_publish_post_rejects_missing_source_url():
    """KABUL #3 (yayın katmanı): kaynak URL'si olmayan gönderi Telegram'a hiç gitmez."""
    tg = FakeTelegram()
    post = {"content_id": "x", "source_urls": []}
    status = publish_post(post=post, text="t", history={"posts": []}, chat_id=CHAT, telegram=tg,
                          persist=lambda: None, now=NOW)
    assert status == "REJECTED" and tg.sent == []


def test_corrupt_insights_end_to_end(tmp_path):
    """KABUL #12 (uçtan uca): bozuk insights.json -> çalışma sürer, yayın yapılır."""
    cfg, data, session = make_env(tmp_path, items(1))
    (data / "insights.json").write_text("{{{ bozuk", encoding="utf-8")
    tg, gen = FakeTelegram(), FakeGenerator()
    code, s = go(cfg, data, session, tg, gen)
    assert code == 0 and len(tg.channel_posts) == 1
    assert list(data.glob("insights.json.corrupt.*.bak"))


def test_digest_not_sent_twice_in_same_window(tmp_path, settings):
    """KABUL #13: Yönetici özeti aynı zaman penceresinde iki kez gönderilmez."""
    state = {"digests_sent": []}
    t1 = NOW.replace(hour=5, minute=50)
    k1 = due_digest_key(settings, state, t1)
    assert k1 == "2026-11-16T06"
    mark_digest_sent(state, k1)
    assert due_digest_key(settings, state, t1 + timedelta(minutes=20)) is None
    assert due_digest_key(settings, state, NOW.replace(hour=7, minute=15)) is None
    assert due_digest_key(settings, state, NOW.replace(hour=12)) is None  # pencere dışı
    assert due_digest_key(settings, state, NOW.replace(hour=17, minute=45)) == "2026-11-16T18"
    # gece yarısı sınırı: 00:30 -> önceki günün değil, yeni günün 06 penceresi değil; pencere yok
    assert due_digest_key(settings, state, NOW.replace(hour=0, minute=30)) is None

    # uçtan uca: iki ardışık çalışma, tek özet
    cfg, data, session = make_env(tmp_path, [])
    tg = FakeTelegram()
    go(cfg, data, session, tg, FakeGenerator(), now=NOW.replace(hour=6, minute=10))
    go(cfg, data, session, tg, FakeGenerator(), now=NOW.replace(hour=6, minute=30))
    digests = [m for m in tg.admin_msgs if "Yönetici Özeti" in m["text"]]
    assert len(digests) == 1


def test_secrets_never_logged(tmp_path, caplog, capsys):
    """KABUL #14: GEMINI_API_KEY ve TELEGRAM_BOT_TOKEN hata durumlarında bile loglarda görünmez."""
    cfg, data, session = make_env(tmp_path, items(1))
    secret_token = "123456789:AAH" + "x" * 32
    secret_key = "AIza" + "S" * 35
    env = dict(ENV, TELEGRAM_BOT_TOKEN=secret_token, GEMINI_API_KEY=secret_key)

    class LeakyGenerator:
        def generate(self, *a):
            raise GeminiError(bot_main.ErrorClass.AUTH_PERMISSION, f"denied key={secret_key}")

    class LeakyTelegram(FakeTelegram):
        def get_updates(self, *a, **k):
            raise bot_main.TelegramError(bot_main.ErrorClass.AUTH_PERMISSION,
                                         f"https://api.telegram.org/bot{secret_token}/getUpdates 401")

    for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN"):
        __import__("os").environ[name] = env[name]
    try:
        logger = logging.getLogger("gta6bot")
        with caplog.at_level(logging.DEBUG, logger="gta6bot"):
            code, summary = go(cfg, data, session, LeakyTelegram(), LeakyGenerator(), env=env)
            logger.error("debug dump %s %s", secret_token, secret_key)
            try:
                raise RuntimeError(f"crash with {secret_token}")
            except RuntimeError:
                logger.exception("beklenmeyen")
        out = capsys.readouterr()
        everything = caplog.text + out.out + out.err + json.dumps(summary)
        everything += "".join(p.read_text() for p in data.glob("*.json"))
        assert secret_token not in everything and secret_key not in everything
        assert "***" in caplog.text
    finally:
        for name in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN"):
            __import__("os").environ.pop(name, None)
    # Pattern tabanlı maskeleme env olmadan da çalışır
    assert secret_token not in redact(f"token {secret_token}")
    assert "Secrets(<redacted>)" == repr(bot_main.load_secrets(env)[0])


# ---- Ek güvenlik/dayanıklılık testleri -------------------------------------------------------

def test_missing_secrets_exit_1_without_values(tmp_path):
    cfg, data, session = make_env(tmp_path, items(1))
    code, s = go(cfg, data, session, FakeTelegram(), FakeGenerator(), env={"TELEGRAM_CHAT_ID": CHAT})
    assert code == 1 and "GEMINI_API_KEY" in s["notes"][0]


def test_corrupt_history_enters_safe_mode_and_keeps_file(tmp_path):
    cfg, data, session = make_env(tmp_path, items(1))
    (data / "history.json").write_text("{bozuk", encoding="utf-8")
    tg, gen = FakeTelegram(), FakeGenerator()
    code, s = go(cfg, data, session, tg, gen)
    assert code == 2 and s["safe_mode"] and gen.calls == 0 and tg.channel_posts == []
    assert (data / "history.json").read_text() == "{bozuk"
    assert list(data.glob("history.json.corrupt.*.bak"))
    assert any("ACİL UYARI" in m["text"] for m in tg.admin_msgs)


def test_gemini_quota_stops_calls_and_never_switches_model(tmp_path):
    cfg, data, session = make_env(tmp_path, items(3), max_gemini_calls_per_run=5)
    gen = FakeGenerator(error=GeminiError(bot_main.ErrorClass.RATE_LIMIT_QUOTA, "429"))
    _, s = go(cfg, data, session, FakeTelegram(), gen)
    assert gen.calls == 1 and s["published"] == 0
    state = json.loads((data / "state.json").read_text())
    assert state["gemini_quota_blocked_until"]
    _, s2 = go(cfg, data, session, FakeTelegram(), gen, now=NOW + timedelta(minutes=20))
    assert gen.calls == 1  # soğuma süresinde çağrı yok
    gen.error = None
    _, s3 = go(cfg, data, session, FakeTelegram(), gen, now=NOW + timedelta(minutes=90))
    assert s3["published"] >= 1


def test_render_post_escapes_html_and_fits_limit(settings):
    c = GeneratedContent(title_tr="GTA VI <b>kalın</b> & \"tırnak\" denemesi", summary_tr="Özet <script>x</script> metni " * 3,
                         category="TRAILER_MEDIA", title_style="FACTUAL", claim_type="REPORTED",
                         source_urls=["https://www.eurogamer.net/a"], why_this_label="t", needs_review=False)
    text = render_post(c, Label.SINGLE_SOURCE, [{"name": "Euro<gamer>", "url": "https://eurogamer.net/a?x=1&y=2"}],
                       settings, NOW)
    assert "<script>" not in text and "&lt;b&gt;kalın" in text and "Euro&lt;gamer&gt;" in text
    assert "🟨 <b>TEK KAYNAK</b>" in text and len(text) < 4096
    assert text.count("🟨") == 1  # tek rozet, emoji kalabalığı yok


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body

    def json(self):
        return self._b


class _PostSession:
    def __init__(self, seq):
        self.seq = list(seq)
        self.calls = 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        item = self.seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_telegram_client_send_not_retried_on_read_timeout():
    s = _PostSession([requests.exceptions.ReadTimeout("x"), _Resp(200, {"ok": True, "result": {}})])
    c = TelegramClient(DUMMY_TELEGRAM_TOKEN, session=s, sleep=lambda d: None)
    with pytest.raises(TelegramUncertainError):
        c.send_message(CHAT, "merhaba")
    assert s.calls == 1


def test_telegram_client_retries_429_with_retry_after_and_masks_token():
    s = _PostSession([_Resp(429, {"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 1}}),
                      _Resp(200, {"ok": True, "result": {"message_id": 7}})])
    slept = []
    c = TelegramClient(DUMMY_TELEGRAM_TOKEN, session=s, sleep=slept.append)
    assert c.send_message(CHAT, "x")["message_id"] == 7 and slept == [1.0]
    s2 = _PostSession([_Resp(401, {"ok": False, "description": f"bad token {DUMMY_TELEGRAM_TOKEN}"})])
    with pytest.raises(bot_main.TelegramError) as ei:
        TelegramClient(DUMMY_TELEGRAM_TOKEN, session=s2, sleep=lambda d: None).get_updates(None, ["x"])
    assert DUMMY_TELEGRAM_TOKEN not in str(ei.value) and ei.value.error_class.value == "AUTH_PERMISSION"
