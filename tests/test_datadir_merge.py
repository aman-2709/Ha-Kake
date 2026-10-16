"""Data-folder guards for the combined tree: the cockpit's saved layout and the
simulator's files follow the data folder, and the repo's web/ directory holds
code and shipped layouts only."""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cockpit_layout_and_simulator_files_follow_the_data_folder(tmp_path):
    """Fresh interpreter, so the import-time values are the ones checked."""
    code = ("import sys; sys.path[:0]=[%r, %r+'/web']\n"
            "import reader as rd\n"
            "print(rd.SIM_TILES_FILE); print(rd.sim_db()); print(rd.LAYOUTS_DIR)\n") % (ROOT, ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "HAKAKE_DATA_DIR": str(tmp_path / "d")}, timeout=60)
    tiles, sim_db, layouts = out.stdout.split()
    assert tiles.startswith(str(tmp_path / "d")) and sim_db.startswith(str(tmp_path / "d")), out.stderr
    # The shipped layouts are code: they stay in the repo, never in the data folder.
    assert layouts == os.path.join(ROOT, "web", "layouts")


def test_web_directory_tracks_no_runtime_data():
    """Only code, templates, static files and shipped layouts are committed under web/."""
    files = subprocess.run(["git", "ls-files", "web"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not files:
        return                                           # not a git checkout (e.g. an exported tarball)
    data = [f for f in files
            if re.search(r"\.(db|db-wal|db-shm|pause|jsonl)$|_state\.json$", f)
            or (f.endswith(".json") and not f.startswith(("web/layouts/", "web/static/")))]
    assert not data, f"runtime data committed under web/: {data}"


def test_every_shipped_layout_is_well_formed_json_with_tiles():
    import json
    d = os.path.join(ROOT, "web", "layouts")
    names = sorted(os.listdir(d))
    assert "sim_tiles.json" in names and any(n.startswith("tiles.") for n in names)
    for n in names:
        with open(os.path.join(d, n)) as f:
            data = json.load(f)
        tiles = data["tiles"] if isinstance(data, dict) else data
        assert tiles and all("id" in t for t in tiles), n


def test_runtime_files_are_not_built_from_the_source_folder():
    """A new settings or database file must go through datadir.path(), not DIR.
    The allowed uses are the code's own folders and the one-off legacy import."""
    allowed = re.compile(r'"(layouts|reader\.py|battery_history\.json|templates|static)"')
    bad = []
    for sub in ("web", "simulator"):
        for fn in os.listdir(os.path.join(ROOT, sub)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(ROOT, sub, fn)) as f:
                for n, line in enumerate(f, 1):
                    if re.search(r"os\.path\.join\(\s*(DIR|HERE|_HERE)\s*,", line) and not allowed.search(line):
                        bad.append(f"{sub}/{fn}:{n}: {line.strip()}")
    assert not bad, "\n".join(bad)
