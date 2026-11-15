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
| `bot/collector.py` | RSS/Atom (defusedxml), URL canonicalization, alan adı eşleşmesi, atıf zinciri tespiti, SSRF korumalı URL doğrulama |
| `bot/processor.py` | Kümeleme, tekrar önleme, deterministik puanlama ve etiket, Gemini istemi ve çıktı doğrulama |
| `bot/publisher.py` | Mesaj şablonu, idempotent yayın, günlük limit, yönetici özeti, alarm tekilleştirme |
| `bot/analyzer.py` | Reaksiyon güncellemeleri, ölçüm durumu, kategori/başlık stili analizi |
| `bot/main.py` | Orkestrasyon ve JSON çalışma özeti |

## Yayın etiketleri

| Rozet | Etiket | Ne zaman | Varsayılan |
|---|---|---|---|
| 🟩 | RESMÎ AÇIKLAMA | Haber doğrudan `rockstargames.com` / `take2games.com` alan adında | Yayınlanır |
| 🟦 | ÇOKLU KAYNAK | En az 2 **bağımsız** köken (aynı ilk haberi kopyalayanlar ve aynı yayın grubu tek sayılır) | Yayınlanır |
| 🟨 | TEK KAYNAK | Tek güvenilir yayın organı | `allow_single_source_media` |
| 🟥 | SIZINTI İDDİASI | Başlıkta leak/rumor/insider vb. | `allow_community_rumors` (kapalı) |
| 🟧 | TOPLULUK İDDİASI | Yalnızca Reddit/topluluk | `allow_community_rumors` (kapalı) |

Etiketi model değil Python belirler. Model "resmî" dese bile resmî alan adı yoksa gönderi incelemeye takılır. Şablonların görünümü: `docs/message_preview.html` (`python tools/render_preview.py` ile yeniden üretilir).

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

## Kill switch

`config/settings.json` içinde `"paused": true` yapıp commit edin. Bu durumda toplama, Gemini çağrısı ve kanal yayını yapılmaz. Reaksiyon ölçümü ve yönetici özeti sürer. Açmak için tekrar `false` yapın.

## Zamanlama ve sınırlar

- Workflow `7,27,47 * * * *` ile çalışır (20 dakikada bir, saat başı yoğunluğundan kaçınır). GitHub `schedule` olayı **en iyi çaba** ile çalışır: çalışmalar gecikebilir veya atlanabilir; en kısa desteklenen aralık 5 dakikadır. Kaçırılan aralık sorun yaratmaz, çünkü bot son `max_item_age_hours` (48 saat) içindeki her öğeye bakar ve `seen_items` ile tekrarı önler.
- Zamanlanmış workflow'lar yalnızca varsayılan dalda (`main`) çalışır.
- **60 gün kuralı:** Public repoda 60 gün boyunca hiç etkinlik olmazsa GitHub zamanlanmış workflow'u devre dışı bırakır. Bot her çalışmada `data/state.json`'u commit ettiği için normalde repo etkin kalır. Workflow yine de devre dışı kalırsa Actions sekmesindeki sarı uyarıdan **Enable workflow** ile yeniden açın.
- Gemini 429 alırsa çağrılar `gemini_quota_cooldown_minutes` boyunca durur. Başka bir modele veya ücretli katmana **asla** geçilmez.
- Günlük gönderi sınırı, kayan 24 saatlik pencerede `max_daily_posts` değeridir.

## Hata ve güvenli mod

| Durum | Davranış |
|---|---|
| Bir RSS kaynağı bozuk/erişilemez | Yalnızca o kaynak atlanır, `source_status` güncellenir |
| 24 saat hiç veri yok / kalıcı 401-403 | Yönetici uyarısı (aynı uyarı 6 saatte bir) |
| `history.json` bozuk | Yedek alınır, dosya **ezilmez**, yayın ve Gemini durur, uyarı gönderilir, çıkış kodu 2 |
| `state.json` bozuk | Yedek alınır, hiçbir şey yazılmaz, çıkış kodu 2 (GitHub başarısız çalışma e-postası) |
| `insights.json` bozuk | Nötr varsayılan istemle devam edilir |
| Telegram zaman aşımı | Gönderi `UNCERTAIN` olarak işaretlenir ve **yeniden gönderilmez** (mükerrer yayın yerine olası tek kayıp) |

## Yerel geliştirme

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

Testler gerçek ağa çıkmaz (`tests/conftest.py` engeller) ve yalnızca `DUMMY_..._DO_NOT_USE` sahte sabitlerini kullanır.

## Telif

Bot yalnızca başlık, kaynak URL'si, yayın zamanı ve kısa olgusal özet kullanır. Kaynak metin veya görsel kopyalanmaz ve her gönderide orijinal kaynağa bağlantı verilir.
