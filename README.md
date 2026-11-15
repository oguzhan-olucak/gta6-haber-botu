# GTA VI Türkiye Bülteni — otonom Telegram haber botu

GTA VI haberlerini RSS kaynaklarından toplayan, kaynakları **kodla** sınıflandıran, Gemini ile kısa ve özgün Türkçe özet hazırlayan, doğrulama kurallarından geçen haberleri herkese açık Telegram kanalına gönderen ve gönderilerin reaksiyonlarını ölçen bot. GitHub Actions üzerinde yaklaşık 20 dakikada bir çalışır.

> Bu bot hata durumunda yanlış haber yayımlamak yerine **durur**. "Sıfır müdahale" yalnızca kurulumdan sonraki normal akış için hedeflenmiştir; dış servis kesintisi, kota dolması veya platform değişikliği için garanti verilmez.

## Nasıl çalışır

```mermaid
flowchart LR
  A[GitHub Actions<br/>schedule / dispatch] --> B[main.py]
  B --> C{paused?}
  C -- evet --> M
  C -- hayır --> D[collector.py<br/>RSS/Atom + canonical URL<br/>alan adı allowlist]
  D --> E[processor.py<br/>kümeleme + tekrar kontrolü<br/>source_strength / editorial_priority]
  E -- CANDIDATE --> F[Gemini<br/>Structured Outputs]
  F --> G[validate_generated<br/>şema + uydurma ayrıntı + kesinlik dili]
  G -- READY --> H[publisher.py<br/>idempotent sendMessage]
  E -- HOLD/REJECT --> S[(state.json)]
  G -- REJECTED/REVIEW_HELD --> HI[(history.json)]
  H --> HI
  B --> M[analyzer.py<br/>getUpdates: message_reaction_count]
  M --> I[(insights.json)<br/>yalnızca başlık stili ipucu]
  I -.-> F
  B --> J[Yönetici özeti 06/18 UTC<br/>alarmlar 6 saat tekilleştirme]
```

| Modül | Sorumluluk |
|---|---|
| `bot/config.py` | `settings.json` / `sources.json` doğrulama (Pydantic), secret'ları `os.environ`'dan okuma, loglarda secret maskeleme |
| `bot/storage.py` | Atomik JSON (`tempfile` + `os.replace`), bozuk dosyayı ezmeden `.corrupt.<zaman>.bak` yedeği, dosya kilidi |
| `bot/telegram_client.py` | Tüm Telegram HTTP çağrıları, token maskeleme, 429/5xx için sınırlı backoff; `sendMessage` zaman aşımında yeniden gönderim yok |
| `bot/collector.py` | RSS/Atom (defusedxml, bozuk UTF-8 onarımı), Google News ve HTML liste kaynakları, URL canonicalization, alan adı eşleşmesi, atıf zinciri, SSRF korumalı URL doğrulama |
| `bot/official.py` | Resmî kaynak yardımcıları: Google News bağlantı çözümü, HTML liste/JSON-LD ayrıştırıcı |
| `bot/textutil.py` | HTML→metin, mojibake/bozuk UTF-8 onarımı, görünmez karakter temizliği, güvenli kırpma, Türkçe büyük harf |
| `bot/clustering.py` | Olay kümeleme motoru: TF-IDF kosinüs + karakter 3-gram + özel isim/sayı örtüşmesi, ortalama bağlantı |
| `bot/labels.py` | Etiketler ve değerlendirme veri tipi |
| `bot/processor.py` | Kümeleme adaptörü, tekrar önleme, prompt injection şüphelilerini ayıklama, deterministik puanlama ve etiket |
| `bot/gemini.py` | Çıktı şeması, istem, 6 aşamalı deterministik çıktı doğrulama, `google-genai` istemcisi |
| `bot/publisher.py` | Mesaj şablonu, idempotent yayın, günlük limit, yönetici özeti, alarm tekilleştirme |
| `bot/analyzer.py` | Reaksiyon güncellemeleri, ölçüm durumu, kategori/başlık stili analizi |
| `bot/site_exporter.py` | Statik site beslemesi (`docs/data/feed.json` + `feed.js`): beyaz liste alanlar, XSS temizliği, manşet ve vitrin seçimi |
| `bot/main.py` | Orkestrasyon ve JSON çalışma özeti |

## Yayın etiketleri

