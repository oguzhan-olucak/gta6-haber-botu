---
name: security-auditor
description: GTA6 bot kodunda, testlerde ve GitHub Actions dosyalarında secret sızıntısı, SSRF, güvensiz eval/exec ve RSS kaynaklı prompt injection denetimi. Güvenlik incelemesi, commit öncesi kontrol veya "güvenlik denetimi" istendiğinde kullan.
---
# security-auditor

Yalnızca proje klasörü içinde çalış. Gerçek secret okuma; `.env`, `~/.ssh`, `~/.aws` dosyalarına dokunma.

## Kontrol listesi
1. Secret sızıntısı
   - `grep -rnE "AIza[0-9A-Za-z_-]{20,}|[0-9]{6,12}:[A-Za-z0-9_-]{30,}" --exclude-dir=.git .` sonucu boş olmalı (testlerdeki sahte sabitler `DUMMY_..._DO_NOT_USE` biçimindedir).
   - Secret'lar yalnızca `bot/config.py::load_secrets` ile `os.environ`'dan okunur; başka yerde `os.environ[...TOKEN/KEY]` olmamalı.
   - Tüm loglar `gta6bot` logger'ı ve `RedactingFilter` üzerinden geçer; `print` yalnızca `main()` içinde `redact(...)` ile.
   - `telegram_client.py` istisnalarında `from None` kullanılır (URL'de token taşıyan `requests` hatası zincire eklenmez).
2. SSRF: kaynak URL doğrulaması `collector.verify_source_url` ile — yalnızca https, allowlist alan adı, her yönlendirme adımında yeniden kontrol, özel/iç IP reddi, canonical bağlantı kontrolü.
3. `grep -rnE "\beval\(|\bexec\(|pickle|shell=True|verify=False" bot/` boş olmalı.
4. XML: yalnızca `defusedxml` ile ayrıştırma (`forbid_dtd=True`).
5. Prompt injection: kaynak verisi yalnızca `<untrusted_source_data>` içinde, `<`/`>` kaçırılmış; sistem talimatı bu veriyi talimat saymamayı söyler; çıktı `validate_generated` ile deterministik denetlenir.
6. Workflow: tetikleyiciler yalnızca `schedule` + `workflow_dispatch`; `permissions: contents: write`; secret'lar yalnızca "Botu çalıştır" adımında.

Bulguları `NIGHT_PROGRESS.md`'ye tek satırlık sonuçla yaz.

## Ne zaman tetiklenir
Her commit öncesi; bot/, tools/ veya workflow değiştiğinde; yeni bağımlılık eklendiğinde.

## Otomatik doğrulama
```bash
python tools/skill_audit.py --skill security-auditor
```
Denetleyici bu skill'in kurallarını koda karşı çalıştırır; sonuç `SKILL_AUDIT_REPORT.md` dosyasına yazılır.
