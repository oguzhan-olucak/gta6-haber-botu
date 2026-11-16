---
name: webapp-testing-site
description: docs/ sitesini headless Chrome ile 390/820/1440 genişlikte, gerçek (boş olabilir) ve örnek veriyle uçtan uca sınar; yatay taşma, boş durum ve gerçek-veri önceliğini doğrular. Site yayına alınmadan önce veya görsel değişiklik sonrası kullan.
---
# webapp-testing-site

## Yöntem
- `tools/site_check.py` `docs/` klasörünü 127.0.0.1 üzerinde geçici sunucuyla açar (dış ağ yok).
- Sayfa `?selftest=1` ile açıldığında `app.js` `<html data-selftest>` özniteliğine mod, haber/kart sayısı,
  manşet durumu, kaynak nabzı ve `overflowX` yazar; araç bunu `--dump-dom` ile okur.
- Matris: 3 genişlik × {gerçek, `?demo=1`}. Gerçek beslemede haber varsa `?demo=1` yine gerçek modda kalmalıdır.

## Komutlar
```bash
python tools/site_check.py                  # matris
python tools/site_check.py --shots shots/   # + ekran görüntüleri (gözle kontrol)
```
Ekran görüntülerine mutlaka bakılır: manşet okunur mu, kartlar hizalı mı, modallar ekrana sığıyor mu.

## Ne zaman tetiklenir
`docs/` altındaki HTML/CSS/JS veya `bot/site_exporter.py` çıktısı değiştiğinde; yayına almadan önce.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill webapp-testing-site
```
Chrome varsa matrisi çalıştırır; yoksa selftest kancasının ve aracın varlığını denetler.
