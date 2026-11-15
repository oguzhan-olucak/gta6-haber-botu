---
name: event-clustering-calibrator
description: bot/clustering.py benzerlik ağırlıklarını ve cluster_similarity_threshold eşiğini etiketli başlık çiftleriyle kalibre eder; yanlış birleştirme (sahte ÇOKLU KAYNAK) ve kaçırılan birleştirme oranını ölçer. Eşik veya ağırlık değiştirilmeden önce kullan.
---
# event-clustering-calibrator

1. Etiketli çiftler: `tests/test_clustering.py::SAME_EVENT` (birleşmeli) ve `DIFFERENT_EVENT` (birleşmemeli). Yeni gerçek dünya örneği bulunduğunda buraya ekle.
2. Ölçüm: her çift için `SimilarityEngine(...).score(0, 1)`; en düşük pozitif ve en yüksek negatif puanı raporla.
3. Eşik, iki grubun arasındaki boşluğun ortasına yakın seçilir; **öncelik yanlış birleştirmeyi sıfırda tutmak** (sahte ÇOKLU KAYNAK, eksik birleştirmeden daha zararlıdır).
4. Sert engeller (çelişen sayı, varlık çatışması, 72 saat) puandan bağımsızdır; değiştirirsen negatif testleri yeniden çalıştır.
5. Kayıt: kalibrasyon sonucu ve tarih `NIGHT_PROGRESS.md`'ye.

## Ne zaman tetiklenir
Kümeleme eşiği/ağırlıkları değiştirilmeden önce; yanlış birleşme raporlandığında.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill event-clustering-calibrator
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
