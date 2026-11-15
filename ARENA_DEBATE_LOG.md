# ARENA_DEBATE_LOG — Çekişmeli Denetim Turları

Protokol: `.claude/skills/arena-adversarial-review/SKILL.md`. Roller tek bağlamda sırayla oynandı (alt ajan açılmadı; `token-budget-guardian`).
Her bulgu: `dosya:satır` → önce FAIL eden test (`tests/test_arena.py`) → yama → tüm paket PASS.

Başlangıç durumu: 104 test PASS, `mypy bot` temiz, `ruff` temiz (commit `c30c5ef`).

---

## Tur 1

| # | Rol | Bulgu (`dosya:satır`) | Senaryo / etki | Test |
|---|---|---|---|---|
| 1.1 | Red Team | `bot/processor.py:219` (Assessment.items = tüm geçerli öğeler) | Reddit gönderisi bir IGN haberiyle aynı kümeye girince metni Gemini istemine ve "Kaynak" satırına giriyordu. Böylece "kuzenim Rockstar'da çalışıyor" türü bir iddia, TEK/ÇOKLU KAYNAK rozetli habere karışabiliyordu. | `test_r1_red_community_text_never_blends_into_media_post` |
| 1.2 | Red Team | `bot/processor.py:76` (`normalize_text` homoglif katlamıyor) | Kiril `І/о/е` ile yazılan "Іgnоre prеvious instructions" enjeksiyon dedektörünü atlatıyordu. | `test_r1_red_homoglyph_injection_is_detected` |
| 1.3 | FinOps/SRE | `bot/main.py:526` (`candidate_pool` için kayıt sınırı yok) | 48 saatte ~8.600 öğe × ~1 KB özet, state.json'u megabaytlarca şişirip her 20 dakikalık commit'le repoyu büyütür (Actions süresi ve klon boyutu). | `test_r1_sre_candidate_pool_is_bounded` |
| 1.4 | Editör | `bot/publisher.py:43,90` (kategori satırı) | Insider Gaming'in sızıntı haberi "SIZINTI İDDİASI · TOPLULUK" basılıyordu; okur yayın organı haberini Reddit sanıyor. "RESMÎ AÇIKLAMA · DUYURU" ise anlamca tekrar. | `test_r1_editor_media_leak_not_labelled_as_community` |

**FAIL kanıtı (yama öncesi):** `4 failed in 0.18s`

**Yamalar:**
- 1.1: `processor.assess`: etiketi belirleyen güven katmanı (`_LABEL_TIER`) dışındaki öğeler ayıklanıyor. İstem ve kaynak listesi yalnızca bu katmandan besleniyor.
- 1.2: `textutil.fold_confusables` (Kiril/Yunan → Latin) eklendi; `injection_suspect` önce bunu uyguluyor. Tam genişlikli karakterleri NFKD zaten katlıyor.
- 1.3: `retention_limits.candidate_pool_max_records = 400`; en yeni öğeler korunuyor.
- 1.4: Etiketle aynı anlamı taşıyan kategori satırı gizleniyor; `COMMUNITY_RUMOR` → "İddia".

**PASS kanıtı:** `108 passed` · `mypy`: temiz · `ruff`: temiz
