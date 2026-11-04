"""The project was called Ha-Kake until 2026-11 (it is a fork of David D. Karnowski's project of that name).

Nothing tracked may still carry the old name, in its text or in its path, except what names it on purpose: the
attribution, the history, the old-name compatibility code and its docs and tests, and recordings left as they
were captured. The list is explicit, each entry says why, and a stale entry fails too, so it cannot rot.
"""
import os
import re

import pytest

from conftest import ROOT

OLD = re.compile(r"ha-?_?kake", re.IGNORECASE)
SKIP_DIRS = {".git", "venv", "research", "node_modules", "__pycache__", "vendor"}
BINARY = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".gz", ".zip", ".db")

# Whole files that name the old form on purpose.
WHOLE_FILE = {
    "NOTICE": "attribution: the original author's copyright notice and trademark paragraph",
    "LICENSE-DOCS": "the documentation licence's original copyright header",
    "WORKLOG.md": "history: entries written when the project had the old name",
    "util.py": "env() reads the HAKAKE_ twin of every VEHICLETAP_ name",
    "datadir.py": "the data folder from before the rename is still used",
    "elm327.py": "replay files recorded before the rename carry the old key",
    "docs/DATA.md": "explains the old folder and variable",
    "docs/REPLAY.md": "explains the old replay key",
    "tests/test_util_env.py": "tests the old-name twin",
    "tests/test_datadir.py": "tests the old folder and variable",
    "tests/test_legacy_env_names.py": "tests the old variable names at the real readers",
    "tests/test_replay.py": "tests the old replay key",
    "tests/test_recorder.py": "asserts the old replay key is no longer written",
    "tests/test_no_old_name.py": "this file",
    "tests/fixtures/session_leaf_ze0.json": "a real capture, left as recorded (old replay key)",
    "tests/fixtures/session_lancer_2009.json": "a real capture, left as recorded (old replay key)",
    "tests/fixtures/session_leaf_ze0_pull_sim.json": "a recording left as written (old replay key and adapter name)",
}
# Browser storage keys keep the old prefix so that saved layouts and settings survive the rename.
STORAGE_KEYS = ("hakake-alerts-muted", "hakake-sim-folded-v1", "hakake-sim-tiles-v1", "hakake-sim-tiles-v0",
                "hakake-tiles-v2", "hakake-timeline-dock")
# The upstream project is named where it is credited.
UPSTREAM = re.compile(r"davidkarnowski|fork of \[Ha-Kake\]|based on Ha-Kake", re.IGNORECASE)
UPSTREAM_FILES = {"README.md"}


def text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and (not d.startswith(".") or d == ".github")]
        for name in filenames:
            if not name.lower().endswith(BINARY):
                path = os.path.join(dirpath, name)
                yield os.path.relpath(path, ROOT).replace(os.sep, "/"), path


def lines_of(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().split("\n")
    except UnicodeDecodeError:
        return []


def allowed(rel, line):
    if rel in WHOLE_FILE:
        return True
    if any(key in line for key in STORAGE_KEYS):
        return True
    return rel in UPSTREAM_FILES and bool(UPSTREAM.search(line))


def test_no_tracked_path_carries_the_old_name():
    bad = [rel for rel, _ in text_files() if OLD.search(rel)]
    assert not bad, bad


def test_no_file_carries_the_old_name_except_on_purpose():
    bad = []
    for rel, path in text_files():
        for n, line in enumerate(lines_of(path), 1):
            if OLD.search(line) and not allowed(rel, line):
                bad.append(f"{rel}:{n}: {line.strip()[:110]}")
    assert not bad, "still called by its old name (or add it to the list, with a reason):\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("rel", sorted(WHOLE_FILE))
def test_every_whole_file_entry_is_still_needed(rel):
    path = os.path.join(ROOT, rel)
    if not os.path.exists(path):
        pytest.fail(f"{rel} is on the list but does not exist")
    assert any(OLD.search(line) for line in lines_of(path)), f"{rel} no longer names the old form: drop its entry"


def test_every_storage_key_is_still_used_somewhere():
    text = "\n".join("\n".join(lines_of(p)) for rel, p in text_files()
                     if rel.endswith((".js", ".html")) and not rel.startswith("tests/"))
    assert [k for k in STORAGE_KEYS if k not in text] == []
