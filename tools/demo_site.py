"""Haber sitesi için 12 haberlik DEMO beslemesi.

Haberler elle feed.json'a yazılmaz: botun gerçek hattından geçer (toplama → olay kümeleme →
deterministik etiket → çıktı doğrulama → idempotent yayın → ``site_exporter``). Bot her haber
için o haberin saatinde bir kez çalıştırılır; böylece yayın zamanları gerçekçi dağılır ve önceki
haberlerin tekrar elemesi de sınanır. Sahte servisler kullanılır, ağ erişimi yoktur.

Bu metinler ÖRNEKTİR, gerçek haber değildir; ``feed.json`` içinde ``"demo": true`` işaretlenir ve
site bunu açıkça gösterir. Kaynak bağlantıları uydurma makale adresleri değil, yayınların ana
sayfalarıdır.
"""
from __future__ import annotations

import html
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot import main as bot_main
from bot.site_exporter import Feed

ROOT = Path(__file__).resolve().parent.parent
END = datetime(2026, 11, 16, 19, 0, tzinfo=timezone.utc)   # 22:00 TSİ

SOURCES: dict[str, dict[str, Any]] = {
    "rockstar_newswire_html": {"name": "Rockstar Newswire", "trust_class": "OFFICIAL", "kind": "html_listing",
                               "feed_url": "https://www.rockstargames.com/newswire",
                               "link_pattern": "^/newswire/article/", "allowed_domains": ["rockstargames.com"],
                               "origin_group": "rockstar"},
    "take_two_ir_html": {"name": "Take-Two Interactive", "trust_class": "OFFICIAL", "kind": "html_listing",
                         "feed_url": "https://ir.take2games.com/news-releases", "link_pattern": "/news-release",
                         "allowed_domains": ["take2games.com"], "origin_group": "take_two"},
    "ign": {"name": "IGN", "feed": "https://feeds.example-ign.test/games.xml", "domain": "ign.com"},
    "eurogamer": {"name": "Eurogamer", "feed": "https://www.eurogamer.net/feed", "domain": "eurogamer.net"},
    "gamesradar": {"name": "GamesRadar+", "feed": "https://www.gamesradar.com/rss/", "domain": "gamesradar.com",
                   "group": "future_plc"},
    "pcgamer": {"name": "PC Gamer", "feed": "https://www.pcgamer.com/rss/", "domain": "pcgamer.com",
                "group": "future_plc"},
    "vgc": {"name": "Video Games Chronicle", "feed": "https://www.videogameschronicle.com/feed/",
            "domain": "videogameschronicle.com"},
    "insider_gaming": {"name": "Insider Gaming", "feed": "https://insider-gaming.com/feed/",
                       "domain": "insider-gaming.com"},
    "reddit_gta6": {"name": "r/GTA6", "feed": "https://www.reddit.com/r/GTA6/new/.rss", "domain": "reddit.com",
                    "trust": "COMMUNITY"},
}


@dataclass
class Report:
    """Bir haberin tek yayın organındaki hâli."""
    source: str
    title: str
    path: str
    desc: str


@dataclass
class Story:
    """Bir olay: bir veya birden çok rapor + modelin (senaryolu) Türkçe çıktısı."""
    hours_ago: float
    reports: list[Report]
    title_tr: str
    summary_tr: str
    category: str
    claim: str = "REPORTED"
    style: str = "FACTUAL"


