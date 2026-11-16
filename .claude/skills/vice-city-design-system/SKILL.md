---
name: vice-city-design-system
description: docs/ sitesinin "Leonida Night" tasarım sistemi — renk, tipografi, cam yüzeyler, güven rozeti renkleri ve kırılımlar. docs/assets/style.css veya yeni bir site bileşeni tasarlanırken/değiştirilirken kullan; token dışı renk ya da yazı tipi eklemeden önce bu kurallara bak.
---
# vice-city-design-system

Kimlik: Leonida'da gün batımından geceye geçiş. Tek cesur öğe **sinematik manşettir** (güneş, ızgara ufku, palmiye
silueti); geri kalan her şey sakin ve disiplinli kalır.

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
- Başlık: **Big Shoulders Display** 800–900 (manşet `clamp(40px, 5.6vw, 84px)`, satır yüksekliği .92).
- Gövde: **Instrument Sans** 400–700, 16px / 1.6; satır uzunluğu ≤ 75 karakter (`max-width: 60–70ch`).
- Tümü büyük harf etiket yok; Türkçe büyük harf gerekiyorsa `toLocaleUpperCase("tr")`.

## Yüzeyler
- Cam: `.glass` → yarı saydam lacivert + `backdrop-filter: saturate(140%) blur(18px)` + 1px açık kenar.
- Kart: üstte güven renginde 2px ışık çizgisi; hover'da 4px yükselme + degrade kenar (`::before`). Başka efekt yok.
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
