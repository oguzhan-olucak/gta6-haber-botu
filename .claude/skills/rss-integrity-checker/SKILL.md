---
name: rss-integrity-checker
description: RSS/Atom ayrıştırma, URL canonicalization, yönlendirme takibi, kaynak sınıfı eşleşmesi ve bozuk XML izolasyonunu test eder. sources.json değiştiğinde veya yeni kaynak eklendiğinde kullan.
---
# rss-integrity-checker

## Yeni kaynak eklerken
- `trust_class` yalnızca `OFFICIAL` (rockstargames.com, take2games.com), `ESTABLISHED_MEDIA`, `COMMUNITY`, `UNKNOWN`.
- `allowed_domains` öğe bağlantılarının gerçek alan adı olmalı (feedburner gibi ara alan adları değil).
- Aynı yayın grubundaki siteler aynı `origin_group` (ör. GamesRadar+ ve PC Gamer = `future_plc`), böylece bağımsız iki kaynak sayılmaz.
- Canlı doğrulanmamış besleme `rss_verified: false` kalır; ilk `workflow_dispatch` özetindeki `source_status` ile kontrol edilir.

## Resmî kaynaklar
- `kind: google_news` ve `kind: html_listing` için nihai URL resmî alan adında ve `url_verified=True` olmalı; aksi halde öğe atılır.
- Google News ara adımı yalnızca `hop_domains=["news.google.com"]` ile izinlidir; nihai adres değil.

## Testler
`python -m pytest -q tests/test_collector.py` — XXE reddi, Atom desteği, alan adı nokta sınırı (`evilign.com` ≠ `ign.com`), takip parametresi temizliği, bozuk kaynağın izolasyonu, güvenli yönlendirme ve yabancı canonical reddi.

## Ne zaman tetiklenir
config/sources.json veya collector.py / official.py / textutil.py değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill rss-integrity-checker
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