STORIES: list[Story] = [
    Story(44, [Report("eurogamer", "Rockstar audio director talks GTA 6 radio stations", "/gta-6-radio-interview",
                      "In an interview with Eurogamer, Rockstar's audio director said GTA 6 features more radio "
                      "stations than GTA 5.")],
          "Rockstar ses yönetmeni GTA VI radyolarını anlattı",
          "Eurogamer'a konuşan Rockstar ses yönetmeni, GTA 6'da GTA 5'ten daha fazla radyo istasyonu bulunduğunu "
          "belirtti. Röportajda istasyon sayısına dair net bir rakam verilmedi.", "GAMEPLAY_TECH"),
    Story(40, [Report("ign", "GTA 6 preload size is 150GB on PS5", "/articles/gta-6-preload-size",
                      "Grand Theft Auto 6 will require 150GB of storage on PlayStation 5, according to the "
                      "PlayStation Store listing."),
               Report("vgc", "GTA VI needs 150GB of free space on PlayStation 5, store listing shows",
                      "/news/gta-6-150gb", "The PlayStation Store page for GTA 6 lists a 150GB download ahead of launch.")],
          "GTA VI, PlayStation 5'te 150GB alan istiyor",
          "IGN ve Video Games Chronicle, PlayStation Store listesine göre GTA 6'nın PlayStation 5'te 150GB "
          "depolama alanı gerektirdiğini bildiriyor.", "RELEASE_PLATFORMS"),
    Story(36, [Report("take_two_ir_html", "Take-Two Interactive Reports Results for Fiscal Second Quarter",
                      "/news-releases/news-release-details/fiscal-second-quarter",
                      "Grand Theft Auto VI remains on track to launch November 19, 2026, the company said.")],
          "Take-Two, GTA VI'ın 19 Kasım takviminin sürdüğünü açıkladı",
          "Take-Two Interactive, ikinci çeyrek sonuçlarını duyurduğu bültende Grand Theft Auto VI'ın 19 Kasım "
          "2026 çıkışı için takvimde olduğunu bildirdi.", "INDUSTRY_BUSINESS", "OFFICIAL"),
    Story(30, [Report("insider_gaming", "GTA 6 leak allegedly shows unannounced Leonida island", "/gta-6-leak-island",
                      "An alleged leak claims an unannounced island exists in Leonida. Rockstar has not commented.")],
          "Bir sızıntı, GTA VI'da duyurulmamış bir ada olduğunu iddia ediyor",
          "Insider Gaming'in aktardığı doğrulanmamış bir sızıntıya göre Leonida'da henüz duyurulmamış bir ada "
          "bulunuyor. Rockstar konu hakkında yorum yapmadı.", "COMMUNITY_RUMOR", "RUMOR"),
    Story(26, [Report("gamesradar", "GTA 6 accessibility options listed on Rockstar support page",
                      "/gta-6-accessibility-options",
                      "GamesRadar spotted subtitle size, colour filter and control remapping options for GTA 6 on "
                      "Rockstar's support site.")],
          "GTA VI'ın erişilebilirlik seçenekleri destek sayfasında listelendi",
          "GamesRadar+'ın aktardığına göre Rockstar destek sitesinde GTA 6 için altyazı boyutu, renk filtresi ve "
          "tuş atama seçenekleri yer alıyor.", "GAMEPLAY_TECH"),
    Story(22, [Report("reddit_gta6", "Fans think they spotted Ocean Drive in the GTA 6 launch trailer",
                      "/r/GTA6/comments/ocean-drive",
                      "Users on r/GTA6 compared frames from the launch trailer with real Ocean Drive photos.")],
          "Hayranlar GTA VI fragmanında Ocean Drive'ı gördüklerini düşünüyor",
          "r/GTA6 kullanıcıları, fragmandaki kareleri gerçek Ocean Drive fotoğraflarıyla karşılaştırdıklarını "
          "iddia ediyor; benzerlik Rockstar tarafından teyit edilmiş değil.", "COMMUNITY_RUMOR", "RUMOR"),
    Story(18, [Report("rockstar_newswire_html", "Grand Theft Auto VI Pre-Load Now Available",
                      "/newswire/article/pl19/grand-theft-auto-vi-pre-load",
                      "Pre-load Grand Theft Auto VI now ahead of its November 19 launch on PlayStation 5 and "
                      "Xbox Series X|S.")],
          "GTA VI için ön yükleme başladı",
          "Rockstar Games, Grand Theft Auto VI'ın 19 Kasım çıkışı öncesinde PlayStation 5 ve Xbox Series X|S "
          "için ön yüklemenin açıldığını duyurdu.", "RELEASE_PLATFORMS", "OFFICIAL"),
    Story(14, [Report("eurogamer", "GTA 6 reviews will go live on November 18", "/gta-6-review-embargo",
                      "Reviews for GTA 6 will be published on November 18, one day before the game launches."),
               Report("gamesradar", "GTA 6 review embargo set for November 18, a day before launch",
                      "/gta-6-review-embargo-date",
                      "The GTA 6 review embargo lifts on November 18, one day ahead of release.")],
          "GTA VI incelemeleri 18 Kasım'da yayımlanacak",
          "Eurogamer ve GamesRadar+, GTA 6 inceleme yasağının 18 Kasım'da, çıkıştan bir gün önce kalkacağını "
          "bildiriyor.", "OTHER"),
    Story(10, [Report("vgc", "GTA 6 physical edition spotted on UK retailer shelves", "/news/gta-6-boxed-copies",
                      "Video Games Chronicle reports that boxed copies of GTA 6 have appeared at a UK retailer "
                      "ahead of launch.")],
          "GTA VI'ın kutulu sürümü İngiltere'de raflarda görüldü",
          "Video Games Chronicle'ın haberine göre GTA 6'nın kutulu kopyaları, çıkıştan önce İngiltere'deki bir "
          "perakendecide raflara çıktı.", "RELEASE_PLATFORMS"),
    Story(7, [Report("ign", "GTA 6 needs 145GB on Xbox Series X", "/articles/gta-6-xbox-size",
                     "The Xbox Series X version of Grand Theft Auto 6 is a 145GB download, per the Microsoft Store."),
              Report("pcgamer", "GTA 6's Xbox Series X download weighs in at 145GB", "/gta-6-xbox-series-x-145gb",
                     "Microsoft Store lists the Xbox Series X download of GTA 6 at 145GB.")],
          "GTA VI, Xbox Series X'te 145GB yer kaplayacak",
          "IGN ve PC Gamer, Microsoft Store listesine göre GTA 6'nın Xbox Series X sürümünün 145GB indirme "
          "boyutunda olduğunu bildiriyor.", "RELEASE_PLATFORMS"),
    Story(4, [Report("ign", "GTA 6 photo mode detailed in hands-on preview", "/articles/gta-6-photo-mode-preview",
                     "IGN's hands-on preview says GTA 6's photo mode offers filters and lens options.")],
          "GTA VI'ın fotoğraf modu ön incelemede ayrıntılandı",
          "IGN'in ön inceleme yazısına göre GTA 6'daki fotoğraf modu, filtre ve lens seçenekleri sunuyor.",
          "GAMEPLAY_TECH"),
    Story(2, [Report("rockstar_newswire_html", "Grand Theft Auto VI Launch Trailer",
                     "/newswire/article/lt19/grand-theft-auto-vi-launch-trailer",
                     "Watch the Launch Trailer for Grand Theft Auto VI, coming November 19 to PlayStation 5 and "
                     "Xbox Series X|S.")],
          "Rockstar, GTA VI'ın çıkış fragmanını yayımladı",
          "Rockstar Games, Grand Theft Auto VI için çıkış fragmanını Newswire'da paylaştı. Oyun 19 Kasım'da "
          "PlayStation 5 ve Xbox Series X|S için çıkacak.", "TRAILER_MEDIA", "OFFICIAL"),
]


