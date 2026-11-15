---
name: arena-adversarial-review
description: Dört rollü (Red Team, FinOps/SRE, Oyun Medyası Editörü, Test & Kaos Hakemi) çekişmeli kod denetimi turlarını yönetir; her bulguyu önce başarısız teste, sonra yamaya çevirir ve ARENA_DEBATE_LOG.md'ye kaydeder. "Arena turu" veya çekişmeli denetim istendiğinde kullan.
---
# arena-adversarial-review

## Roller (tek bağlamda sırayla oynanır — alt ajan yok, bkz. token-budget-guardian)
| Rol | Arar |
|---|---|
| **Red Team** | RSS/HTML ile LLM'i kandırma, sahte RESMÎ AÇIKLAMA, token sızıntısı, JSON bozma/zehirleme, otomatik bağlantı/spam enjeksiyonu |
| **FinOps & SRE** | 0 TL'yi delen döngüler, kota/istek israfı, 60 gün kuralı, cron gecikmesi, sonsuz retry, iş süresi aşımı, repo şişmesi |
| **Oyun Medyası Editörü** | Clickbait, kesinlik dili, tekrar eden/anlamsız etiketler, yanıltıcı kategori/kaynak gösterimi, okunabilirlik |
| **Test & Kaos Hakemi** | Her bulguyu önce **FAIL eden** pytest'e çevirir, yamayı yapar, tüm paketi yeşile döndürür |

## Tur protokolü
- **A — Saldırı:** 3 denetçi rol toplam ≥3 bulgu; her biri `dosya:satır` + somut senaryo + etki. Övgü ve genel tavsiye yasak.
- **B — Test:** Hakem `tests/test_arena.py` içine `test_rN_*` testleri yazar; `pytest -q tests/test_arena.py -k rN` ile FAIL olduğunu kaydeder (çıktının son satırı log'a).
- **C — Yama:** en küçük değişiklik; `pytest -q` tamamı PASS + `mypy bot` + `ruff check`.
- **D — Kayıt:** `ARENA_DEBATE_LOG.md` (bulgu tablosu, FAIL→PASS kanıtı, karar) + `git commit -m "arena-tur-N: ..."` (push yok).

## Kurallar
- Bir bulgu reddedilecekse (yanlış alarm) hakem gerekçesini tek satırla yazar; sayıma girmez.
- Aynı yama 2 denemede yeşile dönmezse: geri al, "İNSAN MÜDAHALESİ GEREKLİ" olarak kaydet.
- Turlar arasında önceki turların testleri her zaman çalışır (regresyon kalkanı).

## Ne zaman tetiklenir
Büyük bir özellik tamamlandığında veya kullanıcı 'Arena turu' istediğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill arena-adversarial-review
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
