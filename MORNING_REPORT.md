# MORNING_REPORT — Gece Vardiyası Sonuç Raporu

**Tarih:** 16 Kasım 2026, Pazartesi · Vardiya: 00:51 – sabah (Faz 1 + Faz 2 + Aşama 3 Arena + Aşama 4 Haber Sitesi)

---

## 1. Yönetici Özeti

| | |
|---|---|
| **Genel durum** | **KISMİ HAZIR.** Bot, haber sitesi, testler, workflow ve dokümanlar tamam. Canlıya çıkmadan önce senin yapman gereken 8 adım ve canlıda doğrulanması gereken 3 dış varsayım var (bkz. bölüm 6–7). |
| **Haber sitesi** | `docs/index.html`: Vice City gece temalı, 0 TL GitHub Pages portalı. Manşet, doğrulama süzgeçleri, kategori sekmeleri, canlı arama, detay çekmecesi, canlı durum bandı, mobil uyumlu. Bot her çalışmada `docs/data/feed.json`'u günceller. Şu an 12 haberlik **örnek veri** yüklü. |
| **Testler** | **160 / 160 geçti.** Gece başında 49 testti: Faz 2'de 55, Arena'da 25, Aşama 4'te 31 test eklendi. Komut: `python -m pytest -v`. Gerçek ağ çağrısı yok. |
| **Tip ve stil** | `mypy bot` (15 modül): **temiz** · `ruff`: **temiz** · tüm genel fonksiyonlarda docstring var |
| **Arena** | 6 tur, 4 rol, **25 kanıtlanmış açık**. Her biri önce FAIL eden bir teste çevrildi, sonra yamalanıp PASS'e döndü (`ARENA_DEBATE_LOG.md`). |
| **Skill'ler** | **15 skill**, `tools/skill_audit.py` ile **15/15 doğrulandı** (`SKILL_AUDIT_REPORT.md`) |
| **Yerel git** | 22 commit, `main` dalı. **Push yapılmadı.** |

**Çıkışa 3 gün var (19 Kasım).** Bu gece resmî kaynak açığı kapatıldı: Rockstar Newswire ve Take-Two artık Google News alan adı sorgusu ve HTML liste ayrıştırıcıyla izleniyor. Ancak bu iki yolun canlı çalıştığı bu oturumda doğrulanamadı (ağ kapalıydı). İlk elle çalıştırmada kontrol et (bölüm 6, adım 6).

---

## 2. Gerçeklik Denetimi Bulguları (kontrol tarihi: 16 Kasım 2026)

