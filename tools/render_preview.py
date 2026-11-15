"""Telegram mesaj şablonlarının HTML önizlemesini üretir: docs/message_preview.html

Kullanım:  python tools/render_preview.py
Önizlemedeki metinler ÖRNEKTİR; gerçek haber değildir. Kartlar, botun Telegram'a gönderdiği
metni üreten gerçek ``bot.publisher.render_post`` fonksiyonuyla oluşturulur.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import Settings  # noqa: E402
from bot.processor import GeneratedContent, Label  # noqa: E402
from bot.publisher import render_digest, render_post  # noqa: E402

NOW = datetime(2026, 11, 16, 18, 40, tzinfo=timezone.utc)

SAMPLES = [
    (Label.OFFICIAL, "RELEASE_PLATFORMS", [("Rockstar Newswire", "https://www.rockstargames.com/newswire")],
     "Örnek: Rockstar, resmî duyurusunda yayın takvimini paylaştı",
     "Örnek metin. Rockstar Games resmî Newswire sayfasında bir duyuru yayımladı. Özet yalnızca kaynakta "
     "yazan bilgiyi iki üç cümlede aktarır ve her zaman orijinal bağlantıyı verir."),
    (Label.MULTI_SOURCE, "TRAILER_MEDIA", [("IGN", "https://www.ign.com/"), ("Eurogamer", "https://www.eurogamer.net/")],
     "Örnek: İki bağımsız yayın aynı gelişmeyi aktarıyor",
     "Örnek metin. Birbirinden bağımsız iki yayın organı aynı gelişmeyi bildiriyor. Bot, aynı ilk haberi "
     "kopyalayan siteleri tek kaynak sayar; bu etiket yalnızca gerçekten bağımsız kökenler için verilir."),
    (Label.SINGLE_SOURCE, "GAMEPLAY_TECH", [("Video Games Chronicle", "https://www.videogameschronicle.com/")],
     "Örnek: Tek bir yayın organı yeni ayrıntılar bildiriyor",
     "Örnek metin. Haber tek bir yayın organına dayanıyor ve resmî doğrulama içermiyor. Özet bu belirsizliği "
     "korur; kesinlik bildiren ifadeler doğrulama katmanında engellenir."),
    (Label.LEAK_CLAIM, "COMMUNITY_RUMOR", [("Insider Gaming", "https://insider-gaming.com/")],
     "Örnek: Doğrulanmamış bir sızıntı iddiası konuşuluyor",
     "Örnek metin. Bu tür içerik yalnızca ayarlarda açıkça izin verildiğinde yayımlanır ve her zaman iddia "
     "olarak etiketlenir. Varsayılan ayarda yayımlanmaz."),
    (Label.COMMUNITY_CLAIM, "COMMUNITY_RUMOR", [("r/GTA6", "https://www.reddit.com/r/GTA6/")],
     "Örnek: Topluluk forumunda bir iddia gündemde",
     "Örnek metin. Topluluk kaynaklı içerik asla resmî açıklama etiketi alamaz. Varsayılan ayarda "
     "yayımlanmaz; açıldığında belirgin bir uyarı notuyla gönderilir."),
]

HEAD = {Label.OFFICIAL: "Resmî açıklama", Label.MULTI_SOURCE: "Çoklu kaynak", Label.SINGLE_SOURCE: "Tek kaynak",
        Label.LEAK_CLAIM: "Sızıntı iddiası", Label.COMMUNITY_CLAIM: "Topluluk iddiası"}

ACCENT = {Label.OFFICIAL: "#3DDC97", Label.MULTI_SOURCE: "#4FA8FF", Label.SINGLE_SOURCE: "#FFD166",
          Label.LEAK_CLAIM: "#FF5C7A", Label.COMMUNITY_CLAIM: "#FF9A5A"}


def tg_to_html(text: str) -> str:
    # render_post çıktısı zaten kaçırılmış, Telegram HTML alt kümesidir; yalnızca satır sonlarını çevir.
    return text.replace("\n", "<br>")


def main() -> None:
    settings = Settings.model_validate(json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8")))
    cards = []
    for label, cat, srcs, title, summary in SAMPLES:
        c = GeneratedContent(title_tr=title, summary_tr=summary, category=cat, title_style="FACTUAL",
                             claim_type="REPORTED", source_urls=[s[1] for s in srcs], why_this_label="örnek",
                             needs_review=False)
        text = render_post(c, label, [{"name": n, "url": u} for n, u in srcs], settings, NOW)
        cards.append(f"""
      <article class="post" style="--accent:{ACCENT[label]}">
        <header class="post-head"><span class="dot" aria-hidden="true"></span>{HEAD[label]}</header>
        <div class="bubble">{tg_to_html(text)}<span class="meta">{len(text)} karakter · 21:40</span></div>
      </article>""")
    digest = render_digest({"sources_ok": 6, "sources_checked": 7, "new_items": 4, "gemini_calls": 2},
                           {"posts": []}, {"status": "YETERSİZ VERİ"}, settings, NOW)
    page = TEMPLATE.replace("{{CARDS}}", "".join(cards)).replace("{{DIGEST}}", tg_to_html(digest))
    out = ROOT / "docs" / "message_preview.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"Yazıldı: {out.relative_to(ROOT)}")


TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTA VI Türkiye Bülteni — mesaj şablonları</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@700;900&family=Instrument+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --night: #120B2E;
    --night-2: #1C1442;
    --bubble: #241A52;
    --ink: #F4EEFF;
    --muted: #A99CD6;
    --pink: #FF4F9A;
    --teal: #2EE6D6;
    --sun: #FF9A5A;
    --display: "Big Shoulders Display", "Arial Narrow", "Roboto Condensed", sans-serif;
    --body: "Instrument Sans", "Segoe UI", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  html { background: var(--night); color: var(--ink); }
  body { margin: 0; font: 400 16px/1.55 var(--body); }
  a { color: var(--teal); text-underline-offset: 3px; }
  a:focus-visible { outline: 2px solid var(--teal); outline-offset: 3px; border-radius: 2px; }

  .horizon {
    position: relative; overflow: hidden; padding: 72px 24px 56px;
    background:
      radial-gradient(120% 90% at 50% 120%, rgba(255,154,90,.55) 0%, rgba(255,79,154,.35) 35%, transparent 65%),
      linear-gradient(180deg, #0C0722 0%, var(--night) 100%);
    border-bottom: 1px solid rgba(46,230,214,.25);
  }
  .horizon::after {           /* tek cesur öğe: ufukta batan, şeritli Vice City güneşi */
    content: ""; position: absolute; right: max(24px, calc(50% - 540px)); bottom: 0;
    width: min(380px, 60vw); aspect-ratio: 2 / 1; border-radius: 999px 999px 0 0;
    background:
      repeating-linear-gradient(180deg, transparent 0 46%, transparent 46%),
      linear-gradient(180deg, transparent 0 52%, var(--night) 52% 56%, transparent 56% 66%,
                      var(--night) 66% 72%, transparent 72% 80%, var(--night) 80% 88%, transparent 88%),
      linear-gradient(180deg, #FFD166 0%, var(--sun) 45%, var(--pink) 100%);
    box-shadow: 0 0 80px rgba(255,79,154,.35);
  }
  .horizon-inner { position: relative; z-index: 1; max-width: 1080px; margin: 0 auto; }
  h1 {
    margin: 0; font: 900 clamp(48px, 9vw, 104px)/.9 var(--display); letter-spacing: -.01em;
    color: var(--ink); text-shadow: 0 0 28px rgba(255,79,154,.45);
  }
  .lede { max-width: 60ch; margin: 18px 0 0; color: var(--muted); font-size: 17px; }

  main { max-width: 1080px; margin: 0 auto; padding: 48px 24px 80px; }
  h2 { font: 700 30px/1.1 var(--display); margin: 0 0 6px; }
  .section-note { color: var(--muted); margin: 0 0 24px; max-width: 70ch; }

  .feed { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 28px 24px; }
  .post-head { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 14px; color: var(--accent); margin-bottom: 8px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); }
  .bubble {
    position: relative; background: var(--bubble); border-radius: 4px 16px 16px 16px;
    padding: 14px 16px 26px; font-size: 15px; line-height: 1.5;
    border-left: 3px solid var(--accent);
  }
  .bubble b { font-weight: 600; }
  .bubble i { color: var(--muted); }
  .meta { position: absolute; right: 12px; bottom: 6px; font-size: 12px; color: var(--muted); }

  .split { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 56px; align-items: start; }
  .rules { margin: 0; padding-left: 20px; color: var(--ink); }
  .rules li { margin-bottom: 10px; }
  .rules li::marker { color: var(--pink); }
  .admin .bubble { border-left-color: var(--teal); }
  footer { max-width: 1080px; margin: 0 auto; padding: 0 24px 48px; color: var(--muted); font-size: 14px; }

  @media (max-width: 760px) { .split { grid-template-columns: 1fr; } .horizon { padding-top: 48px; } }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
</head>
<body>
  <section class="horizon">
    <div class="horizon-inner">
      <h1>Gece bülteni,<br>ışıklar açık.</h1>
      <p class="lede">GTA VI Türkiye Bülteni’nin Telegram kanalına giden mesajların önizlemesi. Her kart,
      botun gerçekte gönderdiği metni üreten şablonla oluşturuldu; içerikler örnektir, gerçek haber değildir.</p>
    </div>
  </section>

  <main>
    <h2>Kanal gönderileri</h2>
    <p class="section-note">Her gönderide tek bir renkli rozet, doğrulama düzeyini söyleyen etiket, kalın başlık,
    iki üç cümlelik özet ve orijinal kaynak bağlantısı bulunur. Rozet rengi doğrulama düzeyini gösterir.</p>
    <div class="feed">{{CARDS}}
    </div>

    <div class="split">
      <section>
        <h2>Şablon kuralları</h2>
        <ul class="rules">
          <li>Gönderi başına tek emoji: renk kodlu rozet. Başka süsleme yok.</li>
          <li>Etiketi model değil, kaynak doğrulama kuralları belirler.</li>
          <li>Tek kaynak ve iddia gönderilerinde doğrulama notu italik yazılır.</li>
          <li>Kaynak bağlantısı her gönderide zorunlu; en fazla üç kaynak gösterilir.</li>
          <li>Tüm metin Telegram HTML’ine güvenli biçimde kaçırılır, 4096 karakter sınırı denetlenir.</li>
        </ul>
      </section>
      <section class="admin">
        <h2>Yönetici özeti</h2>
        <p class="section-note">Günde iki kez, 06:00 ve 18:00 UTC civarında yalnızca yönetici sohbetine gider.</p>
        <div class="bubble">{{DIGEST}}</div>
      </section>
    </div>
  </main>
  <footer>Önizleme <code>python tools/render_preview.py</code> ile yeniden üretilir.</footer>
</body>
</html>
"""

if __name__ == "__main__":
    main()
