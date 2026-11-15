---
name: token-budget-guardian
description: Uzun/otonom oturumlarda token ve kota tasarrufu kuralları; gereksiz yeniden okumayı, büyük çıktıları ve sonsuz deneme-yanılmayı keser. Gece vardiyası, Arena turu veya uzun refactor başlarken kullan.
---
# token-budget-guardian

## Kurallar
1. **Bir dosyayı bir kez oku.** Düzenledikten sonra tekrar okuma; yalnızca değiştirilecek fonksiyonu `sed -n '/def x/,/^def /p'` veya `grep -n` ile hedefle.
2. **Yalnızca değişen fonksiyonu düzenle.** Tüm dosyayı yeniden yazmak yalnızca dosyanın yarısından fazlası değişiyorsa.
3. **Büyük çıktıyı özetle.** `pytest -q | tail -3`, `ruff ... | head -30`, `mypy | tail -5`. Tam `-v` çıktısı yalnızca rapor için ve bir kez.
4. **Deneme sınırı: 2.** Aynı test/hata 2 düzeltme denemesinde geçmiyorsa dur; `MORNING_REPORT.md` → "İNSAN MÜDAHALESİ GEREKLİ" altına kaydet, bağımsız sonraki işe geç.
5. **Canlı LLM/API çağrısı yok.** Tüm doğrulama sahte (mock) servislerle; ağ `tests/conftest.py` ve simülatörde engelli.
6. **Alt ajan açma.** Roller (Arena dahil) tek bağlamda sırayla oynanır; aynı bağlamı tekrar okutmak yasak.
7. **Ara çıktılar kısa:** her adımda "ne değişti + test sonucu" tek satır (`NIGHT_PROGRESS.md`).
8. **Web araması yalnızca resmî doküman doğrulaması için**, konu başına en fazla 2 sorgu.

## Bütçe kontrol listesi (her büyük adım sonunda)
- [ ] Bu adımda aynı dosya 2'den fazla okundu mu?
- [ ] 200 satırdan uzun araç çıktısı üretildi mi? Üretildiyse bir sonraki adımda filtrele.
- [ ] Başarısız deneme sayısı ≤ 2 mi?