| Konu | Bulgu | Sonuç |
|---|---|---|
| **GTA VI çıkışı** | 19 Kasım 2026 (Perşembe), PS5 ve Xbox Series X\|S. PC duyurulmadı. Rockstar tarihi 6 Kasım 2025'te duyurdu; 15 Ekim 2026 fragmanı tarihi teyit etti. [TechRadar](https://www.techradar.com/gaming/grand-theft-auto-6-delayed-again-but-itll-still-ship-in-2026), [GTABoom](https://www.gtaboom.com/gta-6-release-date-and-delay-history-9f6b) | **Doğrulandı** (ikincil kaynaklar). Kodda sabit değil. |
| **Gemini modeli** | `gemini-3.5-flash` resmî sayfada Stable. Structured outputs dokümanı (2026-10-19) daha yeni kimlikler kullanıyor. [ai.google.dev](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash) | **Koşula bağlı:** `GEMINI_MODEL` Variable'ını sabah AI Studio'dan seç. |
| **Structured Outputs** | Python SDK: `response_mime_type` + `response_json_schema`. REST biçimi değiştiği için resmî `google-genai` SDK'sı kullanıldı. [doküman](https://ai.google.dev/gemini-api/docs/generate-content/structured-output?hl=en) | **Doğrulandı.** SDK canlı denenmedi (paket kurulumu kapalıydı). Model yanıtı kod çitine sararsa da çözülüyor. |
| **Gemini ücretsiz katman** | Flash modelleri ücretsiz. Limitler projeye göre AI Studio'da görünüyor. Ücretsiz katman verisi ürün geliştirmede kullanılabilir. | **Koşula bağlı** |
| **Gemini — Türkiye** | Resmî bölge listesi kesik geldi. | **Doğrulanamadı.** AI Studio'da anahtar oluşturabiliyorsan erişim var. |
| **Telegram Bot API** | 10.4 (9 Kasım 2026). views/forwards alınamıyor. `message_reaction_count` için bot yönetici olmalı ve update türü açıkça istenmeli. Webhook açıkken `getUpdates` çalışmaz. [core.telegram.org](https://core.telegram.org/bots/api) | **Doğrulandı** |
| **GitHub Actions** | Public repoda standart runner ücretsiz. Schedule en iyi çaba ile çalışır (en kısa aralık 5 dk). 60 gün hareketsizlikte devre dışı kalır. [docs.github.com](https://docs.github.com/en/billing/concepts/product-billing/github-actions) | **Doğrulandı** |
| **Google News RSS bağlantıları** | 2024'ten beri çoğu bağlantı çevrimdışı çözülemeyen imzalı kimlik. Yönlendirme takibi çoğunda çalışıyor, bir kısmı JavaScript gerektiriyor. | **Koşula bağlı:** çözülemeyen öğe atılır (yanlış "resmî" etiketi yerine eksik haber). |
| **Take-Two IR** | `ir.take2games.com` haber listesi var, sayfada "RSS Feeds" bağlantısı görünüyor. Tam besleme adresi doğrulanamadı. | **Koşula bağlı:** HTML liste + Google News ile izleniyor. |

---

## 3. Faz 2 — Ne Eklendi

| Alan | Sonuç |
|---|---|
| **Resmî kaynak açığı** | `bot/official.py`: Google News alan adı sorgusu (çevrimdışı çözüm → SSRF korumalı yönlendirme takibi) ve HTML liste/JSON-LD ayrıştırıcı. RESMÎ etiketi için üç koşul birden gerekli: OFFICIAL sınıfı, `url_verified` ve resmî alan adı. Bu kontrol iki ayrı yerde yapılıyor. `sources.json`'a 4 resmî kaynak eklendi. |
| **Olay kümeleme** | `bot/clustering.py`: TF-IDF kosinüs (0.5) + karakter 3-gram (0.3) + özel isim/sayı (0.2), ortalama bağlantı. Kalibrasyon: aynı olay ≥0.35, zor negatifler ≤0.17, eşik 0.27. Sert engeller: çelişen sayı, varlık çatışması (Lucia ↔ Jason), 72 saat. İki bağımsız yayın aynı olayı farklı başlıkla yazınca haber otomatik olarak ÇOKLU KAYNAK'a yükseliyor. |
| **Test paketi** | +55 test: kümeleme (15), injection (16), dayanıklılık (22: UTF-8 ve Türkçe karakter, mojibake, kırpma, .lastgood kurtarma, TRT/UTC günlük limit, Google News/HTML), simülatör (2) |
| **Simülatör** | `tools/dry_run_simulator.py`: ağ kalkanlı tam hat simülasyonu (5 senaryo, `--interactive`, `--scenario`, `--print`). Çıktısı `docs/message_preview.html`: Telegram mobil arayüzü maketi, Vice City gün batımı teması. |
| **Kod kalitesi** | Modüller ayrıştırıldı (`labels`, `gemini`, `textutil`, `official`, `clustering`). `main.py` `RunContext` ile 15 küçük fonksiyona bölündü. Doğrulama 6 bağımsız `check_*` fonksiyonuna ayrıldı. `pyproject.toml` (mypy + ruff + pytest) eklendi. |
| **Veri kurtarma** | `*.lastgood.json`: ana dosya bozuk veya yarım yazılmışsa otomatik kurtarma ve yönetici uyarısı. İkisi de bozuksa güvenli mod. |
| **Günlük limit** | Varsayılan olarak TRT takvim günü: TRT gece yarısı sıfırlanır, UTC gece yarısı sıfırlamaz. `rolling_24h` seçeneği var. |

---

## 3b. Aşama 4 — Haber Sitesi ve Skill Doğrulama

| Alan | Sonuç |
|---|---|
| **Site** | `docs/index.html` + `docs/assets/style.css` + `docs/assets/app.js`. Renkler: gece `#090A0F`, neon pembe `#FF2A85`, elektrik turkuaz `#00F0FF`, gün batımı altını `#FFB800`. Gün batımı ve neon ufuk ızgaralı manşet, editoryal ızgara (2 vitrin + 3 sütun), sticky başlık. Mobil, tablet ve masaüstü başsız Chrome ile ekran görüntüsü alınarak kontrol edildi. |
| **Etkileşim** | Doğrulama düzeyi süzgeçleri (sayaçlı), kategori sekmeleri (Fragman, Oynanış, Çıkış/Platform, Sızıntı, Analiz), Türkçe karakter duyarsız canlı arama, `#haber-<id>` derin bağlantılı detay çekmecesi (tam özet, "Neden bu etiket?", kaynak gücü, kaynak bağlantıları, Telegram'da aç/paylaş, bağlantı kopyala), canlı durum bandı (çalışıyor/gecikmeli/duraklatıldı, son güncelleme, kaynak sayısı, doğrulanmış haber sayısı) |
| **Köprü** | `bot/site_exporter.py`: yalnızca `PUBLISHED` haberler, beyaz liste alanlar (chat_id ve iç alanlar yok), çift kodlanmış HTML dahil temizlik, yalnızca https bağlantı. Manşet en yeni resmî haber; vitrinde önce doğrulanmış haberler. `feed.js` sayesinde site `file://` ile de açılıyor. `main.py` her çalışmada üretiyor; bir hata olursa bile yayını durdurmuyor. |
| **Demo** | `tools/dry_run_simulator.py` → `tools/demo_site.py`: 12 haber elle yazılmadı. Her biri kendi saatinde **gerçek bot hattından** geçti: toplama, kümeleme, etiket, doğrulama, yayın, dışa aktarım. Dağılım: 3 resmî, 3 çoklu, 4 tek kaynak, 1 sızıntı, 1 topluluk. Kaynak bağlantıları uydurma makale adresi değil, yayınların ana sayfaları. |
| **Telegram önizleme** | `docs/message_preview.html` korundu; sitenin üst menüsünden erişiliyor, kendi menüsünden de haberlere geri dönülüyor. |
| **Skill doğrulama** | `tools/skill_audit.py` her skill'i yapısal (8 kontrol) ve işlevsel olarak denetliyor; işlevsel kısım skill kurallarını kod, ayar ve testlere karşı çalıştırıyor. İlk koşuda denetleyicinin kendisinde 5 yanlış alarm çıktı (kendi desenlerini ve yorum satırlarını yakalıyordu); düzeltildi → **15/15**. |
| **Arena Tur 6** | 6 açık bulundu. 2'si demo üretiminden çıktı: olumsuz kesinlik ifadesi ve "PC Gamer" yayın adı yanlış alarmı, 12 haberden 2'sini haksız yere düşürüyordu. Diğerleri: çift kodlu HTML'nin beslemeye sızması, iç kimliklerin okura gösterilmesi, vitrinde iddia haberleri, workflow'un site beslemesini commit etmemesi. |

---

## 3c. Site Yenileme — "Leonida Night"

- `docs/` baştan tasarlandı: sinematik gün batımı manşeti (öne çıkan haber), 19 Kasım 2026 geri sayımı + kilometre taşları,
  11 kaynaklık **kaynak nabzı**, dört güven rozeti, okuma süresi, kaynak alan adı önizlemesi, tek tıkla Telegram'da
  paylaş / bağlantı kopyala, anında güven/kategori süzgeci ve arama (`/`), haber çekmecesi, "Telegram önizleme" ve
  "Nasıl doğruluyoruz" modalları (derin bağlantı: `#haber-<id>`, `#telegram`, `#yontem`).
- Boş akışta: "İlk doğrulanmış haber yolda" manşeti, iskelet kartlar ve **Örnek bülten önizlemesini göster/gizle** anahtarı.
  Örnek veri ayrı dosyada (`docs/data/demo-feed.*`) ve yalnızca istek üzerine yüklenir; gerçek haber gelince her zaman gerçek veri görünür.
- Şema geriye uyumlu: `status.sources` (kaynak nabzı) eklendi, eski alanlar aynen duruyor. Bot bir sonraki çalışmada
  bu alanı doldurur; o zamana kadar nabız yalnızca "11/11 kaynak yanıt verdi" özetini gösterir.
- Simülatör artık `feed.json`'un üzerine yazmıyor (önceden test çalıştırmak canlı beslemeyi örnekle değiştirebiliyordu).
- Yeni skill'ler: `vice-city-design-system`, `ui-ux-interaction-standards`, `webapp-testing-site` + `.claude/skills/README.md` dizini.
  `python tools/site_check.py` 390/820/1440 × gerçek/örnek matrisini headless Chrome ile sınar (taşma yok).

## 3d. Leonida Komuta Merkezi + kaynak ve Gemini düzeltmeleri

- **Site:** üst kısım etkileşimli, özgün ve stilize bir Leonida haritası (SVG). Beş nabız atan bölge var: Vice City,
  Leonida Keys, Grassrivers, Port Gellhorn & Ambrosia, Mount Kalaga. Bir bölgeye tıklayınca kamera yakınlaşır, bölge
  paneli açılır ve akış süzülür. Kartın üzerine gelmek haritayı önizler; "Haritada göster" haritaya götürür.
  Sayfada fare/kaydırma paralaksı, projektör hüzmeleri, tarama çizgisi dokusu, kademeli açılış, neon dijital geri
  sayım, bölgeye özgü SVG kapaklar, 3B kart eğimi ve okuma ilerleme çubukları var. Telegram önizleme ve "Nasıl
  doğruluyoruz" cam efektli yan çekmeceler. Gerçek akış boşken örnek bülten varsayılan olarak açılır.
- **feed.json:** opsiyonel `location_id` + `region` (eski veriyle geriye uyumlu; `bot/site_exporter.classify_location`).
- **Kaynaklar:** GTA VI ilgi filtresi genişletildi (Leonida, GTAVI, Vice City/Lucia/Jason + Rockstar...). Resmî
  kaynaklara 7 günlük pencere verildi. İmzalı Google News bağlantıları `batchexecute` ile çözülüyor. İstemci tarafında
  çizilen Newswire sayfasında gömülü bağlantılar yakalanıyor. Kaynak durumunda `relevant` (eşleşen) ve `new` (eklenen)
  ayrı tutuluyor.
- **Gemini:** varsayılan istemci REST (`v1beta generateContent`, yalnızca `x-goog-api-key`); `AQ.` auth key'leriyle
  uyumlu. Eski istemcinin koyduğu soğuma kilidi ilk çalışmada bir kez kendiliğinden temizlenir. Alarm, Google'ın hata
  kodunu (anahtarsız) gösterir.
- **Otomatik haber görselleri:** yayından önce doğrulanan kaynak sayfasının `og:image` görseli (yoksa RSS
  `media:content`/enclosure) haberle kaydedilir. Görsel yalnızca kaynağın alan adından veya bilinen yayıncı
  CDN'lerinden kabul edilir; topluluk kaynaklarından alınmaz; indirilmez, kaynağa atıfla bağlantı olarak gösterilir.
  Telegram gönderisi kaynak sayfasının büyük önizleme görseliyle (metnin üstünde) gider.
- **Gemini 404 (16 Kasım 13:31 çalışması):** anahtar artık kabul ediliyor, ama `GEMINI_MODEL` secret'ındaki model bu
  anahtar için yok (HTTP 404 NOT_FOUND). Bot artık 404'te bir kez `models.list` ile erişilebilir modelleri okuyup
  ücretsiz katmandaki bir Flash modeline (asla Pro) geçiyor ve yönetici alarmında hangi modeli kullandığını yazıyor.
  Kalıcı çözüm: `GEMINI_MODEL` secret'ını alarmda yazan model adıyla güncellemek.
- **Doğrulama:** `python tools/site_check.py` (Playwright: 390/820/1440 × yalnız gerçek/varsayılan, bölge tıklama,
  çekmeceler, sıfır JS hatası).

## 4. Kurulan Tüm Skill'ler ve Arena Tartışmasında Çözülen Kritik Açıklar

### 4.1 Skill'ler (`.claude/skills/`, 15 adet — doğrulama: `SKILL_AUDIT_REPORT.md`)

| Skill | Görev |
|---|---|
| `security-auditor` | Secret sızıntısı, SSRF, eval/exec, injection taraması |
| `cost-guard` | Ücretsiz kota, limitler, ücretli modele geçiş yasağı |
| `architect-verifier` | Modül sınırları (14 modül tablosu), atomik yazım, deterministik karar |
| `python-tdd-runner` | pytest + mypy + ruff; 14 kabul testi ve Faz 2/Arena test haritası |
| `rss-integrity-checker` | Ayrıştırma, canonical URL, kaynak sınıfı, resmî kaynak kuralları |
| `telegram-api-guard` | Bot API sınırları, idempotency, 4096 sınırı, özet/alarm tekilleştirme |
| `gemini-schema-enforcer` | Structured Outputs, `CHECKS` doğrulama zinciri |
| `night-shift-supervisor` | Gece vardiyası sırası ve sınırları |
| **`token-budget-guardian`** (yeni) | Tek okuma, hedefli düzenleme, kısa çıktı, en fazla 2 deneme, alt ajan yok |
| **`arena-adversarial-review`** (yeni) | 4 rollü tur protokolü (saldırı → FAIL testi → yama → kayıt) |
| **`atomic-json-recovery`** (yeni) | Atomik yazım, şema doğrulama, `.lastgood` kurtarma, güvenli mod |
| **`rss-anti-poisoning`** (yeni) | 7 katmanlı zehirli içerik savunması ve saldırı yükü kütüphanesi |
| **`official-source-verifier`** (yeni) | RESMÎ etiketin üç koşulu, Google News ve HTML kuralları |
| **`event-clustering-calibrator`** (yeni) | Eşik ve ağırlık kalibrasyon prosedürü |
| **`static-site-guardian`** (Aşama 4) | Site ve besleme güvenliği: beyaz liste, XSS, CSP, gizli veri, yalnızca yayınlanmış haber |

> Not: Roller ayrı alt ajanlar olarak değil, token tasarrufu için tek bağlamda sırayla oynandı (`token-budget-guardian` kuralı). `/doctor`, `/skill-doctor`, `/code-review`, `/verify` komutları bu oturumda yoktu. Eşdeğerleri elle yapıldı: frontmatter doğrulama betiği, mypy, ruff, mutasyon kontrolü.

### 4.2 Arena: 6 tur, 25 açık (hepsi FAIL → PASS) — Tur 6 için bkz. 3b

En kritik 10 açık:

| # | Rol | Açık | Etki (yama öncesi) |
|---|---|---|---|
| 1.1 | Red | Reddit metni aynı kümedeki medya haberinin istemine ve kaynak satırına karışıyordu | Doğrulanmamış iddia, TEK/ÇOKLU KAYNAK rozetli habere sızabiliyordu |
| 1.2 | Red | Kiril homoglif ile enjeksiyon dedektörü atlatılıyordu | Gizli talimat modele ulaşıyordu |
| 2.1 | Red | Çıplak `t.me/…`, `www.…`, `@kanal` engellenmiyordu | Telegram bunları otomatik bağlantıya çevirir: spam/oltalama bağlantısı kanala çıkabiliyordu |
| 3.1–3.2 | Red | Geçerli JSON ama şekli bozuk state/history çöküşe yol açıyordu | Bot her çalışmada çıkış 3 veriyor, yani fiilen ölüyordu |
| 3.3 | SRE | Toplam çalışma süresi sınırı yoktu | 15 dakikalık iş sınırı aşılıp tur yarıda kesilebiliyordu |
| 4.1 | SRE | State her çalışmada yazılıyordu | Boşta günde ~72 commit, repo şişmesi (yamadan sonra ~24) |
| 5.2 | SRE | Resmî bağlantılar her 20 dakikada yeniden doğrulanıyordu | Rockstar ve Google'a gereksiz istek, 429 ve engellenme riski |
| 2.2 | SRE | `retry_after=3600` için 3 × 60 sn boşuna bekleniyordu | Actions süresi israfı, flood kısıtının uzaması |
| 4.2 | Editör | Doğrulanmamış haber özeti iddiayı kaynağa atfetmiyordu | Okur tek kaynaklı iddiayı kesin bilgi sanıyordu |
| 2.4 | Editör | İddialarda soru başlığı (clickbait) serbestti | Betteridge tipi yanıltıcı başlık |

Diğer 9 açık (1.3 aday havuzu sınırı, 1.4 yanıltıcı "TOPLULUK" kategorisi, 2.3 emoji disiplini, 3.4 jenerik doğrulama notu, 4.3 kesinlik sözlüğü boşlukları, 5.1 kod çitli JSON, 5.3 dolgulu enjeksiyon, 5.4 eyleme dönük yönetici özeti) ve her birinin FAIL/PASS kanıtı: `ARENA_DEBATE_LOG.md`.

**Testlerin gerçekten bir şey yakaladığının kontrolü:** Arena'nın 5 ana savunması bilerek bozuldu: katman izolasyonu, bağlantı engeli, şema doğrulama, süre sınırı ve tekrar doğrulama önleme. Her birinde ilgili test başarısız oldu.

---

## 5. Test Çıktısı

```
$ python -m pytest -v
tests/test_analyzer.py      6    tests/test_injection.py      16
tests/test_arena.py        25    tests/test_processor.py      11
tests/test_clustering.py   15    tests/test_publisher.py      15
tests/test_collector.py    11    tests/test_resilience.py     22
tests/test_simulator.py     2    tests/test_site_exporter.py  31
tests/test_storage.py       6
============================== 160 passed ==============================
$ mypy bot                          → Success: no issues found in 15 source files
$ ruff check bot tests tools        → All checks passed!
$ python tools/skill_audit.py       → 15/15 skill tüm denetimlerden geçti
$ chrome --headless --dump-dom docs/index.html → 11 kart + 1 manşet JS ile çizildi
```

14 kabul testinin eşlemesi değişmedi (`.claude/skills/python-tdd-runner/SKILL.md`).

---

## 6. Açık Riskler

1. **Resmî kaynaklar canlı denenmedi.** Rockstar Newswire sayfası istemci tarafında çiziliyorsa HTML ayrıştırıcı boş döner; kaynak durumuna `warning` yazılır. Google News'in imzalı bağlantıları yönlendirmeyle çözülemezse öğe atılır. Bu durumda resmî haberler yalnızca ÇOKLU KAYNAK olarak gelir. Bu bilinçli bir güvenlik tercihi.
2. **RSS adresleri ve `google-genai` SDK canlı denenmedi** (paket kurulumu ve ağ kapalıydı).
3. **Doğrulama katmanı bilinçli olarak temkinli.** Atıf zorunluluğu, sayı/ay kontrolü ve soru başlığı yasağı bazı geçerli haberleri incelemeye alabilir. İlk hafta özetteki "İncelemeye takılan" sayısını izle.
4. **Kümeleme eşiği** 9 etiketli çiftle kalibre edildi. Gerçek akışta yanlış birleşme veya ayrılma görürsen örneği `tests/test_clustering.py`'ye ekleyip `event-clustering-calibrator` adımlarını izle.
5. **Site demo verisiyle teslim edildi.** İlk bot çalışmasında `feed.json` gerçek haberlerle değişir. O ana kadar sitede "Örnek veri" rozeti görünür.
6. **`.github` ve `.claude` klasörleri bilgisayarına kendi adlarıyla yazılamadı** (uzak araç bu adları korumaya alıyor). Doğru hâlleri bundle'da. Açık klasörde `_dot_github/` ve `_dot_claude/` olarak duruyorlar.

**İNSAN MÜDAHALESİ GEREKLİ** başlığı altında kayıt yok: 2 denemede çözülemeyen hata olmadı.

---

## 7. Sabah Senin Yapacakların

1. **GitHub'a yükle.** "Haber Sitesi" klasöründe terminal aç:
   ```bash
   git clone gta6-autonomous-telegram.bundle gta6-repo
   cd gta6-repo
   ```
   GitHub'da yeni bir **public** repo oluştur (README eklemeden), sonra:
   ```bash
   git remote set-url origin https://github.com/<kullanıcı-adın>/<repo-adı>.git
   git push -u origin main
   ```
   **Bundle yolunu kullan:** `.github/` ve `.claude/` klasörleri yalnızca bundle'da doğru adlarıyla var. Klasörü elle yüklersen önce `_dot_github` → `.github` ve `_dot_claude` → `.claude` olarak yeniden adlandır. Workflow `.github/workflows/run.yml` yolunda olmazsa bot hiç çalışmaz.
2. **BotFather:** Telegram'da @BotFather → `/newbot`. Token'ı **yalnızca** 5. adımda GitHub Secrets'a yapıştır.
3. **Kanal:** Herkese açık kanal oluştur, botu **yönetici** yap ve "Mesaj gönderme" iznini ver. İstersen özet ve uyarılar için ayrı bir özel grup kur, botu oraya da ekle.
4. **Gemini:** [Google AI Studio](https://aistudio.google.com)'da API anahtarı oluştur. **Billing'i açma.** Ücretsiz katmandaki **stable** bir Flash modelinin kimliğini not al.
5. **GitHub → Settings → Secrets and variables → Actions:**
   - **Secrets:** `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - **Variables:** `GEMINI_MODEL`, isteğe bağlı `ADMIN_CHAT_ID`
6. **İlk çalıştırma:** Actions → `gta6-bot-run` → **Run workflow**. Log'un sonundaki JSON özette şunlara bak:
   - `sources_ok` değeri
   - `data/state.json` → `source_status` içinde `rockstar_newswire_html`, `rockstar_google_news`, `take_two_*` satırları: `relevant` > 0 mı, yoksa `warning` mı var?
   - `gemini_errors` 0 olmalı
   - `error_classes` içinde `AUTH_PERMISSION` olmamalı
7. **Görünüm:** `docs/index.html` dosyasını tarayıcıda aç (12 haberlik demo site). Üst menüdeki "Telegram önizleme" sayfasında beş senaryonun telefon maketi var. Kanaldaki ilk gönderiyle karşılaştır. Botu durdurmak gerekirse `config/settings.json` → `"paused": true` yapıp commit et.
8. **Haber sitesini yayına al (tek seferlik):** Repo → **Settings → Pages → Source: "Deploy from a branch" → `main` / `/docs` → Save.** Kanal herkese açıksa `config/settings.json` → `"public_channel_username"` alanına kanal adını yaz (site "Telegram'da aç" düğmesini gönderiye bağlar).

---

## 8. İlk 7 Gün Operasyon Planı

| Gün | Kontrol |
|---|---|
| **Her gün (09:00 ve 21:00 TSİ civarı)** | Yönetici özeti: bugünkü yayınlar (başlık listesiyle), incelemeye takılanlar, belirsiz gönderimler, hata sınıfları |
| **1. gün** | Resmî kaynak satırlarının durumu. Bir kaynak hep boş veya hatalıysa `enabled: false` yap. |
| **2–3. gün (çıkış öncesi)** | Haber yoğunluğu artacak; `max_daily_posts: 8` yeterli mi değerlendir. Yanlış etiket görürsen hemen `paused: true` yap. |
| **19 Kasım** | En yoğun gün. Gemini 429 alırsa bot 60 dakika bekler; bu bir hata değil. Çalışma süresi sınırı (10 dk) devreye girerse özette "çalışma süresi sınırı" notu çıkar. |
| **5–7. gün** | Reaksiyon akışı doluyor mu (`reaction_snapshots`)? Analiz her grupta 5 gönderi birikene kadar "YETERSİZ VERİ" der; bu beklenen davranış. |

**Müdahale gerektiren durumlar:** 401/403 uyarısı, "otomatik kurtarıldı" uyarısı (nedenini incele), güvenli mod uyarısı, Gemini modelinin kullanımdan kalkması, 60 günlük hareketsizlik.
