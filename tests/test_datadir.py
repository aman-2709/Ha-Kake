# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
import os

import datadir


def test_env_override_is_used_and_created(tmp_path, monkeypatch):
    d = tmp_path / "mine" / "data"
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(d))
    assert datadir.data_dir() == str(d) and d.is_dir()
    assert datadir.path("leaf_battery.db") == str(d / "leaf_battery.db")


def test_default_is_outside_the_source_tree(monkeypatch):
    monkeypatch.delenv("VEHICLETAP_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home-for-test")
    monkeypatch.setattr(datadir.os, "makedirs", lambda *a, **k: None)
    d = datadir.data_dir()
    assert not d.startswith(datadir._HERE)
    assert "vehicletap" in d.lower() and "ha-kake" not in d.lower()


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
                         env={**os.environ, "VEHICLETAP_DATA_DIR": str(tmp_path / "d")}, timeout=60)
    paths = out.stdout.split()
    assert len(paths) == 7, out.stderr
    assert all(p.startswith(str(tmp_path / "d")) for p in paths), paths


def test_startup_note_warns_about_an_older_database_without_moving_it(tmp_path, monkeypatch):
    fake_root = tmp_path / "repo"
    (fake_root / "web").mkdir(parents=True)
    old = fake_root / "web" / "leaf_battery.db"
    old.write_bytes(b"old")
    monkeypatch.setattr(datadir, "_HERE", str(fake_root))
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(tmp_path / "data"))
    note = datadir.startup_note()
    assert "NOT used" in note and "docs/DATA.md" in note
    assert old.exists() and old.read_bytes() == b"old"            # never moved or deleted


def test_no_warning_once_the_data_folder_has_a_database(home, tmp_path, monkeypatch):      # `home`: not this machine's
    fake_root = tmp_path / "repo"
    (fake_root / "web").mkdir(parents=True)
    (fake_root / "web" / "leaf_battery.db").write_bytes(b"old")
    data = tmp_path / "data"
    data.mkdir()
    (data / "leaf_battery.db").write_bytes(b"new")
    monkeypatch.setattr(datadir, "_HERE", str(fake_root))
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(data))
    assert "NOT used" not in datadir.startup_note()


