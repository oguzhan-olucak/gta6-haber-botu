---
name: night-shift-supervisor
description: Gece vardiyası görev sırasını yönetir, her adımı NIGHT_PROGRESS.md'ye kaydeder, takılınca 3 denemede durur ve sabah için MORNING_REPORT.md hazırlar. Otonom/gece çalışması başlatıldığında kullan.
---
# night-shift-supervisor

## Sıra
1. Ortam kontrolü (Python, pytest, bağımlılıklar) → NIGHT_PROGRESS.md.
2. Gerçeklik denetimi (yalnızca salt-okunur web araması) → MORNING_REPORT.md bölüm 2.
3. Modül modül: yaz → `python -m pytest -q` → yerel `git commit` (ASLA `git push`) → NIGHT_PROGRESS.md'ye tek satır.
4. Güvenlik (`security-auditor`) ve maliyet (`cost-guard`) kontrolleri.
5. MORNING_REPORT.md: durum (HAZIR / KISMİ HAZIR / ENGEL VAR), test sayıları, açık riskler, "Sabah Senin Yapacakların".

## Kesin sınırlar
- Gerçek Telegram kanalına mesaj yok; gerçek API anahtarı okuma/yazma yok; ücretli servis yok; proje dışı dosya yok.
- Aynı hata 3 denemede çözülmezse: "İNSAN MÜDAHALESİ GEREKLİ" başlığıyla kaydet, bağımsız sonraki göreve geç.
- Paralel alt ajan açma; tek bağlamda sıralı çalış; yalnızca üzerinde çalışılan dosyayı oku.
