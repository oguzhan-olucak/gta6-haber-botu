---
name: rss-anti-poisoning
description: Kötü niyetli veya bozuk RSS/HTML içeriğine (prompt injection, homoglif, görünmez karakter, XML bombası, aşırı uzun alan, sahte resmî kaynak, topluluk metninin doğrulanmış habere karışması) karşı savunmaları denetler. Kaynak ekleme veya collector/processor değişikliğinde kullan.
---
# rss-anti-poisoning

## Savunma katmanları
1. **Ayrıştırma:** defusedxml (`forbid_dtd=True`), 2 MB yanıt sınırı, bozuk UTF-8 onarımı.
2. **Temizlik:** `textutil.strip_html` → HTML, kontrol/biçim karakterleri (ZWSP, bidi), mojibake; `truncate` ile sınır.
3. **Alan adı:** öğe bağlantısı kaynağın `allowed_domains` listesinde (nokta sınırı); resmî öğe için doğrulanmış nihai URL.
4. **Enjeksiyon şüphelisi:** `processor.injection_suspect` (homoglif katlama dahil) → öğe kümeden ayıklanır; temiz kaynaklar yayınlanmaya devam eder (DoS yok).
5. **Katman izolasyonu:** etiketin geldiği güven katmanı dışındaki öğeler (ör. Reddit) doğrulanmış habere ne istemde ne kaynak listesinde yer alır.
6. **İstem:** veri `<untrusted_source_data>` içinde, `< >` kaçırılmış.
7. **Çıktı:** `gemini.CHECKS` — URL/mention/HTML/emoji/kesinlik/uydurma ayrıntı.

## Saldırı yükü kütüphanesi
`tests/test_injection.py::PAYLOADS` ve `tests/test_arena.py` — yeni bir saldırı türü bulunduğunda önce buraya başarısız test olarak eklenir.

## Ne zaman tetiklenir
Yeni kaynak eklendiğinde; processor/gemini doğrulama kuralları değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill rss-anti-poisoning
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
