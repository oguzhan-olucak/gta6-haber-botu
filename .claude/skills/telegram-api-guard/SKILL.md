---
name: telegram-api-guard
description: Telegram Bot API kısıtlarını korur; views/forwards uydurulmaz, message_reaction_count idempotent işlenir, yönetici özeti spam yapmaz, sendMessage zaman aşımında tekrar gönderilmez. Telegram ile ilgili her değişiklikte kullan.
---
# telegram-api-guard

Doğrulanmış gerçekler (core.telegram.org/bots/api, Bot API 10.4, 9 Kasım 2026):
- Bot API'de kanal gönderisi görüntülenme/iletilme sayısı alınamaz → `metrics.views/forwards = "unavailable"` sabit kalır.
- `message_reaction_count`: bot kanal yöneticisi olmalı ve `allowed_updates` içinde açıkça istenmeli; gruplanır, birkaç dakika gecikebilir; geriye dönük sorgulanamaz.
- `getUpdates` webhook ayarlıyken çalışmaz (409) → alarm.

Kurallar:
- `allowed_updates` yalnızca `["message_reaction_count"]`. Kullanıcı bazlı `message_reaction` istenmez; kullanıcı ID saklanmaz.
- `sendMessage` için ReadTimeout/5xx = belirsiz → `UNCERTAIN`, yeniden gönderim yok.
- Özet anahtarı `YYYY-MM-DDTHH` ile `state.digests_sent`; alarm tekilleştirme `state.alerts_last_sent` (varsayılan 6 saat).
- Mesaj ≤ 4096 karakter, `parse_mode=HTML`, tüm dinamik metin `html.escape`.
