<!--
SPDX-FileCopyrightText: 2026 David D. Karnowski
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Where Ha-Kake keeps your data

Ha-Kake's own data (the readings database, the last state, tile layouts, bookmarks, calibration) lives in one **data
folder** outside the source tree. It is created the first time you run the app, and a fresh install starts with an empty
database there (the schema is created on first use).

| Platform | Default data folder |
|---|---|
| macOS | `~/Library/Application Support/VehicleTap` |
| Linux and others | `$XDG_DATA_HOME/vehicletap`, else `~/.local/share/vehicletap` |
| Windows | `%APPDATA%\VehicleTap` |

Set `HAKAKE_DATA_DIR` to use another folder, for example one folder per car:

```bash
HAKAKE_DATA_DIR=~/cars/my-leaf ./venv/bin/python web/app.py
```

The startup banner prints the folder in use (`data folder: …`). The folder is created owner-only.

**An install from before the rename.** The folder used to be called `Ha-Kake` (`ha-kake` on Linux). If that folder
exists and the new one does not, the app keeps using the old one exactly as it is: nothing is created beside it and
nothing is moved, copied or deleted, so your history stays where it was. If both exist, the new one is used and the
startup banner says the old one is not. To switch on purpose, stop the app and move the files yourself, or point
`HAKAKE_DATA_DIR` at the folder you want.

## What is in it

| File | What | Safe to delete? |
|---|---|---|
| `leaf_battery.db` | the readings database (SQLite), never pruned by the app | **No: this is your history. Back it up.** |
| `battery_state.json` | the last reading, for the dashboard | yes, rewritten on the next cycle |
| `tiles.json`, `layouts.json`, `sim_tiles.json` | tile arrangement and named layouts | yes (resets to the layout the project ships in `web/layouts/`) |
| `bookmarks.json` | timeline flags you dropped | no, unless you do not need them |
| `calibration.json` | per-car offsets (for example the current-sensor zero) | no, unless you will recalibrate |
| `console.jsonl`, `reader.pause` | the raw console's window; the pause flag | yes |
| `ota_status.json` | the board's OS-update status, written by a process on the host ([OTA.md](OTA.md)) | yes, the exporter rewrites it |
| `replay_*.db`, `sim_*.db` (and `*_state.json`) | replay and simulator runs, kept apart from real readings | yes, disposable |

## Moving an older install's data

Earlier versions kept these files in `web/` next to the code. The app **never moves or deletes your data on its own**.
If it finds an old `web/leaf_battery.db` and no database in the data folder, it prints a note and starts with an empty
database. To keep your history:

1. Stop the dashboard and the reader.
2. Copy the old files into the data folder (`web/leaf_battery.db`, and the `web/*.json` settings you want).
3. Start the app again and check the history is there before deleting the old copies.

## Backups

Copy `leaf_battery.db` while the reader is stopped, or use SQLite's own `.backup`. The database file is plain data
about your car and your trips: treat backups as private.
