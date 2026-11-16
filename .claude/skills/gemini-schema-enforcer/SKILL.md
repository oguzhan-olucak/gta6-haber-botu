---
name: gemini-schema-enforcer
description: google-genai Structured Outputs kullanımı, untrusted_source_data izolasyonu, Pydantic doğrulaması ve bozuk JSON'da güvenli REJECTED davranışını denetler. processor.py veya prompt değiştiğinde kullan.
---
# gemini-schema-enforcer

- **Varsayılan çağrı (REST):** `GeminiRestGenerator` → `POST https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent`, kimlik **yalnızca** `x-goog-api-key` başlığında (AI Studio `AQ.` auth key'leri ve eski `AIza` anahtarları için aynı). `Authorization: Bearer` ve `?key=` yasak; gövdede `generationConfig.responseMimeType` + `responseJsonSchema`. Hata tanısında yalnızca büyük harfli `status`/`reason` kodları (ör. `UNAUTHENTICATED/ACCESS_TOKEN_TYPE_UNSUPPORTED`) loglanır.
- Yedek SDK çağrısı: `client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config={"system_instruction", "response_mime_type": "application/json", "response_json_schema": RESPONSE_JSON_SCHEMA})` (resmî Structured outputs sayfası, son güncelleme 2026-10-19: Python SDK `response_mime_type` + `response_json_schema`).
- Şemada yalnızca dokümanda desteklenen anahtar kelimeler: type, properties, required, enum, items, minItems, maxItems, description. Uzunluk sınırları Python'da (`content_limits`) uygulanır.
- Model adı koda gömülmez; değişince yalnızca `GEMINI_MODEL` Actions Variable güncellenir.
- Çıktı her zaman `bot/gemini.py::validate_generated` ile denetlenir; kontroller `CHECKS` demetinde sıralı ve bağımsızdır (yeni kural = yeni `check_*` fonksiyonu + test): JSON/şema → REJECTED; uydurma URL → REJECTED; kaynakta olmayan sayı/platform/ay, yasaklı kesinlik ifadesi, resmî olmayanı resmî sayma, `needs_review=true` → REVIEW_HELD (yayın yok).
- Prompt: kaynak kayıtları `<untrusted_source_data>` içinde JSON olarak; `<`/`>` → `‹`/`›` kaçırılır.
- Testler: `tests/test_processor.py`.

## Ne zaman tetiklenir
gemini.py, istem metni veya çıktı şeması değiştiğinde; model kimliği güncellendiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill gemini-schema-enforcer
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
