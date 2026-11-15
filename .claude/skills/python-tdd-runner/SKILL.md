---
name: python-tdd-runner
description: Her kod değişikliğinden sonra pytest çalıştırır, 14 kabul testinin tamamının geçtiğini doğrular ve eksik kapsamı kapatır. Kod değiştiğinde veya "testleri çalıştır" denildiğinde kullan.
---
# python-tdd-runner

1. `python -m pytest -q` (ayrıntı gerekirse `-v`). Sonucu olduğu gibi kaydet; çalıştırılmamış testi "geçti" diye raporlama.
2. 14 kabul testi eşlemesi:
   1 `test_publisher::test_same_item_twice_processed_once` · 2 `test_collector::test_broken_feed_does_not_stop_other_sources`
   3 `test_processor::test_no_source_url_is_rejected` + `test_publisher::test_publish_post_rejects_missing_source_url`
   4 `test_processor::test_reddit_and_single_source_never_official` · 5 `test_processor::test_broken_model_json_is_rejected_without_crash` + `test_publisher::test_broken_model_json_end_to_end`
   6 `test_processor::test_hallucinated_details_and_certainty_words_are_blocked` · 7 `test_publisher::test_daily_post_limit_not_exceeded`
   8 `test_publisher::test_paused_means_no_publish_and_no_gemini` · 9 `test_publisher::test_telegram_timeout_does_not_cause_duplicate_post`
   10 `test_analyzer::test_reaction_count_update_attaches_to_correct_message` · 11 `test_analyzer::test_views_and_forwards_stay_unavailable`
   12 `test_processor::test_corrupt_insights_falls_back_to_neutral` + `test_publisher::test_corrupt_insights_end_to_end`
   13 `test_publisher::test_digest_not_sent_twice_in_same_window` · 14 `test_publisher::test_secrets_never_logged`
   Faz 2+: `test_clustering.py` (kümeleme kalibrasyonu), `test_injection.py` (saldırı yükleri),
   `test_resilience.py` (UTF-8, kırpma, kurtarma, TRT limiti, resmî kaynak), `test_simulator.py`, `test_arena.py` (Arena regresyonları).
   Ayrıca `mypy bot` ve `ruff check bot tests tools` temiz olmalı.
3. Aynı hata 3 denemede çözülmezse dur, `MORNING_REPORT.md` içinde "İNSAN MÜDAHALESİ GEREKLİ" altına yaz.
4. Testlerde yalnızca `DUMMY_TEST_TOKEN_DO_NOT_USE` gibi sahte sabitler; gerçek ağ `conftest.py` tarafından engellenir.

## Ne zaman tetiklenir
Her kod değişikliğinden sonra; commit öncesi.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill python-tdd-runner
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
