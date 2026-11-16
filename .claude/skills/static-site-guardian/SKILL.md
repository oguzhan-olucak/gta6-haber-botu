---
name: static-site-guardian
description: docs/ altındaki GitHub Pages haber sitesinin ve feed.json köprüsünün güvenliğini, gizlilik ve şema kurallarını denetler (XSS, CSP, gizli veri sızıntısı, yalnızca yayınlanmış haber). bot/site_exporter.py, docs/assets/app.js veya docs/index.html değiştiğinde kullan.
---
# static-site-guardian

## Kurallar
1. **Beyaz liste dışa aktarım:** `feed.json` yalnızca `FeedItem` alanlarını içerir (ek alan = şema hatası). `chat_id`, `content_hashes`, `publish_error`, orijinal kaynak başlıkları, state iç alanları ve secret'lar asla yazılmaz.
2. **Yalnızca `PUBLISHED`:** incelemeye takılan, reddedilen ya da belirsiz gönderimler sitede görünmez.
3. **Metin temizliği:** `clean_text` → HTML/varlık/görünmez karakter temizliği ve uzunluk sınırı. Kalan `<` ve `>` karakterleri `‹ ›` olur (çift kodlanmış HTML'ye karşı).
4. **Bağlantılar:** yalnızca `https://` ve canonical (`safe_url`). İstemcide `safeHttps()` ile ikinci kez denetlenir.
5. **İstemci:** veri yalnızca `textContent` ile basılır. `app.js` içinde `innerHTML`, `eval`, `new Function` ve `document.write` yok.
6. **CSP:** `index.html` meta CSP'si `script-src 'self'` (satır içi betik yok), `object-src 'none'`, `base-uri 'none'`.
7. **feed.js:** `<`, `>`, `&` ve U+2028/2029 kaçırılır; `</script>` kırılması olmaz.
8. **Ölçüm dürüstlüğü:** görüntülenme/iletilme dışa aktarılmaz. Reaksiyon yalnızca ölçülmüşse verilir (çıkarsanan 0 gösterilmez).
10. **Haber görselleri:** yalnızca kaynağın kendi paylaşım görseli (og:image / RSS media). Bot görseli indirmez ya da
   yeniden barındırmaz; `collector.safe_image_url` ile yalnızca https, kimlik bilgisi/port içermeyen ve kaynağın alan adı
   veya `image_host_allowlist` (yayıncı CDN'leri) ana makinesindeki adresler kabul edilir. Topluluk kaynaklarından görsel
   alınmaz. Sitede `referrerpolicy="no-referrer"`, `loading="lazy"`, "Görsel: <kaynak>" atfı; yüklenemezse SVG kapak.
   CSP `img-src 'self' data: https:` (betik kuralları değişmez).
9. **Telegram bağlantısı:** yalnızca `public_channel_username` ayarlıysa `https://t.me/<ad>/<id>`; sayısal chat_id asla kullanılmaz.

## Ne zaman tetiklenir
Site, exporter veya demo beslemesi değiştiğinde; yayına almadan önce.

## Komutlar
```bash
python -m pytest -q tests/test_site_exporter.py
python tools/skill_audit.py --skill static-site-guardian
google-chrome --headless=new --dump-dom "file://$PWD/docs/index.html" | grep -c 'class="card '   # JS ile çizilen kart sayısı
```

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill static-site-guardian
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
