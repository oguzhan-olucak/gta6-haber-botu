"""Etkileşimli yerel simülatör: gerçek ağa/API'ye hiç bağlanmadan botun TAM hattını
(toplama → kümeleme → değerlendirme → doğrulama → şablon → yayın → özet/alarm) sahte servislerle
çalıştırır ve çıktıları Telegram mobil arayüzü maketi içinde ``docs/message_preview.html``
dosyasına basar.

Kullanım:
    python tools/dry_run_simulator.py                      # tüm senaryolar → docs/message_preview.html
    python tools/dry_run_simulator.py --scenario multi     # tek senaryo
    python tools/dry_run_simulator.py --interactive        # menüden seç
    python tools/dry_run_simulator.py --print              # mesajları terminale de yaz

Güvenlik: simülatör çalışırken soket bağlantıları engellenir; gerçek token/anahtar okunmaz.
Özet metinleri örnek senaryo verisidir, gerçek haber değildir.
"""
from __future__ import annotations

import argparse
import html
import json
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from bot import main as bot_main  # noqa: E402
from bot.telegram_client import TelegramError  # noqa: E402

CHANNEL = "-1001000000001"
ADMIN = "-1001000000002"
NOW = datetime(2026, 11, 16, 18, 40, tzinfo=timezone.utc)   # 21:40 TSİ
ENV = {"GEMINI_API_KEY": "SIMULATOR_FAKE_KEY", "TELEGRAM_BOT_TOKEN": "SIMULATOR_FAKE_TOKEN",
       "TELEGRAM_CHAT_ID": CHANNEL, "ADMIN_CHAT_ID": ADMIN, "GEMINI_MODEL": "simulator-model"}


# ---- Ağ kalkanı ----------------------------------------------------------------------------

