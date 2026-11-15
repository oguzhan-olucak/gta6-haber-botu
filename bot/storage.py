"""Atomik JSON okuma/yazma, bozuk dosya koruması, yedekleme ve basit dosya kilidi.

Kurallar:
- Yazma her zaman aynı dizinde geçici dosya + os.replace ile atomiktir.
- Bozuk (parse edilemeyen veya kök tipi yanlış) dosya ASLA ezilmez. Bir kopyası
  ``<ad>.corrupt.<timestamp>.bak`` olarak alınır ve CorruptDataError fırlatılır.
  Çağıran taraf güvenli moda geçer; bozuk dosya insan düzeltene kadar yerinde kalır,
  böylece sonraki çalışmalar "boş geçmiş" sanıp aynı haberleri tekrar yayınlamaz.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class CorruptDataError(Exception):
    """Bir veri dosyası okunamadı; yedeği alındı, dosya yerinde bırakıldı."""

    def __init__(self, path: Path, backup: Path | None, reason: str):
        self.path = Path(path)
        self.backup = backup
        self.reason = reason
        super().__init__(f"Bozuk veri dosyası: {self.path.name} ({reason})")


class LockError(Exception):
    """Başka bir çalışma kilidi tutuyor."""
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_corrupt(path: Path) -> Path | None:
    """Bozuk dosyanın zaman damgalı .corrupt.<ts>.bak kopyasını alır."""
    path = Path(path)
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.corrupt.{_utc_stamp()}.bak")
    n = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.corrupt.{_utc_stamp()}.{n}.bak")
        n += 1
    shutil.copy2(path, backup)
    return backup


def read_json(path: Path | str, default_factory: Callable[[], Any], expect_type: type = dict) -> Any:
    """JSON dosyasını oku. Yoksa ``default_factory()`` döner.

    Boş dosya, bozuk JSON veya beklenmeyen kök tipi -> yedek + CorruptDataError.
    """
    path = Path(path)
    if not path.exists():
        return default_factory()
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        backup = backup_corrupt(path)
        raise CorruptDataError(path, backup, f"okunamadı: {type(exc).__name__}") from None
    if not raw.strip():
        backup = backup_corrupt(path)
        raise CorruptDataError(path, backup, "boş dosya")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        backup = backup_corrupt(path)
        raise CorruptDataError(path, backup, f"geçersiz JSON (satır {exc.lineno})") from None
    if not isinstance(data, expect_type):
        backup = backup_corrupt(path)
        raise CorruptDataError(path, backup, f"kök tipi {type(data).__name__}, beklenen {expect_type.__name__}")
    return data


def lastgood_path(path: Path | str) -> Path:
    """Son sağlam kopyanın yolu: ``state.json`` → ``state.lastgood.json``."""
    path = Path(path)
    return path.with_name(f"{path.stem}.lastgood{path.suffix}")


def _dump(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _atomic_write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path: Path | str, data: Any, *, keep_last_good: bool = False) -> None:
    """Geçici dosya + fsync + os.replace ile atomik yazım. ``keep_last_good`` ise aynı içerik
    ``<ad>.lastgood.json`` dosyasına da atomik yazılır (otomatik kurtarma kaynağı)."""
    path = Path(path)
    payload = _dump(data)
    _atomic_write_text(path, payload)
    if keep_last_good:
        _atomic_write_text(lastgood_path(path), payload)


def write_if_changed(path: Path | str, data: Any, *, keep_last_good: bool = False) -> bool:
    """Yalnızca içerik değiştiyse yaz (gereksiz git commit'lerini önler).
    ``keep_last_good`` ise son sağlam kopya eksik/farklı olduğunda onu da günceller."""
    path = Path(path)
    new_payload = _dump(data)
    changed = True
    if path.exists():
        try:
            changed = path.read_text(encoding="utf-8") != new_payload
        except (OSError, UnicodeDecodeError):
            changed = True
    if changed:
        _atomic_write_text(path, new_payload)
    if keep_last_good:
        lg = lastgood_path(path)
        try:
            same = lg.exists() and lg.read_text(encoding="utf-8") == new_payload
        except (OSError, UnicodeDecodeError):
            same = False
        if not same:
            _atomic_write_text(lg, new_payload)
    return changed


def read_json_recovering(path: Path | str, default_factory: Callable[[], Any],
                         expect_type: type = dict) -> tuple[Any, CorruptDataError | None]:
    """``read_json`` gibi; ana dosya bozuksa ``<ad>.lastgood.json`` sağlamsa ondan **otomatik
    kurtarır**: bozuk dosyanın yedeği alınır, ana dosya son sağlam içerikle atomik olarak
    yeniden yazılır. Dönüş: (veri, kurtarıldıysa orijinal hata, değilse None).
    Son sağlam kopya da yoksa/bozuksa orijinal ``CorruptDataError`` yükseltilir."""
    path = Path(path)
    try:
        return read_json(path, default_factory, expect_type), None
    except CorruptDataError as exc:
        lg = lastgood_path(path)
        if not lg.exists():
            raise
        try:
            data = read_json(lg, default_factory, expect_type)
        except CorruptDataError:
            raise exc from None
        _atomic_write_text(path, _dump(data))
        return data, exc


class FileLock:
    """O_EXCL tabanlı basit kilit. GitHub Actions'ta asıl koruma ``concurrency``'dir;
    bu kilit yerel elle çalıştırmalarda çakışmayı önler."""

    def __init__(self, path: Path | str, stale_after_seconds: int = 1800):
        self.path = Path(path)
        self.stale_after = stale_after_seconds
        self._held = False

    def acquire(self) -> None:
        """Kilidi alır; eski (bayat) kilit dosyasını temizler."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as fh:
                    fh.write(str(int(time.time())))
                self._held = True
                return
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_after:
                    self.path.unlink(missing_ok=True)
                    continue
                raise LockError("Başka bir çalışma sürüyor (kilit dosyası mevcut).") from None
        raise LockError("Kilit alınamadı.")

    def release(self) -> None:
        """Kilidi bırakır."""
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ---- Varsayılan veri şekilleri -------------------------------------------------

def default_state() -> dict:
    """Boş state.json şekli."""
    return {
        "schema_version": 1,
        "last_run_at": None,
        "last_successful_fetch_at": None,
        "first_run_at": None,
        "telegram_update_offset": None,
        "reaction_pipeline_verified": False,
        "seen_items": {},
        "digests_sent": [],
        "alerts_last_sent": {},
        "gemini_quota_blocked_until": None,
        "source_status": {},
        "run_log": [],
    }


def default_history() -> dict:
    """Boş history.json şekli."""
    return {"schema_version": 1, "posts": []}


def default_insights() -> dict:
    """Nötr insights.json şekli."""
    return {"schema_version": 1, "status": "YETERSİZ VERİ", "prompt_hints": {}}
