---
name: vice-city-design-system
description: docs/ sitesinin "Leonida Night" tasarım sistemi — renk, tipografi, cam yüzeyler, güven rozeti renkleri ve kırılımlar. docs/assets/style.css veya yeni bir site bileşeni tasarlanırken/değiştirilirken kullan; token dışı renk ya da yazı tipi eklemeden önce bu kurallara bak.
---
# vice-city-design-system

Kimlik: Leonida komuta merkezi — gece çöken bir eyaletin taktik haritası. Tek cesur öğe **etkileşimli Leonida
haritasıdır** (neon kıyı çizgisi, nabız atan iğneler, projektör hüzmeleri, tarama çizgisi dokusu); geri kalan her şey
sakin ve disiplinli kalır. Amblem ve harita özgün çizimdir; resmî GTA VI logosu veya oyun haritası kopyalanmaz.

## Token'lar (`docs/assets/style.css` → `:root`)
| Token | Değer | Rol |
|---|---|---|
| `--night` | `#060914` | sayfa zemini |
| `--navy` / `--indigo` / `--plum` | `#0B1230` / `#1B1450` / `#3A1150` | gökyüzü geçişi |
| `--sunset` | `#FF6B2C` | birincil vurgu (düğme degradesi) |
| `--pink` | `#FF2E88` | seçili sekme, iddia rozeti |
| `--gold` | `#FFC94A` | resmî rozet, geri sayım rakamları |
| `--mint` | `#35F0E0` | canlı durum, odak halkası, çoklu kaynak |
| `--violet` | `#A99BFF` | tek kaynak |

Güven renkleri sabittir ve başka anlamda kullanılmaz: resmî = altın, çoklu = nane, tek = mor, topluluk/sızıntı = pembe.

## Tipografi
- Başlık: **Anton** (`--display`; manşet `clamp(52px, 6.4vw, 104px)`), ara başlık/sekme: **Oswald** (`--sub`).
- Gövde: **Plus Jakarta Sans** (`--body`) 16px / 1.6; satır uzunluğu ≤ 75 karakter.
- Sayaç, koordinat ve meta verisi: **JetBrains Mono** (`--mono`).
- Büyük harf yalnızca Oswald ara başlıklarda; Türkçe metin `lang="tr"` ile (İ/ı doğru). Özel adlar (Vice City) büyük harfe çevrilmez.

## Yüzeyler
- Cam: `.glass` → yarı saydam lacivert + `backdrop-filter: saturate(140%) blur(18px)` + 1px açık kenar.
- Kart: bölgeye özgü SVG kapak (`#cover-<bölge>` sembolü), güven renginde neon kenar parıltısı, ince işaretçilerde
  fare açısına göre 3B eğim (±4–5°). Başka efekt yok.
- Bölge renkleri: Vice City pembe · Leonida Keys nane · Grassrivers yeşil `#6BE38E` · Port Gellhorn mor · Mount Kalaga altın.
- Yarıçap hiyerarşisi: çip 999px · kart 16px · panel/modal 24px.

## Kırılımlar
`≤760px` tek sütun, süzgeçler yatay kaydırma · `≤1100px` manşet tek sütun, kart 2'li · masaüstü 12 sütun ızgara.
`prefers-reduced-motion` tüm animasyonları kapatır. `[hidden]` her zaman `display:none !important`.

## Ne zaman tetiklenir
`docs/assets/style.css`, `docs/index.html` görsel yapısı veya yeni bir site bileşeni değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill vice-city-design-system
```
Denetleyici token'ların tanımlı olduğunu, `[hidden]` kuralını, reduced-motion bloğunu ve kırılımları doğrular.
