# MORNING_REPORT — Gece Vardiyası Sonuç Raporu

**Tarih:** 16 Kasım 2026, Pazartesi · Gece vardiyası 00:51–02:30 TSİ (UTC+3)

---

## 1. Yönetici Özeti

| | |
|---|---|
| **Genel durum** | **KISMİ HAZIR.** Kod, testler, workflow ve dokümanlar tamam. Canlıya çıkmadan önce senin yapman gereken 7 adım ve doğrulanması gereken 2 dış varsayım var (bkz. bölüm 5). |
| **Dosyalar** | Bölüm 9'daki yapının tamamı (24 dosya) + `tests/conftest.py` + 8 skill + önizleme aracı + raporlar |
| **Testler** | **49 / 49 geçti** (14 kabul testi dahil). Komut: `python -m pytest -v`. Gerçek ağ çağrısı yok. |
| **Güvenlik taraması** | Gerçek formatlı secret yok · `eval/exec/shell=True/verify=False` yok · loglar maskeleniyor |
| **Yerel git** | 7 commit, `main` dalı. **Push yapılmadı.** |

**Kritik zaman notu:** GTA VI'ın çıkışına 3 gün var (19 Kasım 2026). Resmî Rockstar RSS beslemesi doğrulanamadığı için bot şu an **RESMÎ AÇIKLAMA** etiketini tetikleyemez. Resmî haberler yalnızca bağımsız medya kaynaklarından **ÇOKLU KAYNAK** olarak gelir (bkz. 5.1).

---

## 2. Gerçeklik Denetimi Bulguları (kontrol tarihi: 16 Kasım 2026)

