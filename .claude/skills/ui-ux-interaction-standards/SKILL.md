---
name: ui-ux-interaction-standards
description: docs/ sitesindeki etkileşim kuralları — süzgeç/sekme/arama anında çalışır, çekmece ve modallar <dialog> ile erişilebilir açılır, boş durum yönlendirir, gerçek veri örnek bültenin önündedir. docs/assets/app.js'e bileşen eklerken veya değiştirirken kullan.
---
# ui-ux-interaction-standards

## Kurallar
1. **Gerçek veri önceliklidir.** `feed.json`'da en az bir haber varsa örnek bülten (`data/demo-feed.js`) hiç gösterilmez;
   kullanıcı anahtarı açık bıraksa bile. Örnek veri yalnızca istek üzerine tembel yüklenir ve şeritte "Örnek bülten" yazar.
2. **Boş durum bir davettir.** Boş akışta manşet "İlk doğrulanmış haber yolda" der, iskelet kartlar ve
   "Örnek bülten önizlemesini göster" anahtarı görünür. Hata durumunda ne olduğu ve ne yapılacağı yazılır.
3. **Anında süzgeç.** Güven çipleri (`aria-pressed`), kategori sekmeleri (`role=tab`, `aria-selected`) ve arama
   (Türkçe harf katlamalı, çok kelimeli VE) her tuşta yeniden çizer; gecikme/debounce yok. `/` aramaya odaklar, `Esc` temizler.
4. **Diyaloglar** `<dialog>.showModal()` ile açılır (odak tuzağı + Esc tarayıcıdan); arka plana tıklama kapatır.
   Derin bağlantılar: `#haber-<id>`, `#telegram`, `#yontem`.
5. **Kartlar** tam güven rozeti adı, okuma süresi, en fazla 3 kaynak çipi (alan adıyla önizleme), Telegram'da paylaş ve
   bağlantı kopyala düğmesi taşır. Tüm kart tıklanabilir ama iç bağlantılar kendi işini yapar.
6. **Güvenlik:** veri yalnızca `textContent` ile basılır; bağlantılar `safeHttps()` ile süzülür; `localStorage` erişimi try/catch içindedir.
7. **Eylem adı tutarlılığı:** "Bağlantıyı kopyala" → bildirim "Bağlantı kopyalandı".

## Ne zaman tetiklenir
`docs/assets/app.js` veya `docs/index.html` etkileşim yapısı değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill ui-ux-interaction-standards
```
Denetleyici app.js'te tembel örnek yüklemeyi, gerçek-veri önceliğini, dialog kullanımını ve index.html kimliklerini doğrular.