| Rozet | Etiket | Ne zaman | Varsayılan |
|---|---|---|---|
| 🟩 | RESMÎ AÇIKLAMA | Haber doğrudan `rockstargames.com` / `take2games.com` alan adında | Yayınlanır |
| 🟦 | ÇOKLU KAYNAK | En az 2 **bağımsız** köken (aynı ilk haberi kopyalayanlar ve aynı yayın grubu tek sayılır) | Yayınlanır |
| 🟨 | TEK KAYNAK | Tek güvenilir yayın organı | `allow_single_source_media` |
| 🟥 | SIZINTI İDDİASI | Başlıkta leak/rumor/insider vb. | `allow_community_rumors` (kapalı) |
| 🟧 | TOPLULUK İDDİASI | Yalnızca Reddit/topluluk | `allow_community_rumors` (kapalı) |

Etiketi model değil Python belirler. Model "resmî" dese bile resmî alan adı yoksa gönderi incelemeye takılır. Şablonların görünümü: `docs/message_preview.html`. Bu sayfa, gerçek ağa bağlanmadan tüm hattı sahte servislerle çalıştıran simülatörle üretilir: `python tools/dry_run_simulator.py` (tek senaryo için `--scenario multi`, menü için `--interactive`, terminale yazdırmak için `--print`).

## Resmî kaynaklar nasıl doğrulanır

Rockstar ve Take-Two için doğrulanmış bir RSS adresi bulunamadığından iki yol kullanılır:

1. **Google News alan adı kısıtlı sorgu** (`kind: "google_news"`). Google News bağlantıları `news.google.com/rss/articles/…` biçimindedir. Bot önce eski biçimi çevrimdışı çözer; olmazsa yönlendirmeyi SSRF korumalı olarak takip eder. **Nihai adres `rockstargames.com` / `take2games.com` değilse öğe atılır.** Yeni (imzalı) Google News bağlantılarının bir kısmı yalnızca JavaScript ile çözülebildiği için bu öğeler kaybolabilir. Bu, bilinçli bir "yanlış resmî etiket yerine eksik haber" tercihidir.
2. **HTML liste ayrıştırıcı** (`kind: "html_listing"`). Sayfadaki `<a href>` bağlantıları ve JSON-LD verisi, `link_pattern` düzenli ifadesiyle süzülür. Sayfa istemci tarafında çiziliyorsa sonuç boş olur ve kaynak durumuna `warning` yazılır.

Bir öğenin RESMÎ AÇIKLAMA alabilmesi için üç koşul birlikte sağlanmalıdır: `trust_class: OFFICIAL`, `url_verified: true` ve nihai URL'nin resmî alan adında olması. Bu kontrol `collector` ve `processor` içinde iki ayrı kez yapılır.

## Olay kümeleme

Farklı sitelerin aynı olayı farklı başlıklarla yazması `bot/clustering.py` ile tek kümede toplanır. Kümede bağımsız iki yayın kökeni varsa haber otomatik olarak **ÇOKLU KAYNAK** rozetine yükselir. Eşik `cluster_similarity_threshold` (0.27) değeriyle ayarlanır. Bu değer test setinde aynı olay çiftlerini (≥0.35) farklı olay çiftlerinden (≤0.17) ayıracak şekilde kalibre edildi. Yanlış birleştirmeye karşı üç kural var: çelişen sayılar ("Trailer 2" ≠ "Trailer 3"), ayırt edici özel isim çatışması ("Lucia" ↔ "Jason") ve 72 saatten uzun zaman farkı. Kümeler ortalama bağlantıyla oluşur, yani zincirleme birleşme olmaz.

## Gerçekten ölçülebilen metrikler

- **Ölçülebilen:** `message_reaction_count` güncellemeleri, yani kanal gönderisindeki anonim toplam reaksiyon sayıları. Bot kanalda **yönetici** olmalı ve `getUpdates` `allowed_updates=["message_reaction_count"]` ile çağrılır. Güncellemeler gruplanır ve birkaç dakika gecikebilir. Yalnızca bundan **sonraki** değişiklikler gelir; geçmiş reaksiyonlar geriye dönük sorgulanamaz.
- **Ölçülemeyen:** görüntülenme (`views`) ve iletilme (`forwards`). Bot API'de bu sayıları sorgulayan bir metot yoktur. Bu alanlar her zaman `"unavailable"` kalır ve reaksiyon **oranı** hesaplanmaz. MTProto kullanıcı oturumu kullanılmaz.
- Kullanıcı bazlı `message_reaction` güncellemeleri istenmez ve kullanıcı kimliği saklanmaz.
- Analiz, her grupta en az `min_sample_per_group` (5) gönderi olmadan kazanan ilan etmez. `early_signal_below_n` (15) altındaki sonuçlar "erken sinyal" olarak raporlanır. İçgörüler yalnızca başlık stili ipucu olarak kullanılır; eşikleri ve güven sınıfını değiştiremez.

