"""Site duman testi: docs/ sitesini yerel sunucuda headless Chrome ile açar ve kırılım × veri modu
matrisini doğrular (taşma yok, boş/örnek durum doğru, kart sayısı beklenen).

Kullanım:
    python tools/site_check.py                 # 390/820/1440 × gerçek + örnek
    python tools/site_check.py --shots out/    # ayrıca ekran görüntüsü kaydet

Ağ erişimi yoktur: yalnızca 127.0.0.1 üzerinde geçici bir statik sunucu açılır. Chrome yoksa
çıkış kodu 0 ile "atlandı" yazar (CI'yı kırmaz); ``--strict`` ile hata sayılır.
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

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
WIDTHS = (390, 820, 1440)


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


def selftest(chrome: str, url: str, width: int) -> dict[str, object]:
    """Sayfayı ?selftest=1 ile açar, <html data-selftest> sonucunu döndürür."""
    out = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                          f"--window-size={width},2400", "--virtual-time-budget=3000", "--dump-dom", url],
                         capture_output=True, text=True, timeout=60).stdout
    m = re.search(r'data-selftest="([^"]+)"', out)
    return json.loads(html.unescape(m.group(1))) if m else {}


def expected_items(name: str) -> int:
    path = DOCS / "data" / name
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("items", []))
    except (OSError, ValueError):
        return 0


def run(shots: Path | None = None) -> list[str]:
    """Matrisi çalıştırır; hata mesajları listesini döndürür (boş = başarılı)."""
    chrome = find_chrome()
    if chrome is None:
        raise FileNotFoundError("Chrome bulunamadı")
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(DOCS)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    real_n, demo_n = expected_items("feed.json"), expected_items("demo-feed.json")
    errors: list[str] = []
    try:
        for mode, query in (("real", "?selftest=1"), ("demo", "?demo=1&selftest=1")):
            for w in WIDTHS:
                r = selftest(chrome, base + query, w)
                tag = f"{mode}@{w}"
                if not r:
                    errors.append(f"{tag}: selftest sonucu yok (JS hatası?)")
                    continue
                if r.get("overflowX"):
                    errors.append(f"{tag}: yatay taşma")
                want_mode = "demo" if mode == "demo" and real_n == 0 else "real"
                if r.get("mode") != want_mode:
                    errors.append(f"{tag}: mod {r.get('mode')} (beklenen {want_mode}; gerçek veri öncelikli olmalı)")
                n = demo_n if want_mode == "demo" else real_n
                if r.get("items") != n:
                    errors.append(f"{tag}: {r.get('items')} haber (beklenen {n})")
                if n == 0 and (not r.get("emptyVisible") or r.get("hero") != "empty"):
                    errors.append(f"{tag}: boş durum görünmüyor")
                if n > 0 and (r.get("hero") != "filled" or r.get("cards") != n - 1):
                    errors.append(f"{tag}: manşet/kart sayısı hatalı ({r})")
                if shots is not None:
                    shots.mkdir(parents=True, exist_ok=True)
                    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                                    f"--window-size={w},2600", "--virtual-time-budget=3000",
                                    f"--screenshot={shots / f'{mode}-{w}.png'}", base + query],
                                   capture_output=True, timeout=60)
    finally:
        server.shutdown()
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="docs/ site duman testi")
    ap.add_argument("--shots", type=Path, help="ekran görüntülerinin yazılacağı klasör")
    ap.add_argument("--strict", action="store_true", help="Chrome yoksa hata ver")
    args = ap.parse_args(argv)
    try:
        errors = run(args.shots)
    except FileNotFoundError:
        print("atlandı: Chrome bulunamadı")
        return 1 if args.strict else 0
    for e in errors:
        print("✗", e)
    print("site_check:", "TAMAM" if not errors else f"{len(errors)} sorun")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
