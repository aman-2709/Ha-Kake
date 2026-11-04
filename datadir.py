# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where VehicleTap keeps its own data: the readings database, the last state, tile layouts, bookmarks, calibration.

Application data lives outside the source tree, in one documented folder, created on first run:

    VEHICLETAP_DATA_DIR   if set, that folder (use it to keep a car's data somewhere you choose, or per car)
    macOS                 ~/Library/Application Support/VehicleTap
    Linux / other         $XDG_DATA_HOME/vehicletap, else ~/.local/share/vehicletap
    Windows               %APPDATA%\\VehicleTap

Before the rename the folder was called Ha-Kake (ha-kake on Linux) and the variable HAKAKE_DATA_DIR, which is
still read. An install that still has that folder, and no new one, keeps using it exactly as it is;
``startup_note()`` says so.

A fresh install starts with an empty database in that folder (the schema is created on first use). The program
never moves or deletes data on its own: an older install's files stay in ``web/`` until you move them
(see docs/DATA.md), and ``startup_note()`` says so when it finds them.
"""
import os
import sys

from util import env

APP = "VehicleTap"
LEGACY_APP = "Ha-Kake"          # the folder's name before the rename; an install that has one keeps using it
_HERE = os.path.dirname(os.path.abspath(__file__))


def _default_dir(app):
    """Where the platform keeps the data folder of an app called `app`."""
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", app)
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), app)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, app.lower())


def data_dir():
    """The data folder, created (owner-only) if it does not exist yet.

    A folder from before the rename is used as it is when it is there and the new one is not: nothing is
    created beside it, moved, copied or deleted. If both exist the new one wins and startup_note() says so."""
    given = (env("VEHICLETAP_DATA_DIR") or "").strip()
    if given:
        d = os.path.abspath(os.path.expanduser(given))
    else:
        d = _default_dir(APP)
        legacy = _default_dir(LEGACY_APP)
        if not os.path.isdir(d) and os.path.isdir(legacy):
            d = legacy
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
    except OSError as e:
        raise SystemExit(f"VehicleTap cannot create its data folder {d!r} ({e.strerror}). "
                         f"Set VEHICLETAP_DATA_DIR to a folder you can write to; see docs/DATA.md.") from e
    os.environ["VEHICLETAP_DATA_DIR"] = d          # child processes (the reader) must resolve the same absolute folder
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
    legacy = _default_dir(LEGACY_APP)
    if os.path.abspath(d) == os.path.abspath(legacy):
        note += "  (the folder from before the rename, kept as it is)"
    elif os.path.isdir(legacy):
        note += (f"\n  note: an older data folder exists at {legacy} and is NOT used; to keep that history, "
                 f"set VEHICLETAP_DATA_DIR to it or move its files into {d}; see docs/DATA.md")
    if os.path.exists(old) and not os.path.exists(new):
        note += (f"\n  note: an older database exists at {old} and is NOT used any more; to keep that history, "
                 f"move it (and the other web/*.json settings) into the data folder; see docs/DATA.md")
    return note