| Konu | Bulgu | Sonuç |
|---|---|---|
| **GTA VI çıkışı** | Rockstar, 6 Kasım 2025'te X hesabında 19 Kasım 2026 (Perşembe) tarihini duyurdu. Platformlar: PS5 ve Xbox Series X\|S. PC duyurulmadı. 15 Ekim 2026 fragmanı tarihi yeniden teyit etti. Dijital ön yükleme 12 Kasım'da başladı. [TechRadar](https://www.techradar.com/gaming/grand-theft-auto-6-delayed-again-but-itll-still-ship-in-2026), [TweakTown](https://www.tweaktown.com/news/108727/rockstar-officially-delays-gta-6-again-will-now-release-on-november-19-2026/index.html), [GTABoom](https://www.gtaboom.com/gta-6-release-date-and-delay-history-9f6b) | **Doğrulandı** (ikincil kaynaklar üzerinden; Rockstar Newswire bu oturumdan doğrudan açılamadı). Bilgi yalnızca rapordadır, kodda sabit değildir. |
| **Gemini modeli** | `gemini-3.5-flash` resmî model sayfasında **Stable** olarak listeleniyor ([ai.google.dev](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)). Structured outputs sayfası (son güncelleme 2026-10-19) örneklerde daha yeni kimlikler (`gemini-3.8-flash`) kullanıyor, yani model listesi hızla değişiyor. | **Koşula bağlı.** Model koda gömülmedi; `GEMINI_MODEL` Variable olarak sabah AI Studio'da seçilecek. |
| **Gemini Structured Outputs** | Python SDK: `response_mime_type="application/json"` + `response_json_schema` ([structured outputs](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en)). REST biçimi `responseFormat.text.schema` olarak değişmiş. Bu nedenle REST yerine resmî `google-genai` SDK'sı kullanıldı. | **Doğrulandı** (doküman). SDK yerelde kurulamadığı için **canlı denenmedi**; sahte istemciyle test edildi. |
| **Gemini ücretsiz katman** | Flash/Flash-Lite modelleri ücretsiz katmanda. Limitler projeye ve modele göre AI Studio'da gösteriliyor, sabit sayı yok. Ücretsiz katmanda gönderilen veri Google ürünlerini iyileştirmek için kullanılabilir ([pricing](https://ai.google.dev/pricing?hl=fi)). | **Koşula bağlı.** Limitler senin projende AI Studio → Rate limits sayfasından görülmeli. |
| **Gemini — Türkiye erişimi** | Resmî "Available regions" sayfası açılabildi ama liste kesik geldi; Türkiye satırı görülemedi. | **Doğrulanamadı.** AI Studio'ya Türkiye'den giriş yapıp anahtar oluşturabiliyorsan erişim var demektir. |
| **Telegram Bot API** | Sürüm 10.4 (9 Kasım 2026). Message nesnesinde görüntülenme/iletilme sayısı alanı yok ve kanal gönderisi istatistiği veren metot yok. `message_reaction_count` için bot yönetici olmalı ve `allowed_updates` içinde açıkça istenmeli. Güncellemeler gruplanır, birkaç dakika gecikebilir. `getUpdates` webhook varken çalışmaz. ([core.telegram.org/bots/api](https://core.telegram.org/bots/api)) | **Doğrulandı.** views/forwards = `"unavailable"`. |
| **Telegram MTProto** | `stats.getBroadcastStats` / `messages.getMessagesViews` kullanıcı hesabı oturumu gerektirir. MVP'de kullanılmadı. | Sonraki aşama araştırması |
| **GitHub Actions** | Public repoda standart runner ücretsiz ([docs.github.com](https://docs.github.com/en/billing/concepts/product-billing/github-actions)). Schedule en iyi çaba ile çalışır: en kısa aralık 5 dakika, yalnızca varsayılan dalda, 60 gün etkinlik yoksa devre dışı kalır. | **Doğrulandı** |
| **RSS beslemeleri** | Bu oturumda shell'den ağ erişimi kapalıydı; besleme adresleri canlı test edilemedi (`rss_verified: false`). Rockstar ve Take-Two için resmî RSS adresi bulunamadı. | **Doğrulanamadı.** İlk çalışmanın `source_status` çıktısıyla kontrol edilecek. |

**0 TL koşulları:** Repo public olmalı, Gemini projesinde billing kapalı olmalı ve yalnızca ücretsiz katmandaki model kullanılmalı. Kod hiçbir koşulda başka/ücretli modele geçmez; 429 durumunda Gemini çağrıları bekletilir.

---

## 3. Tamamlanan Dosyalar ve Mimari Kararlar

| Dosya | Durum |
|---|---|
| `bot/config.py`, `bot/storage.py`, `bot/__init__.py` | ✅ Pydantic ayar doğrulama, atomik JSON, bozuk dosya yedeği, secret maskeleme |
| `bot/telegram_client.py` | ✅ Tek HTTP noktası. `sendMessage` okuma zaman aşımında yeniden gönderilmez. 429 durumunda `retry_after` uygulanır. |
| `bot/collector.py` | ✅ defusedxml, canonical URL, alan adı nokta sınırı, atıf zinciri, SSRF korumalı doğrulama |
| `bot/processor.py` | ✅ Kümeleme, `source_strength` / `editorial_priority`, Gemini SDK, 9 katmanlı çıktı doğrulama |
| `bot/publisher.py` | ✅ Şablon, SENDING→PUBLISHED/UNCERTAIN/FAILED idempotency, özet, alarm |
| `bot/analyzer.py` | ✅ Reaksiyon güncellemeleri, ölçüm durumu, n/medyan, erken sinyal |
| `bot/main.py` | ✅ Orkestrasyon, güvenli mod, JSON çalışma özeti |
| `config/*.json`, `data/*.json` | ✅ |
| `.github/workflows/run.yml` | ✅ Önce testler (secret yok), sonra bot, sonra yalnızca `data/*.json` commit |
| `README.md` | ✅ Mermaid diyagram, kurulum, 60 gün kuralı, kill switch |
| `.claude/skills/*` (8 adet) | ✅ Frontmatter doğrulandı, gizli shell komutu yok |
| `docs/message_preview.html` | ✅ Karanlık mod, Vice City gün batımı önizlemesi (`tools/render_preview.py` gerçek şablon fonksiyonunu kullanır) |

Brifte olmayan ama bilinçli olarak alınan kararlar:
- **Cron `7,27,47 * * * *`:** Yine 20 dakikada bir çalışır ama saat başı yoğunluğuna denk gelmez.
- **Aday havuzu (`state.candidate_pool`):** Tek kaynaklı bir haber bekletilir. İkinci bağımsız kaynak gelirse ÇOKLU KAYNAK olarak yeniden değerlendirilir.
- **Gemini yalnızca aday haberlerde çağrılır:** HOLD, tekrar veya red durumunda çağrı yapılmaz, böylece kota korunur.
- **Aynı yayın grubu tek köken sayılır:** GamesRadar+ ve PC Gamer ikisi de Future plc'ye ait olduğu için `origin_group: future_plc`.
- **Mesaj tasarımı:** Gönderi başına tek renk kodlu rozet (🟩🟦🟨🟥🟧), etiket ve kategori satırı, kalın başlık, 2–3 cümlelik özet, "Kaynak:" ve "Doğrulama:" satırları, italik imza. Başka emoji kullanılmadı. Önizleme: `docs/message_preview.html`.

---

## 4. Test ve Güvenlik Denetimi Sonuçları

```
$ python -m pytest -v
collected 49 items
tests/test_analyzer.py ......      (6)
tests/test_collector.py ...........(11)
tests/test_processor.py ...........(11)
tests/test_publisher.py ...............(15)
tests/test_storage.py ......       (6)
============================== 49 passed in 0.27s ==============================
```

| # | Kabul testi | Test |
|---|---|---|
| 1 | Aynı öğe bir kez işlenir | `test_publisher::test_same_item_twice_processed_once` |
| 2 | Bozuk RSS diğerlerini durdurmaz | `test_collector::test_broken_feed_does_not_stop_other_sources` |
| 3 | URL'siz içerik yayınlanmaz | `test_processor::test_no_source_url_is_rejected`, `test_publisher::test_publish_post_rejects_missing_source_url` |
| 4 | Reddit/tek kaynak RESMÎ olamaz | `test_processor::test_reddit_and_single_source_never_official` |
| 5 | Bozuk JSON çökertmez | `test_processor::test_broken_model_json_is_rejected_without_crash`, `test_publisher::test_broken_model_json_end_to_end` |
| 6 | Uydurma bilgi/kesinlik engellenir | `test_processor::test_hallucinated_details_and_certainty_words_are_blocked` |
| 7 | Günlük limit aşılmaz | `test_publisher::test_daily_post_limit_not_exceeded` |
| 8 | paused → yayın ve Gemini yok | `test_publisher::test_paused_means_no_publish_and_no_gemini` |
| 9 | Timeout sonrası tekrar yayın yok | `test_publisher::test_telegram_timeout_does_not_cause_duplicate_post` |
| 10 | Reaksiyon doğru message_id'ye | `test_analyzer::test_reaction_count_update_attaches_to_correct_message` |
| 11 | views/forwards uydurulmaz | `test_analyzer::test_views_and_forwards_stay_unavailable` |
| 12 | Bozuk insights → nötr | `test_processor::test_corrupt_insights_falls_back_to_neutral`, `test_publisher::test_corrupt_insights_end_to_end` |
| 13 | Özet bir pencerede tek | `test_publisher::test_digest_not_sent_twice_in_same_window` |
| 14 | Secret'lar loglanmaz | `test_publisher::test_secrets_never_logged` |

**Testlerin gerçekten bir şey yakaladığının kontrolü:** Bilerek 5 hata eklendi: timeout→FAILED, kill switch devre dışı, log maskeleme kapalı, ilgi filtresi kapalı ve kesinlik kontrolü kapalı. Her birinde ilgili test başarısız oldu, yani testler bu hataları yakalıyor.

**security-auditor:** Gerçek formatlı token/anahtar yok · `eval/exec/pickle/shell=True/verify=False` yok · secret'lar yalnızca `load_secrets`'ta okunuyor · XML yalnızca defusedxml ile · workflow'da `pull_request` tetikleyicisi yok, secret'lar yalnızca bot adımında.
**cost-guard:** Çalışma başına en fazla 4 Gemini çağrısı · 429 durumunda 60 dakika bekleme · yedek/ücretli model kodu yok · standart runner.
**Slash komutları hakkında:** `/doctor`, `/skill-doctor`, `/code-review`, `/verify` bu oturumda bulunmuyordu. Eşdeğer kontroller elle yapıldı: ortam kontrolü, frontmatter doğrulama betiği, grep tabanlı güvenlik taraması, Bölüm 15 kalite kapısı (aşağıda).

**Kalite kapısı (Bölüm 15):** 11 maddenin 11'i karşılandı. Tek açık nokta canlı ortam: SDK ve RSS adresleri canlı denenmedi; bu durum aşağıda risk olarak işaretli.

---

## 5. Çözülemeyen Sorunlar / Riskler

1. **Resmî kaynak beslemesi yok (ÖNEMLİ).** Rockstar Newswire ve Take-Two için doğrulanmış RSS adresi bulunamadı; ikisi de `enabled: false`. Bu yüzden RESMÎ AÇIKLAMA etiketi şimdilik tetiklenmez. Çıkış haftasındaki resmî haberler, ancak iki bağımsız medya kuruluşu aktarırsa ÇOKLU KAYNAK olarak yayınlanır. Doğrulanmış bir resmî besleme bulursan `config/sources.json`'da `feed_url` alanını doldurup `enabled: true` yapman yeterli.
2. **RSS adresleri canlı denenmedi.** IGN beslemesi feedburner üzerinden geliyor; bağlantılar `feedproxy` alan adına çıkarsa bu öğeler alan adı kontrolünde elenir. Reddit botlara 403/429 dönebilir. İlk çalışmanın özetinde `source_status` alanını kontrol et.
3. **`google-genai` SDK canlı denenmedi.** Bu oturumda paket kurulumu kapalıydı. Kod resmî dokümandaki parametre adlarını kullanıyor ve sahte istemciyle test edildi. İlk `workflow_dispatch` çalışmasında `gemini_errors` 0 olmalı.
4. **Sabit kurallı doğrulama aşırı temkinli olabilir.** Kaynakta olmayan herhangi bir sayı veya ay adı gönderiyi incelemeye alır (REVIEW_HELD). Bu yanlış haber riskini düşürür ama bazı geçerli haberleri de tutabilir. Özetteki "İncelemeye takılan" sayısını ilk hafta izle.
5. **Her çalışma `data/state.json` commit'i üretir** (son çalışma zamanı ve kaynak durumu). Bu, repoyu 60 gün kuralına karşı etkin tutar ama günde yaklaşık 72 küçük commit demektir.
6. **"Belirsiz gönderim" (UNCERTAIN):** Telegram zaman aşımı olursa haber bir daha denenmez. Bu durumda haber hiç yayınlanmamış olabilir; özette sayısı görünür.

3 denemede çözülemeyen hata olmadı: **İNSAN MÜDAHALESİ GEREKLİ** başlığı altında kayıt yok.

---

## 6. Sabah Senin Yapacakların

1. **Klasörü GitHub'a yükle.** "Haber Sitesi" klasöründeki `gta6-autonomous-telegram` klasörünün içinde terminal aç:
   ```bash
   git clone gta6-autonomous-telegram.bundle repo && cd repo   # gece atılan 7 commit'lik geçmişle
   ```
   GitHub'da yeni bir **public** repo oluştur (README eklemeden), sonra:
   ```bash
   git remote add origin https://github.com/<kullanıcı-adın>/<repo-adı>.git
   git push -u origin main
   ```
   Git geçmişi gerekmiyorsa klasördeki dosyaları doğrudan da yükleyebilirsin.
2. **BotFather:** Telegram'da @BotFather → `/newbot` → bot adını ver. Token'ı yalnızca 4. adımda GitHub Secrets'a yapıştır; sohbete, dosyaya veya koda yazma.
3. **Kanal:** Herkese açık kanalını oluştur. Botu **yönetici** olarak ekle ve "Mesaj gönderme" iznini ver (reaksiyon ölçümü için yöneticilik şart). İstersen özet ve uyarılar için ayrı bir özel grup kur, botu oraya da ekle.
4. **Gemini:** [Google AI Studio](https://aistudio.google.com)'da API anahtarı oluştur. **Billing'i açma.** Rate limits sayfasında ücretsiz katmanda olan **stable** bir Flash modelinin kimliğini not al (16 Kasım itibarıyla `gemini-3.5-flash` stable olarak listeleniyordu; yine de güncel listeyi kontrol et).
5. **GitHub → Settings → Secrets and variables → Actions:**
   - **Secrets:** `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (`@kanaladı` veya `-100…` ile başlayan sayısal ID)
   - **Variables:** `GEMINI_MODEL` (4. adımdaki kimlik), isteğe bağlı `ADMIN_CHAT_ID`
6. **İlk çalıştırma:** Actions → `gta6-bot-run` → **Run workflow**. Log'un sonundaki JSON özette şunlara bak:
   - `sources_ok` ≥ 4 olmalı. Başarısız kaynaklar için `data/state.json` → `source_status` alanını kontrol et ve gerekirse `config/sources.json`'da `enabled: false` yap.
   - `gemini_errors` 0 olmalı. Hata varsa `GEMINI_MODEL` değerini kontrol et.
   - `error_classes` içinde `AUTH_PERMISSION` olmamalı.
7. **Kanal görüntüsü:** İlk gönderiyi kanalda kontrol et. Görünüm `docs/message_preview.html` ile aynı düzende olmalı. İstersen botu durdurmak için `config/settings.json` → `"paused": true` yapıp commit et.

---

## 7. İlk 7 Gün Operasyon Planı

| Gün | Kontrol |
|---|---|
| **Her gün (09:00 ve 21:00 TSİ civarı)** | Yönetici özetinde 24 saatlik yayın sayısı, "İncelemeye takılan" ve "Belirsiz gönderim" sayıları ve hata sınıfları |
| **1. gün** | `source_status`: çalışmayan beslemeleri kapat. Kanaldaki ilk 3–5 gönderiyi kaynaklarıyla elle karşılaştır. |
| **2–3. gün (çıkış öncesi)** | Haber yoğunluğu artacak. `max_daily_posts: 8` yeterli mi değerlendir. Yanlış etiketlenen haber görürsen hemen `paused: true` yap. |
| **19 Kasım (çıkış günü)** | En yoğun gün. Gemini 429 alırsa bot bekler; özette "Gemini kotası soğuma süresinde" notu görünür. Bu bir hata değildir. |
| **5–7. gün** | Reaksiyon akışı: `data/history.json` içindeki gönderilerde `reaction_snapshots` doluyor mu? Doluyorsa `state.reaction_pipeline_verified = true` olmalı. Analiz, her grupta 5 gönderi birikene kadar "YETERSİZ VERİ" der; bu beklenen davranış. |

**Bot kendi başına yapar:** toplama, tekrar eleme, etiketleme, özetleme, yayın, reaksiyon ölçümü, günde iki özet, uyarı tekilleştirme.

**Senin müdahalen gerekir:** 401/403 uyarıları (token veya yetki), "güvenli mod" uyarısı (bozuk `history.json`'u yedekten geri yükleme), Gemini model kimliğinin kullanımdan kalkması, bir kaynağın kalıcı olarak bozulması, 60 günlük hareketsizlik uyarısı.

**Yanlış haber riskini azaltan kontrol noktaları:** Etiketi Python belirler. Resmî etiket için resmî alan adı şarttır. Bağımsız köken sayılırken kopya haberler ayıklanır. Kaynakta olmayan sayı, platform veya ay içeren özet engellenir. Kesinlik dili yalnızca resmî kaynakta kullanılabilir. İddia türü içerik varsayılan olarak kapalıdır.
