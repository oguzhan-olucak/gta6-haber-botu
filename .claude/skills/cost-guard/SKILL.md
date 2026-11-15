---
name: cost-guard
description: Gemini, RSS ve Telegram çağrılarının ücretsiz katmanda kaldığını, limitlerin ve backoff'un doğru çalıştığını, ücretli modele otomatik geçiş olmadığını doğrular. Maliyet/kota kontrolü istendiğinde veya settings.json limitleri değiştiğinde kullan.
---
# cost-guard

## Doğrulanacaklar
- `settings.json`: `max_gemini_calls_per_run` (öneri ≤ 4), `max_daily_posts`, `max_rss_items_per_run`, `http_max_retries` (≤ 6) makul.
- Gemini yalnızca CANDIDATE kararından SONRA çağrılır (HOLD/REJECT/duplicate için çağrı yok) — `bot/main.py::_content_pipeline`.
- 429 → `gemini_quota_blocked_until` soğuma süresi; aynı çalışmada başka çağrı yok; model değiştirme/yedek model yok (`GeminiGenerator` yalnızca `GEMINI_MODEL`).
- 401/403/404 → alarm + soğuma; ücretli katmana veya başka modele geçiş kodu bulunmamalı: `grep -rn "fallback\|paid" bot/` yalnızca yorum satırı döndürmeli.
- Exponential backoff + jitter: `bot/__init__.py::backoff_delay`; sonsuz döngü yok (deneme sayısı sınırlı).
- GitHub Actions: yalnızca standart `ubuntu-latest` runner (public repoda ücretsiz); larger runner kullanılmaz.
- Testlerde gerçek API çağrısı yok (`tests/conftest.py` ağ erişimini engeller).

İlgili testler: `test_gemini_quota_stops_calls_and_never_switches_model`, `test_paused_means_no_publish_and_no_gemini`, `test_daily_post_limit_not_exceeded`.
