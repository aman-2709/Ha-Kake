# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where Ha-Kake keeps its own data: the readings database, the last state, tile layouts, bookmarks, calibration.

Application data lives outside the source tree, in one documented folder, created on first run:

    HAKAKE_DATA_DIR   if set, that folder (use it to keep a car's data somewhere you choose, or per car)
    macOS             ~/Library/Application Support/Ha-Kake
    Linux / other     $XDG_DATA_HOME/ha-kake, else ~/.local/share/ha-kake
    Windows           %APPDATA%\\Ha-Kake

A fresh install starts with an empty database in that folder (the schema is created on first use). The program
never moves or deletes data on its own: an older install's files stay in ``web/`` until you move them
(see docs/DATA.md), and ``startup_note()`` says so when it finds them.
"""
import os
import sys

APP = "Ha-Kake"
_HERE = os.path.dirname(os.path.abspath(__file__))


def data_dir():
    """The data folder, created (owner-only) if it does not exist yet."""
    env = os.environ.get("HAKAKE_DATA_DIR", "").strip()
    if env:
        d = os.path.abspath(os.path.expanduser(env))
    elif sys.platform == "darwin":
        d = os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP)
    elif sys.platform.startswith("win"):
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
        d = os.path.join(base, APP.lower())
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"Ha-Kake cannot create its data folder {d!r} ({e.strerror}). "
                         f"Set HAKAKE_DATA_DIR to a folder you can write to; see docs/DATA.md.") from e
    os.environ["HAKAKE_DATA_DIR"] = d          # child processes (the reader) must resolve the same absolute folder
    return d


def path(name):
    """A file in the data folder."""
    return os.path.join(data_dir(), name)


def startup_note():
    """One line to print at startup: where the data is, and a hint if an older install's files are still in web/."""
    d = data_dir()
    old = os.path.join(_HERE, "web", "leaf_battery.db")
    new = os.path.join(d, "leaf_battery.db")
    note = f"data folder: {d}"
    if os.path.exists(old) and not os.path.exists(new):
        note += (f"\n  note: an older database exists at {old} and is NOT used any more; to keep that history, "
                 f"move it (and the other web/*.json settings) into the data folder; see docs/DATA.md")
    return note