def _url(r: Report) -> str:
    src = SOURCES[r.source]
    if "feed_url" in src:
        base = src["feed_url"].split("/news-releases")[0].split("/newswire")[0]
        return base + r.path
    return f"https://www.{src['domain']}{r.path}"


def _source_defs() -> list[dict[str, Any]]:
    out = []
    for sid, s in SOURCES.items():
        if "feed_url" in s:
            out.append({"id": sid, **s})
        else:
            out.append({"id": sid, "name": s["name"], "trust_class": s.get("trust", "ESTABLISHED_MEDIA"),
                        "feed_url": s["feed"], "allowed_domains": [s["domain"]],
                        "origin_group": s.get("group", sid)})
    return out


def _pages(now: datetime) -> dict[str, bytes]:
    """Yalnızca ``now`` anına kadar yayımlanmış raporları içeren sahte kaynak sayfaları."""
    by_src: dict[str, list[tuple[Report, datetime]]] = {}
    for st in STORIES:
        when = END - timedelta(hours=st.hours_ago)
        if when <= now:
            for i, r in enumerate(st.reports):
                by_src.setdefault(r.source, []).append((r, when - timedelta(minutes=10 * (i + 1))))
    pages: dict[str, bytes] = {}
    for sid, src in SOURCES.items():
        reps = by_src.get(sid, [])
        if "feed_url" in src:   # resmî HTML liste: JSON-LD ile tarih
            ld = [{"@type": "NewsArticle", "url": _url(r), "headline": r.title, "description": r.desc,
                   "datePublished": w.isoformat()} for r, w in reps]
            pages[src["feed_url"]] = (f'<main><script type="application/ld+json">{json.dumps(ld)}</script></main>'
                                      ).encode()
        else:
            body = "".join(f"<item><title>{html.escape(r.title)}</title><link>{_url(r)}</link>"
                           f"<description>{html.escape(r.desc)}</description>"
                           f"<pubDate>{w.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate></item>" for r, w in reps)
            pages[src["feed"]] = f"<rss version='2.0'><channel>{body}</channel></rss>".encode()
    return pages


