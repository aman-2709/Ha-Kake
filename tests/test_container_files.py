"""Guards for the container files (docs/CONTAINER.md): the image copies only what
it runs, the build context drops private files, and the Quadlet unit matches
the Containerfile. No container engine is needed, except by one test that builds
a throwaway context with docker and skips without it."""

import glob
import os
import re
import shlex
import shutil
import subprocess

import pytest

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


def test_copy_arguments_never_name_the_whole_tree_or_a_private_path():
    """Explicit paths, so a build that ignores both ignore files cannot ship the owner's named data.
    This reads only the COPY arguments: what a directory COPY picks up inside is the ignore files' job
    (the sentinel-context test below)."""
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
    for private in ("**/*.db", "**/*.db-*", "**/*_state.json", "**/config.local.json", "**/__pycache__",
                    "**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/*.log", "**/*.tmp", "**/*.jsonl"):
        assert private in lines, private
        assert lines.index(private) > last_allow, f"{private} must come after the re-includes to win"


def test_dockerignore_is_the_same_rules_as_containerignore():
    """Docker reads .dockerignore, podman and buildah .containerignore: one set of rules."""
    assert _lines(".dockerignore") == _lines(".containerignore")


# Files the image needs, and untracked private files that may sit inside the copied directories.
_WANTED = ["requirements.txt", "LICENSE", "NOTICE", "app_root.py", "vehicles/__init__.py", "simulator/model.py",
           "simulator/scenarios/idle.json", "web/app.py", "web/templates/index.html", "web/static/vehicletap.css",
           "web/static/vendor/x.js", "web/layouts/tiles.leaf_ze0.json"]
_PRIVATE = [".env", "config.local.json", "research/notes.md", "legacy/old.py", "tests/t.py", "web/sim_x.db",
            "simulator/private.log", "web/static/.env", "vehicles/local.pem", "simulator/secret.key",
            "web/static/dump.jsonl", "vehicles/scratch.tmp", "web/layouts/.env.local", "simulator/x.db-wal",
            "vehicles/p_state.json", "web/templates/.env"]


def _docker_that_can_export_locally(tmp_path):
    """The docker binary, or skip. A plain `FROM scratch` probe build with a local export must work first:
    that separates "this machine cannot do it" (no docker, no buildx, no daemon, a driver without the local
    exporter) from "the ignore rules leak", which must fail."""
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("docker is not installed")
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "Dockerfile").write_text("FROM scratch\nCOPY f /f\n")
    (probe / "f").write_text("x")
    try:
        done = subprocess.run([docker, "buildx", "build", "--output", f"type=local,dest={tmp_path / 'probe-out'}",
                               str(probe)], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"docker did not run: {e}")
    if done.returncode:
        pytest.skip("docker cannot do a local-export build here: " + done.stderr.strip()[-200:])
    return docker


def test_the_effective_ignore_rules_keep_private_files_out_of_the_image_context(tmp_path):
    """Build a throwaway context with docker's own ignore handling: nested private files must not be copied.
    The rules are asserted identical to .containerignore above, so this covers both."""
    docker = _docker_that_can_export_locally(tmp_path)
    ctx, out = tmp_path / "ctx", tmp_path / "out"
    ctx.mkdir()
    shutil.copy(os.path.join(ROOT, ".dockerignore"), ctx / ".dockerignore")
    (ctx / "Dockerfile").write_text("FROM scratch\nCOPY . /ctx\n")           # no base image to pull
    for rel in _WANTED + _PRIVATE:
        (ctx / rel).parent.mkdir(parents=True, exist_ok=True)
        (ctx / rel).write_text("x")
    done = subprocess.run([docker, "buildx", "build", "--output", f"type=local,dest={out}", str(ctx)],
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    copied = {os.path.relpath(os.path.join(r, f), out / "ctx") for r, _, fs in os.walk(out / "ctx") for f in fs}
    assert [p for p in _PRIVATE if p in copied] == []
    assert [p for p in _WANTED if p not in copied] == []


def test_quadlet_runs_the_simulator_on_host_networking_with_the_data_volume():
    unit = _lines("deploy/quadlet/vehicletap.container")
    assert "Network=host" in unit                       # the app binds loopback only (SECURITY.md)
    assert not any(ln.startswith("PublishPort=") for ln in unit)
    assert "Exec=python web/app.py --adapter sim" in unit
    assert "Environment=VEHICLETAP_DATA_DIR=/data" in unit
    assert "ReadOnly=true" in unit
    assert [ln for ln in unit if ln.startswith("Volume=")] == ["Volume=vehicletap.volume:/data"]
    assert os.path.exists(os.path.join(ROOT, "deploy", "quadlet", "vehicletap.volume"))
    assert "VEHICLETAP_DATA_DIR=/data" in " ".join(_lines("Containerfile"))


# ── the opt-in OTA status mount (docs/OTA.md) ──

OTA_DROPIN = "deploy/quadlet/optional/vehicletap.container.d/10-ota.conf"


def test_the_ota_dropin_hands_the_container_a_directory_read_only_and_changes_nothing_else():
    """Optional, so the shipped unit keeps working on a board with no exporter (a bind mount whose source does
    not exist stops a unit from starting). A directory, not the file: an atomic replace gives the file a new
    inode, and a single-file bind mount would keep showing the old one."""
    lines = _lines(OTA_DROPIN)
    assert lines[0] == "[Container]" and not any(ln.startswith("[") for ln in lines[1:])
    volumes = [ln for ln in lines if ln.startswith("Volume=")]
    assert len(volumes) == 1
    host, inside, options = volumes[0][len("Volume="):].split(":")
    assert host.startswith("/") and not host.endswith(".json"), "mount the directory"
    assert "ro" in options.split(","), "the container only reads it"
    assert [ln for ln in lines if ln.startswith("Environment=")] == [f"Environment=VEHICLETAP_OTA_FILE={inside}/ota_status.json"]
    assert len(lines) == 3, lines                         # [Container], the Volume, the Environment: nothing else
    # and the hardening the shipped unit sets is not touched from here
    assert not any(ln.startswith(("Network=", "PublishPort=", "PodmanArgs=", "AddCapability=", "SecurityLabel",
                                  "Exec=", "ReadOnly=", "User=", "NoNewPrivileges=", "DropCapability=")) for ln in lines)


def test_the_ota_dropin_is_not_in_the_directory_the_install_command_copies_from():
    assert not os.path.exists(os.path.join(ROOT, "deploy", "quadlet", "vehicletap.container.d"))
    assert [ln for ln in _lines("deploy/quadlet/vehicletap.container") if ln.startswith("Volume=")] == ["Volume=vehicletap.volume:/data"]


def test_the_ota_files_the_image_needs_are_copied_and_the_exporter_stays_on_the_host():
    copied = [s for sources in _copy_sources() for s in sources]
    assert "web/*.py" in copied and "web/templates/" in copied and "web/static/" in copied
    assert not any(s.startswith("tools") for s in copied), "the exporter runs on the host, not in the image"
