# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
import os

import datadir


def test_env_override_is_used_and_created(tmp_path, monkeypatch):
    d = tmp_path / "mine" / "data"
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(d))
    assert datadir.data_dir() == str(d) and d.is_dir()
    assert datadir.path("leaf_battery.db") == str(d / "leaf_battery.db")


def test_default_is_outside_the_source_tree(monkeypatch):
    monkeypatch.delenv("HAKAKE_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")
    monkeypatch.setattr(datadir.os, "makedirs", lambda *a, **k: None)
    d = datadir.data_dir()
    assert not d.startswith(datadir._HERE) and "Ha-Kake" in d or "ha-kake" in d


def test_runtime_modules_keep_their_files_in_the_data_folder(tmp_path):
    """Fresh interpreter (the autouse fixtures redirect the live module globals, so look at the import-time values)."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import sys; sys.path[:0]=[%r, %r+'/web']\n"
            "import reader as rd, store as st\n"
            "for p in (rd.STATE_FILE, rd.TILES_FILE, rd.BOOKMARKS_FILE, rd.CALIB_FILE, rd.PAUSE_FILE, rd.LAYOUTS_FILE, st.DEFAULT_DB):\n"
            "    print(p)\n") % (root, root)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "HAKAKE_DATA_DIR": str(tmp_path / "d")}, timeout=60)
    paths = out.stdout.split()
    assert len(paths) == 7, out.stderr
    assert all(p.startswith(str(tmp_path / "d")) for p in paths), paths


def test_startup_note_warns_about_an_older_database_without_moving_it(tmp_path, monkeypatch):
    fake_root = tmp_path / "repo"
    (fake_root / "web").mkdir(parents=True)
    old = fake_root / "web" / "leaf_battery.db"
    old.write_bytes(b"old")
    monkeypatch.setattr(datadir, "_HERE", str(fake_root))
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(tmp_path / "data"))
    note = datadir.startup_note()
    assert "NOT used" in note and "docs/DATA.md" in note
    assert old.exists() and old.read_bytes() == b"old"            # never moved or deleted


def test_no_warning_once_the_data_folder_has_a_database(tmp_path, monkeypatch):
    fake_root = tmp_path / "repo"
    (fake_root / "web").mkdir(parents=True)
    (fake_root / "web" / "leaf_battery.db").write_bytes(b"old")
    data = tmp_path / "data"
    data.mkdir()
    (data / "leaf_battery.db").write_bytes(b"new")
    monkeypatch.setattr(datadir, "_HERE", str(fake_root))
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(data))
    assert "NOT used" not in datadir.startup_note()


def test_a_relative_data_dir_is_made_absolute_for_child_processes(tmp_path, monkeypatch):
    """app.py starts the reader with a different working directory; both must resolve the same folder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HAKAKE_DATA_DIR", "car1")
    d = datadir.data_dir()
    assert os.path.isabs(d) and d == str(tmp_path / "car1") or d == os.path.realpath(str(tmp_path / "car1"))
    assert os.path.isabs(os.environ["HAKAKE_DATA_DIR"])


def test_an_unwritable_data_folder_fails_with_a_clear_message(tmp_path, monkeypatch):
    import pytest
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(blocker / "sub"))
    with pytest.raises(SystemExit) as e:
        datadir.data_dir()
    assert "HAKAKE_DATA_DIR" in str(e.value)
