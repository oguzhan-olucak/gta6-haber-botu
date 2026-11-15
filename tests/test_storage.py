import json

import pytest

from bot.storage import (CorruptDataError, FileLock, LockError, default_state, read_json,
                         write_if_changed, write_json_atomic)


def test_atomic_write_and_read_roundtrip(tmp_path):
    p = tmp_path / "data" / "state.json"
    write_json_atomic(p, {"a": 1, "ç": "ğüş"})
    assert read_json(p, dict) == {"a": 1, "ç": "ğüş"}
    # geçici dosya artığı kalmamalı
    assert [f.name for f in p.parent.iterdir()] == ["state.json"]


def test_missing_file_returns_default(tmp_path):
    assert read_json(tmp_path / "yok.json", default_state)["seen_items"] == {}


def test_corrupt_file_is_backed_up_and_not_overwritten(tmp_path):
    p = tmp_path / "history.json"
    p.write_text('{"posts": [ BOZUK', encoding="utf-8")
    with pytest.raises(CorruptDataError) as ei:
        read_json(p, dict)
    assert ei.value.backup is not None and ei.value.backup.exists()
    assert ".corrupt." in ei.value.backup.name and ei.value.backup.name.endswith(".bak")
    # orijinal bozuk dosya yerinde ve değişmemiş
    assert p.read_text(encoding="utf-8") == '{"posts": [ BOZUK'


def test_wrong_root_type_is_corrupt(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(CorruptDataError):
        read_json(p, dict)


def test_write_if_changed_skips_identical(tmp_path):
    p = tmp_path / "x.json"
    assert write_if_changed(p, {"k": 1}) is True
    assert write_if_changed(p, {"k": 1}) is False
    assert write_if_changed(p, {"k": 2}) is True
    assert json.loads(p.read_text())["k"] == 2


def test_file_lock_blocks_second_holder(tmp_path):
    lock_path = tmp_path / ".run.lock"
    with FileLock(lock_path):
        with pytest.raises(LockError):
            FileLock(lock_path).acquire()
    assert not lock_path.exists()