## Kurulum

1. **Repo:** Bu klasörü yeni bir **public** GitHub reposuna `main` dalı olarak yükleyin. Standart GitHub-hosted runner'lar public repolarda ücretsizdir.
2. **Telegram botu:** Telegram'da @BotFather → `/newbot` → token'ı **yalnızca** GitHub Secrets'a girin, başka hiçbir yere yapıştırmayın. Kanalınızı oluşturun, botu **yönetici** olarak ekleyin ve "Mesaj gönderme" iznini verin. Kanal ID'si: public kanal için `@kanaladi` da kullanılabilir. Sayısal ID (`-100…`) önerilir.
3. **Gemini:** Google AI Studio'da API anahtarı oluşturun. **Ücretli katmanı (billing) açmayın**, aksi halde 0 TL hedefi geçerliliğini yitirir. AI Studio'daki rate-limit sayfasından ücretsiz katmanda olan **kararlı (stable)** bir model kimliği seçin.
4. **GitHub → Settings → Secrets and variables → Actions:**
   - Secrets: `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - Variables: `GEMINI_MODEL` (ör. AI Studio'da doğruladığınız model kimliği), isteğe bağlı `ADMIN_CHAT_ID` (özet ve uyarıların gideceği özel sohbet/grup)
   - `GITHUB_TOKEN` otomatik gelir; eklemeyin.
5. **İzinler:** Workflow dosyası `permissions: contents: write` ile kendi iznini açıkça tanımlar. Repo ayarlarını değiştirmeniz genellikle gerekmez. Commit adımı 403 verirse Settings → Actions → General → Workflow permissions bölümünü kontrol edin.
6. **İlk test:** Actions → `gta6-bot-run` → **Run workflow**. Log'daki JSON özetinde `source_status` ve `error_classes` alanlarını kontrol edin.

## Güvenlik ve kalite katmanları (özet)

- **Prompt injection:** Kaynak metni `<untrusted_source_data>` içinde ve kaçırılmış olarak modele gider. Talimat kalıbı taşıyan öğeler kümeden ayıklanır; dedektör homoglif, görünmez karakter ve dolgu ile atlatma girişimlerine karşı sertleştirildi. Etiketi belirleyen güven katmanı dışındaki öğeler (ör. Reddit) ne isteme ne kaynak listesine girer.
- **Model çıktısı:** şema (ek alan yasak) → uzunluk → yalnızca kümedeki URL'ler → bağlantı/@kullanıcı/HTML/emoji yasağı → kesinlik dili (yalnızca RESMÎ) → TEK KAYNAK ve İDDİA etiketlerinde atıf zorunluluğu ve soru başlığı yasağı → kaynakta olmayan sayı/platform/ay → `needs_review`.
- **Dayanıklılık:** çalışma süresi sınırı (`run_deadline_seconds`), görülmüş bağlantıları yeniden doğrulamama, `retry_after > 60` için vazgeçme, yapısal JSON doğrulaması ve `.lastgood` kurtarma, state için saatlik yazım (`state_heartbeat_minutes`).
- Ayrıntılı saldırı ve düzeltme geçmişi: `ARENA_DEBATE_LOG.md`. Geliştirici skill'leri: `.claude/skills/`.

## Haber sitesi (GitHub Pages, 0 TL)

`docs/` klasörü kendi başına çalışan statik bir haber portalıdır: manşet, doğrulama düzeyi süzgeçleri, kategori sekmeleri, canlı arama, haber detay çekmecesi, canlı sistem durum bandı ve Telegram önizleme sayfası. Sunucu ve derleme adımı yoktur.

- **Veri köprüsü:** Bot her çalışmada `bot/site_exporter.py` ile `docs/data/feed.json` ve `docs/data/feed.js` dosyalarını üretir. Yalnızca yayınlanmış haberler, temizlenmiş metinler ve https bağlantılar yazılır; chat_id ve iç alanlar yazılmaz. Workflow bu iki dosyayı da commit eder, böylece site kendiliğinden güncellenir.
- **Tek seferlik açılış:** Repo → **Settings → Pages → Build and deployment → Source: "Deploy from a branch" → Branch: `main`, klasör: `/docs` → Save**. Birkaç dakika sonra site `https://<kullanıcı-adın>.github.io/<repo-adı>/` adresinde yayında olur. Public repolarda GitHub Pages ücretsizdir.
- **Yerelde açma:** `docs/index.html` dosyasını tarayıcıda açmak yeterli. `feed.js` sayesinde `file://` ile de çalışır.
- **Demo verisi:** Repodaki `feed.json` 12 haberlik örnek veridir (`"demo": true`, sitede "Örnek veri" rozeti görünür). Bot ilk çalıştığında gerçek haberlerle değişir. Yeniden üretmek için: `python tools/dry_run_simulator.py`.
- **Telegram mesaj bağlantıları:** Kanal herkese açıksa `config/settings.json` → `"public_channel_username": "kanaladi"` yaz; sitedeki "Telegram'da aç" düğmesi gönderiye gider. Boşsa düğme paylaşım bağlantısına döner.
- **Güvenlik:** CSP meta etiketi (yalnızca kendi betikleri), veriler yalnızca `textContent` ile basılır, bağlantılar https denetiminden geçer. Kuralların tamamı: `.claude/skills/static-site-guardian/SKILL.md`.