class StoryGenerator:
    """İstemdeki kaynak URL'sine göre ilgili haberin senaryolu Türkçe çıktısını döndürür."""

    def __init__(self) -> None:
        self.by_url: dict[str, Story] = {_canon(_url(r)): st for st in STORIES for r in st.reports}

    def generate(self, system_instruction: str, prompt: str, schema: dict[str, Any]) -> str:
        """Senaryolu JSON."""
        start = prompt.index("<untrusted_source_data>") + len("<untrusted_source_data>")
        records = json.loads(prompt[start:prompt.index("</untrusted_source_data>")])
        st = next(self.by_url[r["url"]] for r in records if r["url"] in self.by_url)
        return json.dumps({"title_tr": st.title_tr, "summary_tr": st.summary_tr, "category": st.category,
                           "title_style": st.style, "claim_type": st.claim, "why_this_label": "demo",
                           "needs_review": False, "translations": {},
                           "source_urls": [r["url"] for r in records]}, ensure_ascii=False)


def _canon(url: str) -> str:
    from bot.collector import canonicalize_url
    return canonicalize_url(url)


def build_demo_feed(out_dir: Path, telegram_factory: Any, session_cls: Any, env: dict[str, str]) -> Feed:
    """12 haberi zaman sırasıyla bot hattından geçirir ve demo beslemesini ``out_dir``'e yazar."""
    from bot.config import Settings, load_sources
    from bot.site_exporter import build_feed, export_site_feed
    with tempfile.TemporaryDirectory(prefix="demo-site-") as tmp:
        cfg, data = Path(tmp) / "config", Path(tmp) / "data"
        cfg.mkdir()
        data.mkdir()
        settings = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
        settings.update({"verify_source_urls": False, "min_minutes_between_posts": 0, "allow_community_rumors": True,
                         "min_publish_threshold": 20, "max_daily_posts": 20, "max_gemini_calls_per_run": 10,
                         "public_channel_username": "gta6turkiyebulteni", "export_site_feed": False})
        (cfg / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        (cfg / "sources.json").write_text(json.dumps({"sources": _source_defs()}), encoding="utf-8")
        gen, tg = StoryGenerator(), telegram_factory()
        for st in sorted(STORIES, key=lambda s: -s.hours_ago):
            now = END - timedelta(hours=st.hours_ago) + timedelta(minutes=5)
            bot_main.run(now=now, env=env, session=session_cls(_pages(now)), telegram=tg, generator=gen,
                         data_dir=data, config_dir=cfg, url_verifier=lambda u, a, h: (True, u))
        history = json.loads((data / "history.json").read_text(encoding="utf-8"))
        state = json.loads((data / "state.json").read_text(encoding="utf-8"))
        s = Settings.model_validate(settings)
        feed = build_feed(history, state, s, load_sources(cfg / "sources.json"), END + timedelta(minutes=5), demo=True)
    export_site_feed(feed, out_dir, basename="demo-feed", var_name="__GTA6_DEMO_FEED__")
    return feed
