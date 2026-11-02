"""Tests for deleting old results (data retention)."""

import os
import time

import pytest

from risk_engine.cli import main
from risk_engine.retention import delete_folders, find_old_folders, keep_days


def _make(folder, name, age_days, now):
    d = folder / name
    d.mkdir(parents=True)
    f = d / "audit.json"
    f.write_text("{}")
    t = now - age_days * 86400
    os.utime(f, (t, t))
    os.utime(d, (t, t))
    return d


def test_finds_and_deletes_only_old_folders(tmp_path):
    now = time.time()
    old_run = _make(tmp_path, "20250101-old", 200, now)
    new_run = _make(tmp_path, "20261101-new", 5, now)
    (tmp_path / "uploads").mkdir()
    old_upload = _make(tmp_path / "uploads", "20250101-000000", 120, now)
    new_upload = _make(tmp_path / "uploads", "20261101-000000", 1, now)
    (tmp_path / ".gitkeep").write_text("")

    old = find_old_folders(tmp_path, 90, now)
    assert {f.path for f in old} == {old_run, old_upload}
    assert delete_folders(old, tmp_path) == 2
    assert not old_run.exists() and not old_upload.exists()
    assert new_run.exists() and new_upload.exists() and (tmp_path / "uploads").exists()


def test_recent_file_keeps_old_folder(tmp_path):
    now = time.time()
    run = _make(tmp_path, "run", 200, now)
    (run / "report.docx").write_text("new")               # re-reported today
    assert find_old_folders(tmp_path, 90, now) == []


def test_refuses_outside_output_folder(tmp_path):
    from risk_engine.retention import OldFolder
    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(ValueError):
        delete_folders([OldFolder(other, 999)], tmp_path / "outputs")
    assert other.exists()


def test_keep_days_setting():
    assert keep_days({"retention": {"keep_days": 30}}) == 30
    assert keep_days({}) == 90


def test_purge_command(tmp_path, monkeypatch):
    now = time.time()
    old_run = _make(tmp_path, "old", 100, now)
    monkeypatch.setattr("risk_engine.retention.output_root", lambda s: tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert main(["purge"]) == 0 and old_run.exists()       # not confirmed
    assert main(["purge", "--yes"]) == 0 and not old_run.exists()