def test_a_relative_data_dir_is_made_absolute_for_child_processes(tmp_path, monkeypatch):
    """app.py starts the reader with a different working directory; both must resolve the same folder."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", "car1")
    d = datadir.data_dir()
    assert os.path.isabs(d) and d == str(tmp_path / "car1") or d == os.path.realpath(str(tmp_path / "car1"))
    assert os.path.isabs(os.environ["VEHICLETAP_DATA_DIR"])


def test_an_unwritable_data_folder_fails_with_a_clear_message(tmp_path, monkeypatch):
    import pytest
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(blocker / "sub"))
    with pytest.raises(SystemExit) as e:
        datadir.data_dir()
    assert "VEHICLETAP_DATA_DIR" in str(e.value)


# ── the folder from before the rename ──

import types  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty home, a data folder that is not forced by the environment, and no XDG override."""
    monkeypatch.delenv("VEHICLETAP_DATA_DIR", raising=False)     # restored afterwards: data_dir() re-exports it
    monkeypatch.delenv("HAKAKE_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setattr(datadir, "_HERE", str(tmp_path / "repo"))
    return tmp_path


def on(monkeypatch, platform):
    monkeypatch.setattr(datadir, "sys", types.SimpleNamespace(platform=platform))


# where each platform keeps (new folder, old folder), relative to the fake home
FOLDERS = {
    "linux": (".local/share/vehicletap", ".local/share/ha-kake"),
    "darwin": ("Library/Application Support/VehicleTap", "Library/Application Support/Ha-Kake"),
    "win32": ("AppData/VehicleTap", "AppData/Ha-Kake"),
}


@pytest.mark.parametrize("platform", FOLDERS)
def test_a_fresh_install_gets_a_new_private_folder(home, monkeypatch, platform):
    on(monkeypatch, platform)
    new, old = (home / p for p in FOLDERS[platform])
    d = datadir.data_dir()
    assert d == str(new) and new.is_dir() and not old.exists()
    assert (new.stat().st_mode & 0o777) == 0o700


@pytest.mark.parametrize("platform", FOLDERS)
def test_an_install_from_before_the_rename_keeps_its_folder_untouched(home, monkeypatch, platform):
    on(monkeypatch, platform)
    new, old = (home / p for p in FOLDERS[platform])
    old.mkdir(parents=True)
    (old / "leaf_battery.db").write_bytes(b"history")
    d = datadir.data_dir()
    assert d == str(old) and not new.exists()                 # nothing created beside it
    assert [p.name for p in old.iterdir()] == ["leaf_battery.db"]
    assert (old / "leaf_battery.db").read_bytes() == b"history"
    assert datadir.os.environ["VEHICLETAP_DATA_DIR"] == str(old)  # the reader child process resolves the same folder


def test_with_both_folders_the_new_one_wins_and_the_note_says_the_old_one_is_unused(home, monkeypatch):
    on(monkeypatch, "linux")
    new, old = (home / p for p in FOLDERS["linux"])
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    assert datadir.data_dir() == str(new)
    note = datadir.startup_note()
    assert "NOT used" in note and str(old) in note and "docs/DATA.md" in note


def test_the_note_says_when_the_old_folder_is_the_one_in_use(home, monkeypatch):
    on(monkeypatch, "linux")
    old = home / FOLDERS["linux"][1]
    old.mkdir(parents=True)
    note = datadir.startup_note()
    assert str(old) in note and "NOT used" not in note and "before the rename" in note


def test_a_fresh_install_has_no_note_about_an_older_folder(home, monkeypatch):
    on(monkeypatch, "linux")
    note = datadir.startup_note()
    assert "NOT used" not in note and "before the rename" not in note


def test_a_file_or_a_dangling_link_at_the_old_path_is_not_a_data_folder(home, monkeypatch):
    on(monkeypatch, "linux")
    new, old = (home / p for p in FOLDERS["linux"])
    old.parent.mkdir(parents=True)
    old.write_text("not a folder")
    assert datadir.data_dir() == str(new)
    datadir.os.environ.pop("VEHICLETAP_DATA_DIR")
    new.rmdir()
    old.unlink()
    old.symlink_to(home / "nowhere")
    assert datadir.data_dir() == str(new)


def test_a_link_to_a_folder_at_the_old_path_is_followed(home, monkeypatch):
    on(monkeypatch, "linux")
    elsewhere = home / "bigdisk" / "leaf"
    elsewhere.mkdir(parents=True)
    old = home / FOLDERS["linux"][1]
    old.parent.mkdir(parents=True)
    old.symlink_to(elsewhere)
    assert datadir.data_dir() == str(old) and not (home / FOLDERS["linux"][0]).exists()


def test_the_environment_still_beats_both_folders(home, monkeypatch):
    on(monkeypatch, "linux")
    (home / FOLDERS["linux"][1]).mkdir(parents=True)
    mine = home / "chosen"
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(mine))
    assert datadir.data_dir() == str(mine) and mine.is_dir()
    assert "NOT used" in datadir.startup_note()               # the old folder is there and is not the one in use


def test_xdg_data_home_moves_both_names(home, monkeypatch):
    on(monkeypatch, "linux")
    xdg = home / "xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    (xdg / "ha-kake").mkdir(parents=True)
    assert datadir.data_dir() == str(xdg / "ha-kake")


# ── the variable from before the rename ──

def test_the_old_variable_name_still_chooses_the_folder(home, monkeypatch):
    mine = home / "from-the-old-variable"
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(mine))
    assert datadir.data_dir() == str(mine) and mine.is_dir()
    assert datadir.os.environ["VEHICLETAP_DATA_DIR"] == str(mine)      # the reader child process gets the new name


def test_the_new_variable_beats_the_old_one(home, monkeypatch):
    monkeypatch.setenv("HAKAKE_DATA_DIR", str(home / "old"))
    monkeypatch.setenv("VEHICLETAP_DATA_DIR", str(home / "new"))
    assert datadir.data_dir() == str(home / "new") and not (home / "old").exists()
