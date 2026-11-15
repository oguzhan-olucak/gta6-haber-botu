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

---

## Tur 2

| # | Rol | Bulgu (`dosya:satır`) | Senaryo / etki | Test |
|---|---|---|---|---|
| 2.1 | Red Team | `bot/gemini.py:86` (`_BANNED_ALWAYS` yalnızca `https?://` arıyor) | Telegram `t.me/x`, `www.site.ru`, `site.com/x` ve `@kanal` metinlerini otomatik bağlantıya çevirir. Kaynak metne gömülü bir spam/oltalama bağlantısı modelin özetinden kanala sızabiliyordu. | `test_r2_red_bare_links_and_mentions_rejected` |
| 2.2 | FinOps/SRE | `bot/telegram_client.py:103` (`retry_after` her değerde 60 sn'ye kırpılıp yeniden deneniyor) | 429 + `retry_after=3600` geldiğinde 3 kez 60 sn uyuyup boşuna yeniden deniyordu: her çalışmada ~3 dakika Actions süresi harcanıyor ve flood kısıtı uzuyordu. | `test_r2_sre_huge_retry_after_is_not_slept_through` |
| 2.3 | Editör | `bot/gemini.py:137` (`check_banned` emoji denetlemiyor) | "Tek rozet" kuralı yalnızca istemde yazıyordu. Model 🔥😱🚨 eklerse yayınlanıyordu. | `test_r2_editor_emoji_in_generated_text_rejected` |
| 2.4 | Editör | `bot/gemini.py:144` | Doğrulanmamış haberde soru başlığı ("…PC'ye mi geliyor?") klasik clickbait (Betteridge yasası). | `test_r2_editor_question_headline_on_unverified_claim_held` |

**FAIL kanıtı:** `4 failed, 4 deselected in 0.14s`

**Yamalar:** `_LINKISH` ve `_EMOJI` desenleri → REJECTED. TEK KAYNAK ve İDDİA etiketlerinde `?` ile biten başlık → REVIEW_HELD. `retry_after > 60` → bu çalışmada vazgeç (`MAX_RETRY_AFTER_SECONDS`).

**PASS kanıtı:** `112 passed` · `mypy`: temiz · `ruff`: temiz · simülatörün 5 senaryosu üretimde

---

## Tur 3

| # | Rol | Bulgu (`dosya:satır`) | Senaryo / etki | Test |
|---|---|---|---|---|
| 3.1 | Red Team | `bot/main.py:194` (state yalnızca kök tipine göre denetleniyordu) | Geçerli JSON ama şekli bozuk bir state (`{"seen_items": [], "candidate_pool": "x"}`) AttributeError ile çöküşe yol açıyordu. Bot her 20 dakikada çıkış 3 veriyor, yani fiilen ölüyordu. | `test_r3_red_schema_poisoned_state_does_not_crash` |
| 3.2 | Red Team | `bot/main.py:199` (`posts` yalnızca liste mi diye bakılıyordu) | `{"posts": [123, "x"]}` gibi zehirli bir geçmiş `p.get` çağrılarında çöküyordu. Kurtarma yolu da hiç tetiklenmiyordu. | `test_r3_red_schema_poisoned_history_recovers_from_last_good` |
| 3.3 | FinOps/SRE | `bot/collector.py:444` (çalışma süresi sınırı yok) | 11 kaynak × (15 sn × 4 deneme + backoff) + resmî URL doğrulamaları 15 dakikalık iş sınırını aşabiliyordu. İş ortasında öldürülünce o turun yayın ve ölçüm adımları kayboluyordu. | `test_r3_sre_collection_respects_run_deadline` |
| 3.4 | Editör | `bot/labels.py:34-35` (jenerik doğrulama notu) | Take-Two IR haberinde bile "Rockstar Games / Take-Two resmî kanalında" yazıyordu. ÇOKLU KAYNAK'ta gerçek sayı bilindiği halde "en az iki" deniyordu. | `test_r3_editor_verification_note_is_specific` |

**FAIL kanıtı:** `4 failed, 8 deselected in 0.14s`

**Yamalar:**
- 3.1/3.2: `storage.read_json(..., validator=)` ve `validate_state_shape` / `validate_history_shape` eklendi. Şekil bozukluğu artık "bozuk dosya" sayılıyor: önce `.lastgood` kurtarma, o da yoksa güvenli mod (çıkış 2, çöküş yok).
- 3.3: `run_deadline_seconds = 600`. Süre dolunca kalan kaynaklar `skipped: "deadline"` olarak raporlanıyor, Gemini döngüsü de duruyor.
- 3.4: `publisher.verification_note`: resmî kaynağın adı veya bağımsız köken sayısı yazılıyor.

**Süreç notu (hakem):** İlk yama denemesinde `ruff --fix`, önceki turda kullanılmayan test importlarını sildiği için 19 test kırmızıya döndü. Importlar geri eklendi, 2. denemede yeşile döndü. `token-budget-guardian` kuralı (en fazla 2 deneme) aşılmadı.

**PASS kanıtı:** `116 passed` · `mypy`: temiz · `ruff`: temiz
