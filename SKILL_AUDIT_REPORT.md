# SKILL_AUDIT_REPORT — Skill Ekosistemi Denetimi

Üretim: `python tools/skill_audit.py` · 2026-11-16 06:59 UTC · **18/18 skill tüm denetimlerden geçti**

Her skill iki katmanda denetlenir: (1) **yapısal** — frontmatter, gövde dolu mu, tetiklenme ve otomatik doğrulama bölümleri, gizli kabuk komutu yok; (2) **işlevsel** — skill'in koyduğu kurallar koda, ayarlara ve testlere karşı gerçekten çalıştırılır.

## Özet

| Skill | Ne işe yarar | Ne zaman tetiklenir | Denetim | Durum |
|---|---|---|---|---|
| `architect-verifier` | bot/ modül sınırlarını, atomik JSON yazımını ve deterministik yayın puanlamasını denetler | Yeni modül eklendiğinde, modüller arası import veya HTTP çağrısı değiştiğinde. | 12/12 | ✅ DOĞRULANDI |
| `arena-adversarial-review` | Dört rollü (Red Team, FinOps/SRE, Oyun Medyası Editörü, Test & Kaos Hakemi) çekişmeli kod denetimi turlarını yönetir; her bulguyu önce başarısız teste, sonra yamaya çevirir ve ARENA_DEBATE_LOG.md'ye kaydeder | Büyük bir özellik tamamlandığında veya kullanıcı 'Arena turu' istediğinde. | 12/12 | ✅ DOĞRULANDI |
| `atomic-json-recovery` | data/*.json dosyalarının atomik yazımı, bozulma tespiti, .lastgood otomatik kurtarma ve güvenli mod davranışını denetler ve test eder | storage.py veya data/*.json şeması değiştiğinde. | 10/10 | ✅ DOĞRULANDI |
| `cost-guard` | Gemini, RSS ve Telegram çağrılarının ücretsiz katmanda kaldığını, limitlerin ve backoff'un doğru çalıştığını, ücretli modele otomatik geçiş olmadığını doğrular | settings.json limitleri, Gemini/Telegram çağrı mantığı veya workflow zamanlaması değiştiğinde. | 14/14 | ✅ DOĞRULANDI |
| `event-clustering-calibrator` | bot/clustering.py benzerlik ağırlıklarını ve cluster_similarity_threshold eşiğini etiketli başlık çiftleriyle kalibre eder; yanlış birleştirme (sahte ÇOKLU KAYNAK) ve kaçırılan birleştirme oranını ölçer | Kümeleme eşiği/ağırlıkları değiştirilmeden önce; yanlış birleşme raporlandığında. | 10/10 | ✅ DOĞRULANDI |
| `gemini-schema-enforcer` | google-genai Structured Outputs kullanımı, untrusted_source_data izolasyonu, Pydantic doğrulaması ve bozuk JSON'da güvenli REJECTED davranışını denetler | gemini.py, istem metni veya çıktı şeması değiştiğinde; model kimliği güncellendiğinde. | 13/13 | ✅ DOĞRULANDI |
| `night-shift-supervisor` | Gece vardiyası görev sırasını yönetir, her adımı NIGHT_PROGRESS.md'ye kaydeder, takılınca 3 denemede durur ve sabah için MORNING_REPORT.md hazırlar | Otonom/uzun oturum başlarken ve biterken. | 11/11 | ✅ DOĞRULANDI |
| `official-source-verifier` | RESMÎ AÇIKLAMA etiketinin yalnızca doğrulanmış Rockstar/Take-Two URL'lerine verildiğini denetler (Google News çözümü, HTML liste, yönlendirme zinciri, canonical) | Resmî kaynak eklendiğinde/değiştiğinde; etiket mantığı değiştiğinde. | 12/12 | ✅ DOĞRULANDI |
| `python-tdd-runner` | Her kod değişikliğinden sonra pytest çalıştırır, 14 kabul testinin tamamının geçtiğini doğrular ve eksik kapsamı kapatır | Her kod değişikliğinden sonra; commit öncesi. | 11/11 | ✅ DOĞRULANDI |
| `rss-anti-poisoning` | Kötü niyetli veya bozuk RSS/HTML içeriğine (prompt injection, homoglif, görünmez karakter, XML bombası, aşırı uzun alan, sahte resmî kaynak, topluluk metninin doğrulanmış habere karışması) karşı savunmaları denetler | Yeni kaynak eklendiğinde; processor/gemini doğrulama kuralları değiştiğinde. | 11/11 | ✅ DOĞRULANDI |
| `rss-integrity-checker` | RSS/Atom ayrıştırma, URL canonicalization, yönlendirme takibi, kaynak sınıfı eşleşmesi ve bozuk XML izolasyonunu test eder | config/sources.json veya collector.py / official.py / textutil.py değiştiğinde. | 11/11 | ✅ DOĞRULANDI |
| `security-auditor` | GTA6 bot kodunda, testlerde ve GitHub Actions dosyalarında secret sızıntısı, SSRF, güvensiz eval/exec ve RSS kaynaklı prompt injection denetimi | Her commit öncesi; bot/, tools/ veya workflow değiştiğinde; yeni bağımlılık eklendiğinde. | 14/14 | ✅ DOĞRULANDI |
| `static-site-guardian` | docs/ altındaki GitHub Pages haber sitesinin ve feed.json köprüsünün güvenliğini, gizlilik ve şema kurallarını denetler (XSS, CSP, gizli veri sızıntısı, yalnızca yayınlanmış haber) | Site, exporter veya demo beslemesi değiştiğinde; yayına almadan önce. | 14/14 | ✅ DOĞRULANDI |
| `telegram-api-guard` | Telegram Bot API kısıtlarını korur; views/forwards uydurulmaz, message_reaction_count idempotent işlenir, yönetici özeti spam yapmaz, sendMessage zaman aşımında tekrar gönderilmez | telegram_client.py, publisher.py veya analyzer.py değiştiğinde. | 12/12 | ✅ DOĞRULANDI |
| `token-budget-guardian` | Uzun/otonom oturumlarda token ve kota tasarrufu kuralları; gereksiz yeniden okumayı, büyük çıktıları ve sonsuz deneme-yanılmayı keser | Her uzun oturumun başında; her büyük adımın sonunda (bütçe kontrol listesi). | 11/11 | ✅ DOĞRULANDI |
| `ui-ux-interaction-standards` | docs/ sitesindeki etkileşim kuralları — süzgeç/sekme/arama anında çalışır, çekmece ve modallar <dialog> ile erişilebilir açılır, boş durum yönlendirir, gerçek veri örnek bültenin önündedir | `docs/assets/app.js` veya `docs/index.html` etkileşim yapısı değiştiğinde. | 17/17 | ✅ DOĞRULANDI |
| `vice-city-design-system` | docs/ sitesinin "Leonida Night" tasarım sistemi — renk, tipografi, cam yüzeyler, güven rozeti renkleri ve kırılımlar | `docs/assets/style.css`, `docs/index.html` görsel yapısı veya yeni bir site bileşeni değiştiğinde. | 13/13 | ✅ DOĞRULANDI |
| `webapp-testing-site` | docs/ sitesini headless Chrome ile 390/820/1440 genişlikte, gerçek (boş olabilir) ve örnek veriyle uçtan uca sınar; yatay taşma, boş durum ve gerçek-veri önceliğini doğrular | `docs/` altındaki HTML/CSS/JS veya `bot/site_exporter.py` çıktısı değiştiğinde; yayına almadan önce. | 11/11 | ✅ DOĞRULANDI |

## Ayrıntılı sonuçlar

### `architect-verifier` — ✅ (37 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 150 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ HTTP POST yalnızca telegram_client.py (+ collector: Google News çözümü, gemini: REST) — uyumlu
- ✅ HTTP GET yalnızca collector.py — uyumlu
- ✅ dosya yazımı yalnızca storage/site_exporter — uyumlu
- ✅ mypy bot temiz — Success: no issues found in 15 source files

### `arena-adversarial-review` — ✅ (33 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 265 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ her tur ≥ 3 regresyon testi — {"1": 4, "2": 4, "3": 4, "4": 3, "5": 4, "6": 6}
- ✅ her turda FAIL ve PASS kanıtı
- ✅ tablo satırlarında dosya:satır
- ✅ pytest tests/test_arena.py — 25 passed in 0.21s

### `atomic-json-recovery` — ✅ (26 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 183 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ lastgood + şema doğrulayıcılar mevcut
- ✅ pytest tests/test_storage.py tests/test_resilience.py -k storage or recover or corrupt or half — 10 passed, 18 deselected in 0.19s

### `cost-guard` — ✅ (25 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 245 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ max_gemini_calls_per_run ≤ 10 — 4
- ✅ http_max_retries ≤ 6 — 3
- ✅ run_deadline_seconds < iş zaman aşımı (15 dk)
- ✅ kodda sabit Gemini model kimliği yok — bulunamadı
- ✅ standart ubuntu-latest runner
- ✅ pytest tests/test_publisher.py::test_gemini_quota_stops_calls_and_never_switches_model tests/test_arena.py::test_r2_sre_huge_retry_after_is_not_slept_through — 2 passed in 0.18s

### `event-clustering-calibrator` — ✅ (20 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 250 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ eşik pozitif/negatif boşluğun içinde — en yüksek negatif 0.157 < eşik 0.27 ≤ en düşük pozitif 0.340
- ✅ pytest tests/test_clustering.py — 15 passed in 0.16s

### `gemini-schema-enforcer` — ✅ (22 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 199 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ şema yalnızca desteklenen JSON Schema anahtar kelimeleri — uyumlu
- ✅ ≥ 6 bağımsız doğrulama kontrolü — 6
- ✅ sistem talimatı untrusted_source_data'yı tanımlar
- ✅ SDK çağrısı response_json_schema kullanır
- ✅ pytest tests/test_processor.py — 11 passed in 0.11s

### `night-shift-supervisor` — ✅ (26 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 194 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ NIGHT_PROGRESS.md ve MORNING_REPORT.md var
- ✅ kodda 'git push' yok (yalnızca workflow) — bulunamadı
- ✅ İNSAN MÜDAHALESİ başlığı raporda tanımlı

### `official-source-verifier` — ✅ (22 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 222 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ resmî kaynak sayısı ≥ 2 ve etkin — 4 etkin
- ✅ resmî kaynak alan adları yalnızca rockstargames.com / take2games.com — uyumlu
- ✅ üçlü koşul (OFFICIAL + url_verified + alan adı) kodda
- ✅ pytest tests/test_resilience.py tests/test_injection.py tests/test_arena.py -k official or google_news or html_listing or reverified — 14 passed, 49 deselected in 0.16s

### `python-tdd-runner` — ✅ (30 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 184 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ 14 kabul testi tanımlı — 14/14
- ✅ pytest  — 190 passed in 1.14s
- ✅ ruff temiz — All checks passed!

### `rss-anti-poisoning` — ✅ (26 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 278 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ saldırı yükü kütüphanesi ≥ 8 — 8
- ✅ homoglif katlama aktif
- ✅ pytest tests/test_injection.py tests/test_arena.py -k injection or homoglyph or padded or blend or links — 21 passed, 20 deselected in 0.15s

### `rss-integrity-checker` — ✅ (27 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 187 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ tüm feed_url https
- ✅ her kaynakta allowed_domains
- ✅ pytest tests/test_collector.py tests/test_resilience.py — 33 passed in 0.25s

### `security-auditor` — ✅ (30 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 233 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ gerçek biçimli token/anahtar yok — bulunamadı
- ✅ eval/exec/pickle/shell=True/verify=False yok — bulunamadı
- ✅ workflow yalnızca schedule + workflow_dispatch — schedule, workflow_dispatch
- ✅ secret'lar yalnızca bot adımında
- ✅ XML yalnızca defusedxml
- ✅ pytest tests/test_publisher.py::test_secrets_never_logged — 1 passed in 0.18s

### `static-site-guardian` — ✅ (32 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 264 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ app.js'te innerHTML/eval/document.write yok
- ✅ CSP: script-src 'self', object-src 'none', base-uri 'none'
- ✅ index.html'de satır içi betik yok
- ✅ feed.json'da hassas alan yok
- ✅ feed.json yalnızca https bağlantı
- ✅ pytest tests/test_site_exporter.py — 35 passed in 0.19s

### `telegram-api-guard` — ✅ (25 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 225 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ allowed_updates yalnızca message_reaction_count
- ✅ views/forwards yalnızca 'unavailable' — 2 yer
- ✅ 4096 sınırı ve retry_after üst sınırı
- ✅ pytest tests/test_analyzer.py tests/test_publisher.py — 21 passed in 0.30s

### `token-budget-guardian` — ✅ (29 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 198 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ hiçbir hata 2 denemeyi aşmadı (kayıtlara göre) — kayıtlı denemeler: 2, 2, 1, 2, 2
- ✅ alt ajan açılmadı (roller tek bağlamda)
- ✅ ilerleme kaydı tek satırlık adımlarla tutuluyor — 21 satır

### `ui-ux-interaction-standards` — ✅ (34 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 254 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ örnek bülten tembel yüklenir
- ✅ gerçek veri önceliği (realItems.length)
- ✅ harita: bölge verisi + konum yedeği
- ✅ animasyonlar transform/opacity (left/top/width animasyonu yok)
- ✅ diyaloglar showModal ile
- ✅ safeHttps ve textContent
- ✅ localStorage try/catch
- ✅ index.html gerekli kimlikler
- ✅ dört güven rozeti adı

### `vice-city-design-system` — ✅ (48 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 270 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ tasarım token'ları tanımlı
- ✅ [hidden] her zaman gizler
- ✅ prefers-reduced-motion bloğu
- ✅ kırılımlar 760px ve 1100px
- ✅ güven rozeti sınıfları

### `webapp-testing-site` — ✅ (32 satır)

- ✅ frontmatter (name + description)
- ✅ ad klasörle aynı
- ✅ açıklama 30–1024 karakter — 240 karakter
- ✅ gövde ≥ 8 anlamlı satır (taslak değil)
- ✅ 'Ne zaman tetiklenir' bölümü
- ✅ 'Otomatik doğrulama' bölümü
- ✅ gizli kabuk komutu yok (curl|sh, base64 -d)
- ✅ proje dışı yol yok (~/.ssh, ~/.aws, /etc)
- ✅ tools/site_check.py var
- ✅ app.js selftest kancası
- ✅ tarayıcı matrisi 3×2

## Bu oturumda aktif uygulanan skill'ler

### `token-budget-guardian`
- Dosyalar bir kez okundu; düzenlemeler hedefli `python - <<EOF` yamalarıyla yapıldı (tam dosya yeniden yazımı yalnızca yeni dosyalarda).
- Araç çıktıları `| tail -N` / `| head -N` ile kısıtlandı; tam `pytest -v` yalnızca rapor için bir kez çalıştırıldı.
- 2 deneme kuralı: Aşama 4'te hiçbir hata 2. denemeye kalmadı (Tur 6 yamaları ilk denemede yeşil).
- Alt ajan açılmadı; Arena rolleri tek bağlamda sırayla oynandı.

### `arena-adversarial-review`
- **Tur 6** (site + köprü) bu oturumda yürütüldü: 6 bulgu → 6 FAIL testi → yama → tamamı PASS. İki bulgu doğrudan demo
  üretiminden çıktı (12 haberden 2'si haksız yere incelemeye takılıyordu). Ayrıntı: `ARENA_DEBATE_LOG.md` → Tur 6.

### `official-source-verifier`
- Demo hattında iki resmî kaynak (Rockstar Newswire HTML listesi + Take-Two IR) gerçek `collect()` yolundan geçti;
  RESMÎ AÇIKLAMA rozeti yalnızca doğrulanmış resmî alan adlı 3 habere verildi; manşet en yeni resmî haber.
- Skill'in işlevsel denetimi `sources.json` resmî kaynak alan adlarını ve üçlü koşulu kodda doğruladı.
