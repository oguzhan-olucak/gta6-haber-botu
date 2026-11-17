"""Site duman testi: docs/ sitesini yerel sunucuda gerçek bir tarayıcıyla açar ve
kırılım × veri modu matrisini doğrular.

Denetimler (her genişlikte: 390 mobil, 820 tablet, 1440 masaüstü):
- yatay taşma yok, JavaScript/konsol hatası yok;
- gerçek akış (``?demo=0``): boş durum ve boş manşet görünür (gerçek akış boşsa);
- varsayılan açılış: gerçek akış boşsa örnek bülten otomatik açılır; doluysa gerçek veri;
- harita: 5 iğne; bir bölgeye tıklayınca bölge paneli açılır ve akış yalnızca o bölgeyi gösterir;
- Telegram önizleme ve "Nasıl doğruluyoruz" çekmeceleri açılır ve ekrana sığar.

Kullanım:
    python tools/site_check.py                 # matris
    python tools/site_check.py --shots out/    # ayrıca ekran görüntüsü kaydet

Ağ erişimi yoktur: yalnızca 127.0.0.1 üzerinde geçici bir statik sunucu açılır. Playwright yoksa
yalnızca Chrome ``--dump-dom`` ile temel denetim yapılır (Chrome başsız modda pencere genişliği en az
500 px olduğundan 390 px o modda gerçekten sınanamaz; çıktı bunu belirtir). Hiçbir tarayıcı yoksa
çıkış kodu 0 ile "atlandı" yazar; ``--strict`` ile hata sayılır.
"""
from __future__ import annotations

import argparse
import functools
import html
import json
import re
import shutil
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
WIDTHS = (390, 820, 1440)
REGION_COUNT = 5


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D401 - sessiz sunucu
        pass