def block_network() -> None:
    """Simülasyon boyunca her türlü dış bağlantıyı engeller."""
    def guard(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("Simülatörde ağ erişimi yasak")
    socket.socket.connect = guard  # type: ignore[method-assign]
    socket.create_connection = guard  # type: ignore[assignment]


# ---- Sahte servisler -----------------------------------------------------------------------

class FakeResponse:
    """requests.Response'un simülatörde gereken kısmı."""

    def __init__(self, status: int, content: bytes = b""):
        self.status_code = status
        self._content = content
        self.headers: dict[str, str] = {}

    def iter_content(self, chunk_size: int = 65536) -> Any:
        """İçeriği parçalar halinde verir."""
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def close(self) -> None:
        """Bağlantıyı kapatır (no-op)."""


class FakeSession:
    """URL → bayt eşlemesinden yanıt veren oturum."""

    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages

    def get(self, url: str, **_kw: Any) -> FakeResponse:
        """Bilinen URL'ye 200, diğerlerine 404."""
        return FakeResponse(200, self.pages[url]) if url in self.pages else FakeResponse(404)


class CapturingTelegram:
    """Gönderilen mesajları yakalayan sahte Telegram istemcisi."""

    def __init__(self, fail_updates: TelegramError | None = None):
        self.sent: list[dict[str, Any]] = []
        self.fail_updates = fail_updates

    def send_message(self, chat_id: str | int, text: str, *, disable_preview: bool = False) -> dict[str, Any]:
        """Mesajı kaydeder."""
        self.sent.append({"chat_id": str(chat_id), "text": text})
        return {"message_id": len(self.sent), "chat": {"id": int(chat_id)}}

    def get_updates(self, offset: int | None, allowed_updates: list[str], limit: int = 100) -> list[dict[str, Any]]:
        """Reaksiyon güncellemesi yok (veya senaryoya göre hata)."""
        if self.fail_updates:
            raise self.fail_updates
        return []


class ScriptedGenerator:
    """Senaryoya ait hazır Türkçe başlık/özeti, kaynak URL'leriyle birlikte JSON olarak döndürür."""

    def __init__(self, title: str, summary: str, category: str, claim_type: str = "REPORTED"):
        self.payload = {"title_tr": title, "summary_tr": summary, "category": category, "title_style": "FACTUAL",
                        "claim_type": claim_type, "why_this_label": "simülasyon", "needs_review": False,
                        "translations": {}}

    def generate(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        """İstemdeki ilk kaynak URL'sini kullanarak çıktı üretir."""
        start = prompt.index("<untrusted_source_data>") + len("<untrusted_source_data>")
        records = json.loads(prompt[start:prompt.index("</untrusted_source_data>")])
        return json.dumps(dict(self.payload, source_urls=[r["url"] for r in records[:2]]), ensure_ascii=False)


# ---- Senaryolar ----------------------------------------------------------------------------

def rss(items: list[tuple[str, str, str]]) -> bytes:
    """(başlık, bağlantı, açıklama) listesinden RSS 2.0 üretir."""
    body = "".join(f"<item><title>{html.escape(t)}</title><link>{l}</link><description>{html.escape(d)}</description>"
                   f"<pubDate>Mon, 16 Nov 2026 17:30:00 GMT</pubDate></item>" for t, l, d in items)
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()


MEDIA = {
    "ign": ("IGN", "https://feeds.example-ign.test/games.xml", "ign.com"),
    "vgc": ("Video Games Chronicle", "https://www.videogameschronicle.com/feed/", "videogameschronicle.com"),
    "insider_gaming": ("Insider Gaming", "https://insider-gaming.com/feed/", "insider-gaming.com"),
}


def media_source(sid: str) -> dict[str, Any]:
    """Sahte medya kaynağı tanımı."""
    name, feed, domain = MEDIA[sid]
    return {"id": sid, "name": name, "trust_class": "ESTABLISHED_MEDIA", "feed_url": feed,
            "allowed_domains": [domain], "origin_group": sid}


@dataclass
class Scenario:
    """Tek simülasyon senaryosu."""
    key: str
    title: str
    blurb: str
    audience: str                      # "channel" | "admin"
    sources: list[dict[str, Any]] = field(default_factory=list)
    pages: dict[str, bytes] = field(default_factory=dict)
    generator: ScriptedGenerator | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    now: datetime = NOW
    telegram_factory: Callable[[], CapturingTelegram] = CapturingTelegram
    seed_history: list[dict[str, Any]] = field(default_factory=list)


def scenarios() -> dict[str, Scenario]:
    """Beş hazır senaryo."""
    official_page = (b'<main><a href="/newswire/article/k1v2/grand-theft-auto-vi-launch-trailer">'
                     b'Grand Theft Auto VI Launch Trailer</a></main>')
    return {
        "official": Scenario(
            "official", "Resmî duyuru", "Rockstar Newswire HTML listesinden gelen, URL'si doğrulanmış duyuru.",
            "channel",
            sources=[{"id": "rockstar_newswire_html", "name": "Rockstar Newswire", "trust_class": "OFFICIAL",
                      "kind": "html_listing", "feed_url": "https://www.rockstargames.com/newswire",
                      "link_pattern": "^/newswire/article/", "allowed_domains": ["rockstargames.com"],
                      "origin_group": "rockstar"}],
            pages={"https://www.rockstargames.com/newswire": official_page},
            generator=ScriptedGenerator(
                "Rockstar, GTA VI'ın çıkış fragmanını yayımladı",
                "Rockstar Games, Grand Theft Auto VI için çıkış fragmanını resmî Newswire sayfasında paylaştı. "
                "Fragman, Newswire üzerinden izlenebiliyor.", "TRAILER_MEDIA", "OFFICIAL")),
        "multi": Scenario(
            "multi", "Çoklu kaynak", "IGN ve VGC aynı gelişmeyi farklı başlıklarla yazdı; motor tek olayda birleştirdi.",
            "channel",
            sources=[media_source("ign"), media_source("vgc")],
            pages={MEDIA["ign"][1]: rss([("GTA 6 preload size is 150GB on PS5", "https://www.ign.com/articles/gta-6-preload-size",
                                          "Grand Theft Auto 6 will require 150GB of storage on PlayStation 5, according to "
                                          "the PlayStation Store listing.")]),
                   MEDIA["vgc"][1]: rss([("GTA VI needs 150GB of free space on PlayStation 5, store listing shows",
                                          "https://www.videogameschronicle.com/news/gta-6-150gb",
                                          "The PlayStation Store page for GTA 6 lists a 150GB download ahead of launch.")])},
            generator=ScriptedGenerator(
                "GTA VI, PlayStation 5'te 150GB alan istiyor",
                "IGN ve Video Games Chronicle, PlayStation Store listesine göre GTA 6'nın PlayStation 5'te 150GB "
                "depolama alanı gerektirdiğini bildiriyor. Bilgi mağaza sayfasına dayanıyor.", "RELEASE_PLATFORMS")),
        "leak": Scenario(
            "leak", "Sızıntı iddiası", "Yalnızca allow_community_rumors=true iken yayınlanır; her zaman iddia olarak işaretlenir.",
            "channel",
            sources=[media_source("insider_gaming")],
            pages={MEDIA["insider_gaming"][1]: rss([(
                "GTA 6 leak allegedly shows unannounced Leonida island", "https://insider-gaming.com/gta-6-leak-island",
                "An alleged leak claims an unannounced island exists in Leonida. Rockstar has not commented.")])},
            generator=ScriptedGenerator(
                "Bir sızıntı, GTA VI'da duyurulmamış bir ada olduğunu iddia ediyor",
                "Insider Gaming'in aktardığı doğrulanmamış bir sızıntıya göre Leonida'da henüz duyurulmamış bir ada "
                "bulunuyor. Rockstar konu hakkında yorum yapmadı.", "COMMUNITY_RUMOR", "RUMOR"),
            settings={"allow_community_rumors": True}),
        "digest": Scenario(
            "digest", "Günlük yönetici özeti", "06:00 ve 18:00 UTC penceresinde yalnızca yönetici sohbetine gider.",
            "admin", now=datetime(2026, 11, 16, 18, 5, tzinfo=timezone.utc),
            seed_history=[{"content_id": "x1", "publish_status": "PUBLISHED", "published_at": "2026-11-16T09:00:00Z",
                           "source_urls": ["https://ign.com/a"], "chat_id": CHANNEL, "message_id": 1,
                           "label_text": "ÇOKLU KAYNAK", "title_tr": "GTA VI, PlayStation 5'te 150GB alan istiyor"},
                          {"content_id": "x2", "publish_status": "REVIEW_HELD", "created_at": "2026-11-16T12:00:00Z",
                           "source_urls": ["https://ign.com/b"]}]),
        "alert": Scenario(
            "alert", "Acil hata alarmı", "Telegram token reddedildi (401). Aynı uyarı 6 saat içinde tekrar gönderilmez.",
            "admin", now=datetime(2026, 11, 16, 12, 40, tzinfo=timezone.utc), telegram_factory=lambda: CapturingTelegram(
                fail_updates=TelegramError(bot_main.ErrorClass.AUTH_PERMISSION, "getUpdates: 401 Unauthorized",
                                           status=401))),
    }


def run_scenario(sc: Scenario) -> dict[str, Any]:
    """Senaryoyu geçici bir çalışma dizininde botun gerçek ``run()`` fonksiyonuyla çalıştırır."""
    with tempfile.TemporaryDirectory(prefix=f"sim-{sc.key}-") as tmp:
        cfg, data = Path(tmp) / "config", Path(tmp) / "data"
        cfg.mkdir()
        data.mkdir()
        settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
        settings.update({"verify_source_urls": False, "min_minutes_between_posts": 0}, **sc.settings)
        (cfg / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        (cfg / "sources.json").write_text(json.dumps({"sources": sc.sources}, ensure_ascii=False), encoding="utf-8")
        if sc.seed_history:
            (data / "history.json").write_text(json.dumps({"posts": sc.seed_history}), encoding="utf-8")
        tg = sc.telegram_factory()
        code, summary = bot_main.run(now=sc.now, env=ENV, session=FakeSession(sc.pages), telegram=tg,  # type: ignore[arg-type]
                                     generator=sc.generator, data_dir=data, config_dir=cfg,
                                     url_verifier=lambda url, allowed, hops: (True, url))
        history = json.loads((data / "history.json").read_text(encoding="utf-8")) if (data / "history.json").exists() \
            else {"posts": []}
    target = CHANNEL if sc.audience == "channel" else ADMIN
    msgs = [m["text"] for m in tg.sent if m["chat_id"] == target]
    decision = next((p for p in reversed(history.get("posts", [])) if p.get("publish_reason")), {})
    return {"scenario": sc, "code": code, "summary": summary, "messages": msgs, "decision": decision}


# ---- HTML ---------------------------------------------------------------------------------

def tg_html(text: str) -> str:
    """Telegram HTML alt kümesi zaten kaçırılmış; yalnızca satır sonlarını çevir."""
    return text.replace("\n", "<br>")


def phone(result: dict[str, Any]) -> str:
    """Tek senaryo için telefon maketi."""
    sc: Scenario = result["scenario"]
    is_admin = sc.audience == "admin"
    name = "GTA VI Bot" if is_admin else "GTA VI Türkiye Bülteni"
    sub = "yönetici sohbeti" if is_admin else "kanal · önizleme"
    clock = sc.now.astimezone(timezone(timedelta(hours=3))).strftime("%H:%M")
    bubbles = "".join(f'<div class="bubble"><div class="msg">{tg_html(m)}</div><span class="stamp">{clock}</span></div>'
                      for m in result["messages"]) or '<p class="empty">Bu senaryoda mesaj oluşmadı.</p>'
    d = result["decision"]
    if d:
        verdict = (f'<b>{html.escape(d.get("label_text", ""))}</b> · kaynak gücü {d.get("source_strength")} · '
                   f'öncelik {d.get("editorial_priority")}<br>{html.escape(d.get("publish_reason", ""))}')
    else:
        notes = [n for n in result["summary"].get("notes", []) if n.startswith(("alarm", "özet"))]
        verdict = html.escape(", ".join(notes) or "—")
    footer = "" if is_admin else '<div class="mute">Sessize al</div>'
    return f"""
    <figure class="device" data-scenario="{sc.key}" id="s-{sc.key}">
      <div class="screen">
        <div class="status"><span>{clock}</span><span class="island" aria-hidden="true"></span><span class="sig" aria-hidden="true">▮▮▮</span></div>
        <header class="bar">
          <span class="back" aria-hidden="true">‹</span>
          <span class="avatar{' bot' if is_admin else ''}" aria-hidden="true">VI</span>
          <span class="who"><b>{name}</b><small>{sub}</small></span>
        </header>
        <div class="chat">{bubbles}</div>
        {footer}
      </div>
      <figcaption><h3>{html.escape(sc.title)}</h3><p>{html.escape(sc.blurb)}</p><p class="verdict">{verdict}</p></figcaption>
    </figure>"""


def render_page(results: list[dict[str, Any]]) -> str:
    """Tüm sonuçları tek sayfaya yerleştirir."""
    chips = "".join(f'<button type="button" class="chip" data-target="{r["scenario"].key}" aria-pressed="false">'
                    f'{html.escape(r["scenario"].title)}</button>' for r in results)
    phones = "".join(phone(r) for r in results)
    return PAGE.replace("{{CHIPS}}", chips).replace("{{PHONES}}", phones)


PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTA VI Türkiye Bülteni · mesaj simülatörü</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;900&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --night: #120B2E; --night-2: #1C1442; --ink: #F4EEFF; --muted: #A99CD6;
    --pink: #FF4F9A; --teal: #2EE6D6; --sun: #FF9A5A; --gold: #FFD166;
    --tg-bubble: #2A1F5C; --tg-bar: #1A1240;
    --display: "Big Shoulders Display", "Arial Narrow", "Roboto Condensed", sans-serif;
    --body: "Instrument Sans", "Segoe UI", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  html { background: var(--night); color: var(--ink); }
  body { margin: 0; font: 400 16px/1.55 var(--body); }
  a { color: var(--teal); text-underline-offset: 3px; }
  :focus-visible { outline: 2px solid var(--teal); outline-offset: 3px; }

  .sitenav { display: flex; gap: 18px; align-items: center; padding: 14px 24px; border-bottom: 1px solid rgba(169,156,214,.15); font-weight: 600; }
  .sitenav a { color: var(--teal); text-decoration: none; }
  .sitenav span { color: var(--ink); box-shadow: inset 0 -2px 0 var(--pink); padding-bottom: 2px; }
  .horizon { position: relative; overflow: hidden; padding: 64px 24px 48px;
    background: radial-gradient(120% 90% at 50% 120%, rgba(255,154,90,.5) 0%, rgba(255,79,154,.32) 35%, transparent 65%),
                linear-gradient(180deg, #0C0722 0%, var(--night) 100%);
    border-bottom: 1px solid rgba(46,230,214,.25); }
  .horizon::after { content: ""; position: absolute; right: max(24px, calc(50% - 560px)); bottom: 0;
    width: min(360px, 56vw); aspect-ratio: 2 / 1; border-radius: 999px 999px 0 0;
    background: linear-gradient(180deg, transparent 0 52%, var(--night) 52% 56%, transparent 56% 66%,
                  var(--night) 66% 72%, transparent 72% 80%, var(--night) 80% 88%, transparent 88%),
                linear-gradient(180deg, var(--gold) 0%, var(--sun) 45%, var(--pink) 100%);
    box-shadow: 0 0 80px rgba(255,79,154,.35); }
  .inner { position: relative; z-index: 1; max-width: 1180px; margin: 0 auto; }
  h1 { margin: 0; font: 900 clamp(44px, 8vw, 96px)/.92 var(--display); text-shadow: 0 0 28px rgba(255,79,154,.45); }
  .lede { max-width: 62ch; margin: 16px 0 0; color: var(--muted); font-size: 17px; }

  nav.chips { position: sticky; top: 0; z-index: 5; display: flex; gap: 8px; flex-wrap: wrap; justify-content: center;
    padding: 14px 24px; background: rgba(18,11,46,.88); backdrop-filter: blur(8px); border-bottom: 1px solid rgba(169,156,214,.15); }
  .chip { font: 600 14px var(--body); color: var(--ink); background: transparent; border: 1px solid rgba(169,156,214,.35);
    border-radius: 999px; padding: 7px 14px; cursor: pointer; }
  .chip[aria-pressed="true"] { border-color: var(--teal); color: var(--teal); }

  main { max-width: 1180px; margin: 0 auto; padding: 40px 24px 72px; }
  .stage { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 48px 32px; justify-items: center; }
  .device { margin: 0; width: 330px; }
  .device.dim { opacity: .28; }
  .screen { position: relative; height: 680px; border-radius: 46px; overflow: hidden; display: flex; flex-direction: column;
    background: var(--night-2); border: 10px solid #07040F;
    box-shadow: 0 0 0 1px rgba(255,255,255,.08), 0 30px 60px rgba(0,0,0,.55), 0 0 60px rgba(255,79,154,.12); }
  .status { display: flex; justify-content: space-between; align-items: center; padding: 10px 24px 4px; font-size: 13px; font-weight: 600; }
  .island { width: 92px; height: 24px; border-radius: 999px; background: #07040F; }
  .sig { letter-spacing: -2px; font-size: 10px; }
  .bar { display: flex; align-items: center; gap: 10px; padding: 8px 14px 10px; background: var(--tg-bar);
    border-bottom: 1px solid rgba(255,255,255,.06); }
  .back { font-size: 30px; line-height: 1; color: var(--teal); }
  .avatar { width: 38px; height: 38px; border-radius: 50%; display: grid; place-items: center; font: 900 16px var(--display);
    background: linear-gradient(135deg, var(--gold), var(--pink)); color: #1A0F33; }
  .avatar.bot { background: linear-gradient(135deg, var(--teal), #4FA8FF); }
  .who { display: flex; flex-direction: column; line-height: 1.2; }
  .who small { color: var(--muted); font-size: 12px; }
  .chat { flex: 1; overflow-y: auto; padding: 16px 12px; display: flex; flex-direction: column; justify-content: flex-end; gap: 10px;
    background:
      radial-gradient(70% 40% at 50% 105%, rgba(255,79,154,.22), transparent 70%),
      repeating-linear-gradient(135deg, rgba(255,255,255,.018) 0 2px, transparent 2px 14px),
      linear-gradient(180deg, #160E38, #1F1347); }
  .bubble { position: relative; max-width: 94%; background: var(--tg-bubble); border-radius: 16px 16px 16px 4px;
    padding: 10px 12px 20px; font-size: 13.5px; line-height: 1.45; box-shadow: 0 1px 0 rgba(0,0,0,.25); }
  .bubble b { font-weight: 600; }
  .bubble i { color: #C9BEF0; }
  .bubble code { font-size: 12px; background: rgba(46,230,214,.12); color: var(--teal); padding: 0 4px; border-radius: 4px; }
  .stamp { position: absolute; right: 10px; bottom: 4px; font-size: 11px; color: var(--muted); }
  .empty { color: var(--muted); text-align: center; }
  .mute { padding: 14px; text-align: center; font-weight: 600; color: var(--teal); background: var(--tg-bar);
    border-top: 1px solid rgba(255,255,255,.06); }
  figcaption h3 { margin: 18px 0 4px; font: 700 26px/1.1 var(--display); }
  figcaption p { margin: 0 0 6px; color: var(--muted); font-size: 14px; max-width: 42ch; }
  figcaption .verdict { color: var(--ink); font-size: 13px; border-left: 2px solid var(--pink); padding-left: 10px; }
  footer { max-width: 1180px; margin: 0 auto; padding: 0 24px 48px; color: var(--muted); font-size: 14px; }
  @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
</style>
</head>
<body>
  <nav class="sitenav" aria-label="Site"><a href="index.html">‹ Haberler</a><span aria-current="page">Telegram önizleme</span></nav>
  <section class="horizon"><div class="inner">
    <h1>Gece bülteni,<br>ışıklar açık.</h1>
    <p class="lede">Botun beş senaryodaki gerçek çıktısı. Her ekran, sahte servislerle tam hat çalıştırılarak üretildi:
    toplama, olay kümeleme, kaynak doğrulama, şablon ve yayın kararı. Haber metinleri örnektir.</p>
  </div></section>
  <nav class="chips" aria-label="Senaryolar">{{CHIPS}}</nav>
  <main><div class="stage">{{PHONES}}
  </div></main>
  <footer>Yeniden üretmek için: <code>python tools/dry_run_simulator.py</code> · tek senaryo: <code>--scenario multi</code> · menü: <code>--interactive</code></footer>
<script>
  const chips = document.querySelectorAll('.chip');
  const devices = document.querySelectorAll('.device');
  chips.forEach(chip => chip.addEventListener('click', () => {
    const on = chip.getAttribute('aria-pressed') !== 'true';
    chips.forEach(c => c.setAttribute('aria-pressed', 'false'));
    chip.setAttribute('aria-pressed', String(on));
    devices.forEach(d => d.classList.toggle('dim', on && d.dataset.scenario !== chip.dataset.target));
    if (on) document.getElementById('s-' + chip.dataset.target).scrollIntoView({behavior: 'smooth', block: 'center'});
  }));
</script>
</body>
</html>
"""


# ---- CLI ---------------------------------------------------------------------------------

def choose_interactively(all_keys: list[str]) -> list[str]:
    """Basit terminal menüsü."""
    sc = scenarios()
    print("Senaryolar:")
    for i, k in enumerate(all_keys, 1):
        print(f"  {i}. {sc[k].title}")
    print("  0. Hepsi")
    raw = input("Seçim (ör. 1,3 veya 0): ").strip() or "0"
    if raw == "0":
        return all_keys
    picked = [all_keys[int(x) - 1] for x in raw.split(",") if x.strip().isdigit() and 0 < int(x) <= len(all_keys)]
    return picked or all_keys


def main(argv: list[str] | None = None) -> int:
    """Simülatörü çalıştırır ve HTML önizlemeyi yazar."""
    all_keys = list(scenarios())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=["all", *all_keys], default="all")
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--print", dest="echo", action="store_true", help="mesajları terminale de yaz")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "message_preview.html")
    ap.add_argument("--site-data", type=Path, default=ROOT / "docs" / "data",
                    help="12 haberlik demo site beslemesinin yazılacağı klasör")
    ap.add_argument("--no-site", action="store_true", help="demo site beslemesini üretme")
    args = ap.parse_args(argv)
    block_network()
    keys = choose_interactively(all_keys) if args.interactive else all_keys if args.scenario == "all" else [args.scenario]
    results = [run_scenario(scenarios()[k]) for k in keys]
    for r in results:
        sc = r["scenario"]
        print(f"[{sc.key}] çıkış={r['code']} mesaj={len(r['messages'])} yayın={r['summary']['published']}")
        if args.echo:
            for m in r["messages"]:
                print("  " + m.replace("\n", "\n  "))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_page(results), encoding="utf-8")
    print(f"Yazıldı: {args.out}")
    if not args.no_site:
        from demo_site import build_demo_feed
        feed = build_demo_feed(args.site_data, CapturingTelegram, FakeSession, ENV)
        print(f"Demo site beslemesi: {len(feed.items)} haber, manşet={feed.hero_id} → {args.site_data / 'feed.json'}")
    missing = [r["scenario"].key for r in results if not r["messages"]]
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
