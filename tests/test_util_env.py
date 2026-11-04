"""util.env(): the current VEHICLETAP_ name, then its HAKAKE_ twin from before the rename, then explicit aliases.

The twin is one rule in one place, so no call site carries an alias list for it. The older LEAF_* names are
still passed explicitly, as before.
"""
import pytest

from util import env

NEW, OLD = "VEHICLETAP_ENVTEST_X", "HAKAKE_ENVTEST_X"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in (NEW, OLD, "LEAF_ENVTEST_X", "VEHICLETAP_ENVTEST_ONLY", "HAKAKE_ENVTEST_ONLY", "HAKAKE__ENVTEST_ONLY",
                 "ENVTEST_PLAIN"):
        monkeypatch.delenv(name, raising=False)


def test_the_current_name_is_read(monkeypatch):
    monkeypatch.setenv(NEW, "new")
    assert env(NEW) == "new"


def test_the_name_from_before_the_rename_still_works(monkeypatch):
    monkeypatch.setenv(OLD, "old")
    assert env(NEW) == "old"


def test_the_current_name_wins_when_both_are_set(monkeypatch):
    monkeypatch.setenv(NEW, "new")
    monkeypatch.setenv(OLD, "old")
    assert env(NEW) == "new"


def test_empty_counts_as_unset_so_the_old_name_is_found(monkeypatch):
    monkeypatch.setenv(NEW, "")
    monkeypatch.setenv(OLD, "old")
    assert env(NEW) == "old"


def test_nothing_set_gives_the_default_or_none():
    assert env(NEW) is None
    assert env(NEW, default="fallback") == "fallback"


def test_order_is_name_then_old_prefix_then_explicit_aliases(monkeypatch):
    monkeypatch.setenv("LEAF_ENVTEST_X", "leaf")
    assert env(NEW, "LEAF_ENVTEST_X") == "leaf"
    monkeypatch.setenv(OLD, "old")
    assert env(NEW, "LEAF_ENVTEST_X") == "old"
    monkeypatch.setenv(NEW, "new")
    assert env(NEW, "LEAF_ENVTEST_X") == "new"


def test_the_twin_only_runs_from_the_new_prefix_to_the_old_one(monkeypatch):
    """Asking for an old name never reads a new one, and other names get no twin."""
    monkeypatch.setenv("VEHICLETAP_ENVTEST_ONLY", "new")
    assert env("HAKAKE_ENVTEST_ONLY") is None
    monkeypatch.setenv("HAKAKE_ENVTEST_ONLY", "old")
    assert env("ENVTEST_PLAIN") is None
    # The prefix has to be at the start. Cutting 11 characters off "X" + the new name would give "HAKAKE__ENVTEST_ONLY".
    monkeypatch.setenv("HAKAKE__ENVTEST_ONLY", "wrong")
    assert env("XVEHICLETAP_ENVTEST_ONLY") is None


def test_a_value_is_returned_as_written(monkeypatch):
    monkeypatch.setenv(OLD, " spaced ")
    assert env(NEW) == " spaced "


# ── nobody goes around env() ──

import os  # noqa: E402
import re  # noqa: E402

from conftest import ROOT  # noqa: E402

SKIP_DIRS = {".git", "venv", "research", "tests", "node_modules", "__pycache__"}
# A read of a prefixed variable that does not go through util.env(): .get(), os.getenv(), os.environ["X"] not
# being assigned to, or `"X" in os.environ`. Writes (the reader hands its settings to its child that way) are fine.
DIRECT_READ = re.compile(
    r"""os\.environ\.get\(\s*["'](?:HAKAKE|VEHICLETAP)_"""
    r"""|os\.getenv\(\s*["'](?:HAKAKE|VEHICLETAP)_"""
    r"""|os\.environ\[\s*["'](?:HAKAKE|VEHICLETAP)_[^"']*["']\s*\](?!\s*=[^=])"""
    r"""|["'](?:HAKAKE|VEHICLETAP)_[^"']*["']\s+in\s+os\.environ""")


def python_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def test_no_module_reads_a_prefixed_variable_around_env():
    """The HAKAKE_ twin lives in util.env(); a direct os.environ read would silently ignore the other name."""
    bad = []
    for path in python_files():
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if DIRECT_READ.search(line):
                    bad.append(f"{os.path.relpath(path, ROOT)}:{n}: {line.strip()}")
    assert not bad, "read it through util.env():\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("line, is_read", [
    ('x = os.environ.get("HAKAKE_FOO")', True),
    ('x = os.getenv("VEHICLETAP_FOO", "d")', True),
    ('x = os.environ["HAKAKE_FOO"]', True),
    ('if "VEHICLETAP_FOO" in os.environ:', True),
    ('os.environ["HAKAKE_FOO"] = "1"', False),                      # a write: the child process inherits it
    ('os.environ["VEHICLETAP_FOO"] = d          # comment', False),
    ('x = os.environ.get("HOME")', False),
    ('x = env("HAKAKE_FOO")', False),
])
def test_the_direct_read_pattern_means_what_it_says(line, is_read):
    assert bool(DIRECT_READ.search(line)) is is_read
