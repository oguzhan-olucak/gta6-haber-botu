---
name: architect-verifier
description: bot/ modül sınırlarını, atomik JSON yazımını ve deterministik yayın puanlamasını denetler. Mimari değişiklik, yeni modül veya refactor sonrası kullan.
---
# architect-verifier

## Modül sınırları
| Modül | Tek sorumluluk | Yapmaması gereken |
|---|---|---|
| `config.py` | ayar/ortam doğrulama, secret maskeleme | ağ çağrısı |
| `storage.py` | atomik JSON, bozuk dosya yedeği, kilit | iş kuralı |
| `telegram_client.py` | tüm Telegram HTTP çağrıları | içerik kararı |
| `collector.py` | RSS/Atom, canonical URL, alan adı, SSRF doğrulama | LLM çağrısı |
| `processor.py` | kümeleme, puan, Gemini, çıktı doğrulama | Telegram çağrısı |
| `publisher.py` | şablon, idempotent yayın, özet/alarm | puanlama |
| `analyzer.py` | reaksiyon güncellemeleri, ölçüm, içgörü | yayın eşiği değiştirme |
| `textutil.py` | metin temizleme/kırpma/onarım | ağ, iş kuralı |
| `official.py` | Google News çözümü, HTML liste ayrıştırma | doğrulama kararı (collector verir) |
| `clustering.py` | benzerlik motoru | etiket/eşik kararı |
| `labels.py` | etiket sabitleri, Assessment | mantık |
| `gemini.py` | şema, istem, çıktı doğrulama, SDK | yayın |
| `main.py` | `RunContext` ile orkestrasyon | doğrudan HTTP |

## Kontroller
- `requests.Session.post` yalnızca `telegram_client.py`'de; `session.get` yalnızca `collector.py`'de.
- Tüm `data/*.json` yazımları `storage.write_json_atomic` / `write_if_changed` üzerinden (`grep -rn "open(.*'w'" bot/` boş).
- Yayın kararı `processor.assess` (Python) ile verilir; LLM çıktısındaki hiçbir alan etiket/eşik değiştirmez.
- `insights.json` yalnızca `prompt_hints.preferred_title_styles` üzerinden ve enum'a karşı doğrulanarak okunur.

## Ne zaman tetiklenir
Yeni modül eklendiğinde, modüller arası import veya HTTP çağrısı değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill architect-verifier
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
