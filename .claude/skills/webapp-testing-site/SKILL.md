---
name: webapp-testing-site
description: docs/ sitesini headless Chrome ile 390/820/1440 genişlikte, gerçek (boş olabilir) ve örnek veriyle uçtan uca sınar; yatay taşma, boş durum ve gerçek-veri önceliğini doğrular. Site yayına alınmadan önce veya görsel değişiklik sonrası kullan.
---
# webapp-testing-site

## Yöntem
- `tools/site_check.py` `docs/` klasörünü 127.0.0.1 üzerinde geçici sunucuyla açar (dış ağ yok) ve **Playwright**
  ile gerçek görüntü alanında (390/820/1440) sınar. Chrome `--dump-dom` yalnızca yedektir: başsız Chrome pencereyi en az
  500 px açtığı için 390 px'i gerçekten sınayamaz.
- Etkileşim adımları: iğneye odak + Enter → bölge paneli + süzülmüş akış; × ile sıfırlama; `#telegram` ve `#yontem`
  çekmeceleri açılır ve ekrana sığar; JavaScript/konsol hatası sıfır olmalı.
- Sayfa `?selftest=1` ile açıldığında `app.js` `<html data-selftest>` özniteliğine mod, haber/kart sayısı,
  manşet durumu, kaynak nabzı ve `overflowX` yazar; araç bunu `--dump-dom` ile okur.
- Matris: 3 genişlik × {`?demo=0` (yalnız gerçek), varsayılan}. Gerçek akış boşken varsayılan açılış örnek bülten
  olmalı; gerçek akışta haber varsa varsayılan açılış gerçek modda kalmalıdır.

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