## Kill switch

`config/settings.json` içinde `"paused": true` yapıp commit edin. Bu durumda toplama, Gemini çağrısı ve kanal yayını yapılmaz. Reaksiyon ölçümü ve yönetici özeti sürer. Açmak için tekrar `false` yapın.

## Zamanlama ve sınırlar

- Workflow `7,27,47 * * * *` ile çalışır (20 dakikada bir, saat başı yoğunluğundan kaçınır). GitHub `schedule` olayı **en iyi çaba** ile çalışır: çalışmalar gecikebilir veya atlanabilir; en kısa desteklenen aralık 5 dakikadır. Kaçırılan aralık sorun yaratmaz, çünkü bot son `max_item_age_hours` (48 saat) içindeki her öğeye bakar ve `seen_items` ile tekrarı önler.
- Zamanlanmış workflow'lar yalnızca varsayılan dalda (`main`) çalışır.
- **60 gün kuralı:** Public repoda 60 gün boyunca hiç etkinlik olmazsa GitHub zamanlanmış workflow'u devre dışı bırakır. Bot her çalışmada `data/state.json`'u commit ettiği için normalde repo etkin kalır. Workflow yine de devre dışı kalırsa Actions sekmesindeki sarı uyarıdan **Enable workflow** ile yeniden açın.
- Gemini 429 alırsa çağrılar `gemini_quota_cooldown_minutes` boyunca durur. Başka bir modele veya ücretli katmana **asla** geçilmez.
- Günlük gönderi sınırı (`max_daily_posts`) varsayılan olarak **Türkiye saatine (TRT, UTC+3) göre takvim günü** üzerinden sayılır: sayaç TRT gece yarısı sıfırlanır, UTC gece yarısı (TRT 03:00) etkilemez. Kayan 24 saat davranışı için `"daily_limit_mode": "rolling_24h"` kullanın.

## Hata ve güvenli mod

| Durum | Davranış |
|---|---|
| Bir RSS kaynağı bozuk/erişilemez | Yalnızca o kaynak atlanır, `source_status` güncellenir |
| 24 saat hiç veri yok / kalıcı 401-403 | Yönetici uyarısı (aynı uyarı 6 saatte bir) |
| `history.json` / `state.json` bozuk, `*.lastgood.json` sağlam | Bozuk dosyanın yedeği alınır, son sağlam kopyadan **otomatik kurtarılır**, yönetici uyarısı gönderilir, çalışma sürer |
| `history.json` bozuk ve son sağlam kopya yok/bozuk | Dosya **ezilmez**, yayın ve Gemini durur, uyarı gönderilir, çıkış kodu 2 |
| `state.json` bozuk ve son sağlam kopya yok/bozuk | Hiçbir şey yazılmaz, çıkış kodu 2 (GitHub başarısız çalışma e-postası gönderir) |
| `insights.json` bozuk | Nötr varsayılan istemle devam edilir |
| Telegram zaman aşımı | Gönderi `UNCERTAIN` olarak işaretlenir ve **yeniden gönderilmez** (mükerrer yayın yerine olası tek kayıp) |

## Yerel geliştirme

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
mypy bot && ruff check bot tests tools     # tip ve stil denetimi (pyproject.toml)
python tools/dry_run_simulator.py           # ağsız tam hat simülasyonu → docs/message_preview.html + docs/data/feed.json (12 demo haber)
python tools/skill_audit.py                 # 15 skill'in kurallarını koda karşı çalıştırır → SKILL_AUDIT_REPORT.md
```

Testler gerçek ağa çıkmaz (`tests/conftest.py` engeller) ve yalnızca `DUMMY_..._DO_NOT_USE` sahte sabitlerini kullanır.

## Telif

Bot yalnızca başlık, kaynak URL'si, yayın zamanı ve kısa olgusal özet kullanır. Kaynak metin veya görsel kopyalanmaz ve her gönderide orijinal kaynağa bağlantı verilir.
