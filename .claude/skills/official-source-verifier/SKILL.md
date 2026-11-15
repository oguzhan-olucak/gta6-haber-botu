---
name: official-source-verifier
description: RESMÎ AÇIKLAMA etiketinin yalnızca doğrulanmış Rockstar/Take-Two URL'lerine verildiğini denetler (Google News çözümü, HTML liste, yönlendirme zinciri, canonical). Resmî kaynak eklerken veya etiket mantığı değişince kullan.
---
# official-source-verifier

Koşulların üçü birden: `trust_class == "OFFICIAL"` · `url_verified is True` · `domain_allowed(url, ("rockstargames.com", "take2games.com"))`.

- Google News: önce çevrimdışı çözüm (eski biçim), yoksa SSRF korumalı yönlendirme takibi; ara adım `news.google.com`, nihai adres resmî alan adı değilse öğe atılır.
- HTML liste: `link_pattern` yol üzerinde; mutlak bağlantı başka alan adına gidiyorsa atılır.
- Her yönlendirme adımı ve `<link rel=canonical>` izinli alan adında olmalı; özel/iç IP reddedilir.
- Aynı bağlantı her çalışmada yeniden doğrulanmaz (görülen ham bağlantılar `seen_items`'ta); hedef sitelere gereksiz istek yok.
- Testler: `tests/test_resilience.py` (Google News/HTML), `tests/test_injection.py::test_official_trust_class_without_verified_url_is_not_official`.

## Ne zaman tetiklenir
Resmî kaynak eklendiğinde/değiştiğinde; etiket mantığı değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill official-source-verifier
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
