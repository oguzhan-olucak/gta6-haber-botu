# Skill dizini

Proje skill'leri dört katmanda düzenlenir. Her skill'in kuralları `python tools/skill_audit.py` ile koda karşı çalıştırılır
(sonuç: `SKILL_AUDIT_REPORT.md`).

| Katman | Skill | Ne zaman |
|---|---|---|
| **Süreç** | `night-shift-supervisor`, `python-tdd-runner`, `token-budget-guardian`, `arena-adversarial-review` | her oturum / büyük değişiklik |
| **Bot çekirdeği** | `architect-verifier`, `atomic-json-recovery`, `cost-guard`, `gemini-schema-enforcer`, `telegram-api-guard` | bot/ modülleri |
| **Kaynak & doğrulama** | `rss-integrity-checker`, `rss-anti-poisoning`, `official-source-verifier`, `event-clustering-calibrator` | kaynak, etiket, kümeleme |
| **Güvenlik** | `security-auditor`, `static-site-guardian` | secret, XSS, CSP, feed şeması |
| **Ön yüz** | `vice-city-design-system`, `ui-ux-interaction-standards`, `webapp-testing-site` | docs/ sitesi |

Ön yüz değişikliği sırası: tasarım token'ları (`vice-city-design-system`) → etkileşim kuralları
(`ui-ux-interaction-standards`) → güvenlik (`static-site-guardian`) → uçtan uca sınama (`webapp-testing-site`).

Üçüncü taraf, doğrulanmamış skill eklenmez; yeni skill frontmatter + "Ne zaman tetiklenir" + "Otomatik doğrulama"
bölümleri ve `tools/skill_audit.py` içinde işlevsel denetleyiciyle gelir.