def find_chrome() -> str | None:
    """Kurulu Chrome/Chromium yürütülebilir dosyası."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def expected_items(name: str) -> int:
    path = DOCS / "data" / name
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("items", []))
    except (OSError, ValueError):
        return 0


def _serve() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(DOCS)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def _check_selftest(tag: str, r: dict[str, Any], mode: str, real_n: int, demo_n: int) -> list[str]:
    errors: list[str] = []
    if not r:
        return [f"{tag}: selftest sonucu yok (JS hatası?)"]
    if r.get("overflowX"):
        errors.append(f"{tag}: yatay taşma {r.get('wide')}")
    want_mode = "demo" if mode == "default" and real_n == 0 else "real"
    if r.get("mode") != want_mode:
        errors.append(f"{tag}: mod {r.get('mode')} (beklenen {want_mode}; gerçek veri öncelikli olmalı)")
    n = demo_n if want_mode == "demo" else real_n
    if r.get("items") != n:
        errors.append(f"{tag}: {r.get('items')} haber (beklenen {n})")
    if r.get("pins") != REGION_COUNT:
        errors.append(f"{tag}: harita iğnesi {r.get('pins')} (beklenen {REGION_COUNT})")
    if n == 0 and (not r.get("emptyVisible") or r.get("hero") != "empty"):
        errors.append(f"{tag}: boş durum görünmüyor")
    if n > 0 and (r.get("hero") != "filled" or r.get("cards") != n - 1):
        errors.append(f"{tag}: manşet/kart sayısı hatalı ({r})")
    return errors


def _on_page_error(tag: str, out: list[str]) -> Any:
    def handler(err: Any) -> None:
        out.append(f"{tag}: JS hatası: {err}")
    return handler


def _on_console(tag: str, out: list[str]) -> Any:
    def handler(msg: Any) -> None:
        # Web yazı tipleri çevrimdışı ortamda yüklenemez; bu bir site hatası değildir.
        if msg.type == "error" and "fonts.g" not in msg.text and "ERR_" not in msg.text:
            out.append(f"{tag}: konsol: {msg.text}")
    return handler


def run_playwright(shots: Path | None = None) -> list[str]:
    """Playwright ile tam etkileşim matrisi. Hata listesini döndürür (boş = başarılı)."""
    from playwright.sync_api import sync_playwright  # isteğe bağlı bağımlılık

    server, base = _serve()
    real_n, demo_n = expected_items("feed.json"), expected_items("demo-feed.json")
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:  # paketli Chromium yoksa sistem Chrome'u
                chrome = find_chrome()
                if chrome is None:
                    raise
                browser = p.chromium.launch(executable_path=chrome)
            for mode, query in (("real", "?demo=0&selftest=1"), ("default", "?selftest=1")):
                for w in WIDTHS:
                    tag = f"{mode}@{w}"
                    page = browser.new_page(viewport={"width": w, "height": 900})
                    js_errors: list[str] = []
                    page.on("pageerror", _on_page_error(tag, js_errors))
                    page.on("console", _on_console(tag, js_errors))
                    page.goto(base + query)
                    page.wait_for_timeout(1600)
                    raw = page.evaluate("document.documentElement.getAttribute('data-selftest')")
                    errors += _check_selftest(tag, json.loads(raw) if raw else {}, mode, real_n, demo_n)
                    if shots is not None:
                        shots.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(shots / f"{mode}-{w}.png"), full_page=True)
                    if mode == "default" and (real_n or demo_n):
                        errors += _interact(page, tag, shots, mode, w)
                    errors += js_errors
                    page.close()
            errors += _image_check(browser, base, shots)
            browser.close()
    finally:
        server.shutdown()
    return errors


def _png() -> bytes:
    """Ağ gerektirmeyen 64×36 düz renkli PNG (sahte kaynak görseli)."""
    import struct
    import zlib
    w, h = 64, 36
    raw = b"".join(b"\x00" + bytes((255, 80 + y * 3, 120)) * w for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _image_check(browser: Any, base: str, shots: Path | None) -> list[str]:
    """Görselli besleme: kaynak görseli kartta ve çekmecede görünür; bozuk görselde SVG kapağa düşülür."""
    demo = json.loads((DOCS / "data" / "demo-feed.json").read_text(encoding="utf-8"))
    demo["demo"] = False
    for i, it in enumerate(demo["items"]):
        if i % 2 == 0:
            it["image"] = f"https://media-rockstargames-com.akamaized.net/test/{i}.png"
            it["image_credit"] = it["sources"][0]["name"]
        elif i % 3 == 1:
            it["image"] = f"https://assets-prd.ignimgs.com/broken/{i}.png"
    body = "window.__GTA6_FEED__ = " + json.dumps(demo, ensure_ascii=False) + ";"
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.route("**/data/feed.js*", lambda r: r.fulfill(status=200, content_type="application/javascript", body=body))
    page.route("**/data/feed.json*", lambda r: r.fulfill(status=404, body=""))
    page.route("https://media-rockstargames-com.akamaized.net/**",
               lambda r: r.fulfill(status=200, content_type="image/png", body=_png()))
    page.route("https://assets-prd.ignimgs.com/**", lambda r: r.fulfill(status=404, body=""))
    errors: list[str] = []
    page.goto(base + "?selftest=1")
    page.wait_for_timeout(600)
    # Akış artık haritanın, videoların ve rehberlerin altında: tembel yüklenen görseller görünür alana gelsin.
    page.evaluate("() => { const g = document.querySelector('#grid'); if (g) g.scrollIntoView(); }")
    page.wait_for_timeout(600)
    page.evaluate("() => window.scrollBy(0, 1200)")
    page.wait_for_timeout(1200)
    res = page.evaluate("""() => ({
        loaded: document.querySelectorAll('#grid .card__img.is-loaded').length,
        imgs: document.querySelectorAll('#grid .card__img').length,
        credits: document.querySelectorAll('#grid .card__cover .credit').length,
        mode: JSON.parse(document.documentElement.getAttribute('data-selftest') || '{}').mode })""")
    if res["mode"] != "real":
        errors.append(f"görsel: gerçek besleme seçilmedi ({res['mode']})")
    if res["loaded"] < 3:
        errors.append(f"görsel: kartlarda yüklenen kaynak görseli az ({res['loaded']})")
    if res["imgs"] != res["loaded"] or res["credits"] != res["loaded"]:
        errors.append(f"görsel: bozuk görsel SVG kapağa düşmedi ({res})")
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        page.evaluate("document.getElementById('akis').scrollIntoView()")
        page.wait_for_timeout(400)
        page.screenshot(path=str(shots / "images-1440.png"))
    page.close()
    return errors


def _overflow(page: Any) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth > innerWidth + 1"))


def _interact(page: Any, tag: str, shots: Path | None, mode: str, w: int) -> list[str]:
    errors: list[str] = []
    region = page.evaluate("(document.querySelector('.card[data-region]')||{}).dataset?.region || 'vice_city'")
    page.focus(f'.pin[data-region="{region}"]')   # klavye yolu: iğneye odaklan + Enter
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    info = page.evaluate("""() => ({
        panel: !document.getElementById('region-panel').hidden,
        regions: [...document.querySelectorAll('#grid .card')].map(c => c.dataset.region),
        pill: !document.getElementById('region-pill').hidden })""")
    if not info["panel"] or not info["pill"]:
        errors.append(f"{tag}: bölge tıklanınca panel/etiket açılmadı")
    if any(r != region for r in info["regions"]):
        errors.append(f"{tag}: bölge süzgeci başka bölgelerden haber gösteriyor {info['regions']}")
    if _overflow(page):
        errors.append(f"{tag}: bölge seçiliyken yatay taşma")
    if shots is not None:
        page.screenshot(path=str(shots / f"{mode}-{w}-bolge.png"))
    page.click("#region-close")
    page.wait_for_timeout(300)
    if page.evaluate("!document.getElementById('region-panel').hidden"):
        errors.append(f"{tag}: bölge paneli kapanmadı")
    for sheet, hash_ in (("telegram", "#telegram"), ("method", "#yontem")):
        page.evaluate(f"location.hash = '{hash_}'")
        for _ in range(25):   # açılış animasyonu bitene kadar bekle (CSP eval'e izin vermez: yoklama)
            page.wait_for_timeout(120)
            if not page.evaluate(f"document.getElementById('{sheet}').getAnimations()"
                                 ".some(a => a.playState === 'running')"):
                break
        state = page.evaluate(f"""() => {{ const d = document.getElementById('{sheet}');
            const r = d.getBoundingClientRect(); return {{ open: d.open, right: r.right, w: innerWidth }}; }}""")
        if not state["open"]:
            errors.append(f"{tag}: '{sheet}' çekmecesi açılmadı")
        elif state["right"] > state["w"] + 1:
            errors.append(f"{tag}: '{sheet}' çekmecesi ekrana sığmıyor")
        if shots is not None and state["open"]:
            page.screenshot(path=str(shots / f"{mode}-{w}-{sheet}.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        page.evaluate("history.replaceState(null, '', location.pathname + location.search)")
    return errors


def run_dump_dom(chrome: str) -> list[str]:
    """Yedek: Chrome --dump-dom ile yalnızca selftest denetimi (min. pencere genişliği 500 px)."""
    server, base = _serve()
    real_n, demo_n = expected_items("feed.json"), expected_items("demo-feed.json")
    errors: list[str] = []
    try:
        for mode, query in (("real", "?demo=0&selftest=1"), ("default", "?selftest=1")):
            for w in WIDTHS:
                out = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                                      f"--window-size={w},1800", "--virtual-time-budget=4000", "--dump-dom",
                                      base + query], capture_output=True, text=True, timeout=60).stdout
                m = re.search(r'data-selftest="([^"]+)"', out)
                r = json.loads(html.unescape(m.group(1))) if m else {}
                errors += _check_selftest(f"{mode}@{max(w, 500)}", r, mode, real_n, demo_n)
    finally:
        server.shutdown()
    return errors


def run(shots: Path | None = None) -> list[str]:
    """Kullanılabilir en iyi yöntemle matrisi çalıştırır."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        chrome = find_chrome()
        if chrome is None:
            raise FileNotFoundError("tarayıcı bulunamadı") from None
        print("not: Playwright yok; Chrome --dump-dom yedeği (390 px yerine 500 px) kullanılıyor")
        return run_dump_dom(chrome)
    return run_playwright(shots)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="docs/ site duman testi")
    ap.add_argument("--shots", type=Path, help="ekran görüntülerinin yazılacağı klasör")
    ap.add_argument("--strict", action="store_true", help="tarayıcı yoksa hata ver")
    args = ap.parse_args(argv)
    try:
        errors = run(args.shots)
    except FileNotFoundError:
        print("atlandı: tarayıcı bulunamadı")
        return 1 if args.strict else 0
    for e in errors:
        print("✗", e)
    print("site_check:", "TAMAM" if not errors else f"{len(errors)} sorun")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
