---
name: atomic-json-recovery
description: data/*.json dosyalarının atomik yazımı, bozulma tespiti, .lastgood otomatik kurtarma ve güvenli mod davranışını denetler ve test eder. storage.py veya veri şeması değiştiğinde kullan.
---
# atomic-json-recovery

## Sözleşme (bot/storage.py)
- Yazım: `tempfile.mkstemp` (aynı dizin) → `fsync` → `os.replace`. Başka yazma yolu yok.
- `write_if_changed(path, data, keep_last_good=True)`: state/history için her başarılı yazımda `<ad>.lastgood.json` güncellenir.
- Okuma: `read_json_recovering` → ana dosya bozuksa `.corrupt.<ts>.bak` yedeği alınır, `.lastgood` sağlamsa ana dosya ondan atomik olarak yeniden yazılır; ikisi de bozuksa `CorruptDataError` → güvenli mod (yayın yok).
- Yapısal doğrulama: kök tipi + üst düzey alan tipleri (`seen_items: dict`, `posts: list[dict]` ...) — JSON geçerli ama şekli bozuksa da "bozuk" sayılır.

## Testler
`tests/test_storage.py`, `tests/test_resilience.py::test_half_written_*`, `test_end_to_end_corrupt_*`, `tests/test_arena.py` (şema zehirlenmesi).

## Elle kurtarma
`git log -- data/history.json` → son sağlam commit'ten `git checkout <sha> -- data/history.json`.

## Ne zaman tetiklenir
storage.py veya data/*.json şeması değiştiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill atomic-json-recovery
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
