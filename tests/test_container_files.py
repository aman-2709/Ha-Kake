"""Guards for the container files (docs/CONTAINER.md): the image copies only what
it runs, the build context drops private files, and the Quadlet unit matches
the Containerfile. No container engine is needed."""

import glob
import os
import re
import shlex

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lines(name):
    """The file's lines without blanks and comments."""
    with open(os.path.join(ROOT, name)) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


def _copy_sources():
    return [shlex.split(ln)[1:-1] for ln in _lines("Containerfile") if ln.startswith("COPY ")]


def test_every_copy_source_in_the_containerfile_exists():
    """A renamed directory would otherwise fail at build time, on someone's board."""
    copies = _copy_sources()
    assert copies
    for sources in copies:
        for src in sources:
            assert glob.glob(os.path.join(ROOT, src)), f"Containerfile COPY source matches nothing: {src}"


def test_the_image_never_copies_the_whole_tree_or_private_files():
    """Explicit paths, so a build that ignores .containerignore cannot ship the owner's data."""
    for sources in _copy_sources():
        assert "." not in sources and "./" not in sources
        assert not any(re.search(r"config\.local|research|legacy|\.db|_state", s) for s in sources), sources


def test_the_image_runs_as_a_non_root_user():
    users = [ln.split()[1] for ln in _lines("Containerfile") if ln.startswith("USER ")]
    assert users and users[-1] not in ("0", "root")


def test_containerignore_is_an_allowlist_and_its_denylist_comes_last():
    lines = _lines(".containerignore")
    assert lines[0] == "*"
    assert not any(ln.startswith("!") and re.search(r"config\.local|research|\.db", ln) for ln in lines)
    last_allow = max(i for i, ln in enumerate(lines) if ln.startswith("!"))
    for private in ("**/*.db", "**/*.db-*", "**/*_state.json", "**/config.local.json", "**/__pycache__"):
        assert private in lines, private
        assert lines.index(private) > last_allow, f"{private} must come after the re-includes to win"


def test_dockerignore_is_the_same_rules_as_containerignore():
    """Docker reads .dockerignore, podman and buildah .containerignore: one set of rules."""
    assert _lines(".dockerignore") == _lines(".containerignore")


def test_quadlet_runs_the_simulator_on_host_networking_with_the_data_volume():
    unit = _lines("deploy/quadlet/ha-kake.container")
    assert "Network=host" in unit                       # the app binds loopback only (SECURITY.md)
    assert not any(ln.startswith("PublishPort=") for ln in unit)
    assert "Exec=python web/app.py --adapter sim" in unit
    assert "Environment=HAKAKE_DATA_DIR=/data" in unit
    assert "ReadOnly=true" in unit
    assert [ln for ln in unit if ln.startswith("Volume=")] == ["Volume=ha-kake.volume:/data"]
    assert os.path.exists(os.path.join(ROOT, "deploy", "quadlet", "ha-kake.volume"))
    assert "HAKAKE_DATA_DIR=/data" in " ".join(_lines("Containerfile"))
