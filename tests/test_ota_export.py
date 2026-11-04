"""tools/ota_export.py: the host-side half of the OTA status file (docs/OTA.md).

It runs on the board, outside the container, as root, and it is the only thing that sees the host. So the
claims worth testing are the ones about what it reads and what it lets out: it only reads (an allowlist of the
commands it may run), it builds the document from named fields (a registry, a checksum or a key in its inputs
cannot reach the output), and what it writes is exactly what the dashboard's reader accepts.

The inputs are real captures from the J7 with the registry, digests and checksums replaced
(tests/fixtures/ota/).
"""
import json
import os
import stat
import sys
from types import SimpleNamespace

import pytest

from conftest import ROOT, fixture

sys.path.insert(0, os.path.join(ROOT, "tools"))

import ota_export as ex  # noqa: E402
import ota  # noqa: E402  (web/ota.py: the reader the output must satisfy)

BOOTC = fixture("ota/bootc_status.json")
ESYNC = fixture("ota/esync_components.json")
HOST = fixture("ota/host_misc.json")
NOW = HOST["time"]
MONO = HOST["monotonic"]
BOOT = HOST["boottime"]


def vfs():
    return ex.Vfs(**HOST["statvfs"])


def sources(**over):
    s = {"bootc": BOOTC, "esync": ESYNC, "kernel": HOST["kernel"],
         "units": {n: HOST["systemctl_show"][n] for n in ("esync", "candump", "cangen")},
         "selinux": HOST["selinux_enforce"], "ntp": HOST["ntp"], "vfs": vfs()}
    s.update(over)
    return s


def build(**over):
    return ex.build(sources(**over), now=NOW, mono=MONO, boot=BOOT)


# ── the document: every section, from real captures ──

def test_the_document_has_the_schema_and_the_time_it_was_made():
    d = build()
    assert d["schema"] == 1 and d["generated_at"] == ex.iso(NOW) == "2026-10-28T03:58:12Z"


def test_the_os_section_names_three_images_and_the_queued_rollback():
    o = build()["os"]
    assert o["booted"] == {"version": "4.4.0", "digest": o["booted"]["digest"], "built_at": "2026-08-07T23:03:53Z"}
    assert o["rollback"]["version"] == "4.5.0" and o["rollback"]["built_at"] == "2026-08-07T23:03:54Z"
    assert o["staged"] is None and o["rollback_queued"] is True
    assert o["kernel"] == "6.12.0-251.el10iv.aarch64"
    assert o["booted_at"] == "2026-10-27T23:46:53Z"            # now minus the time since boot


def test_nanosecond_times_become_whole_seconds():
    assert ex.iso_seconds("2026-08-07T23:03:53.358191364Z") == "2026-08-07T23:03:53Z"
    assert ex.iso_seconds("2026-08-07T23:03:53Z") == "2026-08-07T23:03:53Z"
    assert ex.iso_seconds("2026-08-07T16:03:53.5-07:00") == "2026-08-07T16:03:53-07:00"
    for bad in ("", None, 5, "later", "2026-08-07", "2026-08-07T23:03:53"):
        assert ex.iso_seconds(bad) == ""


def test_a_staged_update_is_an_image_like_the_others():
    b = json.loads(json.dumps(BOOTC))
    b["status"]["staged"] = json.loads(json.dumps(b["status"]["rollback"]))
    b["status"]["staged"]["image"]["version"] = "9.9.9"
    b["status"]["rollbackQueued"] = False
    o = build(bootc=b)["os"]
    assert o["staged"]["version"] == "9.9.9" and o["rollback_queued"] is False


@pytest.mark.parametrize("queued", ["true", 1, None, "yes", [True]])
def test_a_queued_rollback_needs_a_real_true(queued):
    b = json.loads(json.dumps(BOOTC))
    b["status"]["rollbackQueued"] = queued
    assert build(bootc=b)["os"]["rollback_queued"] is False


def test_components_come_from_the_esync_state_by_name():
    c = build()["components"]
    assert [x["id"] for x in c] == ["RHIVOS-APP-CANDUMP", "RHIVOS-OS-AUTOSD"]
    assert c[0] == {"id": "RHIVOS-APP-CANDUMP", "version": "3.4.0", "installed_at": "2026-07-24T20:16:34Z",
                    "transaction_digest": ESYNC["RHIVOS-APP-CANDUMP"]["transactionDigest"]}
    assert c[1]["version"] == ""


def test_services_report_state_and_when_they_started_on_the_wall_clock():
    s = {x["name"]: x for x in build()["services"]}
    assert list(s) == ["esync", "candump", "cangen"]
    e = s["esync"]
    assert (e["active_state"], e["sub_state"], e["restarts"]) == ("active", "running", 0)
    # started 52.715896 s after the monotonic clock began; now is MONO s after it began
    assert e["since"] == ex.iso(NOW - MONO + 52.715896) == "2026-10-27T23:47:46Z"
    assert s["candump"]["since"] == "2026-10-27T23:47:32Z"


def test_a_unit_that_does_not_exist_is_inactive_and_says_so():
    s = ex.service("nosuchunit", HOST["systemctl_show"]["nosuchunit"], now=NOW, mono=MONO)
    assert (s["active_state"], s["sub_state"], s["since"]) == ("inactive", "not-found", "")


def test_a_unit_that_never_started_has_no_start_time():
    text = "LoadState=loaded\nActiveState=inactive\nSubState=dead\nActiveEnterTimestampMonotonic=0\nNRestarts=0\n"
    assert ex.service("x", text, now=NOW, mono=MONO)["since"] == ""


@pytest.mark.parametrize("text", [None, "", "garbage", "ActiveState", "=\n=\n", "ActiveState=<script>\nNRestarts=many\n",
                                  "ActiveState=active\nSubState=<b>x</b>\nActiveEnterTimestampMonotonic=-5\n"])
def test_systemctl_output_that_is_garbage_is_unknown_not_a_crash(text):
    s = ex.service("x", text, now=NOW, mono=MONO)
    assert s["name"] == "x" and s["sub_state"] == "" and s["since"] == "" and s["restarts"] is None
    assert s["active_state"] == ("active" if text and text.startswith("ActiveState=active") else "unknown")


def test_health_from_the_kernel_the_clock_service_and_the_filesystem():
    h = build()["health"]
    assert h["selinux"] == "enforcing" and h["ntp_synced"] is True
    assert h["var_free_bytes"] == 5424121 * 4096 == 22217199616
    assert h["var_used_pct"] == 24.9                             # used / (used + available), as df shows it


@pytest.mark.parametrize("text,want", [("1\n", "enforcing"), ("0\n", "permissive"), ("1", "enforcing"),
                                       (None, "disabled"), ("", "unknown"), ("2", "unknown"), ("enforcing", "unknown")])
def test_selinux_mode_from_the_selinuxfs_flag(text, want):
    assert ex.selinux_mode(text) == want


@pytest.mark.parametrize("text,want", [("NTPSynchronized=yes\n", True), ("NTPSynchronized=no\n", False),
                                       ("NTPSynchronized=maybe", None), ("", None), (None, None), ("yes", None)])
def test_ntp_sync_from_timedatectl(text, want):
    assert ex.ntp_synced(text) is want


def test_a_full_filesystem_reads_as_one_hundred_percent_not_a_division_error():
    full = ex.Vfs(f_frsize=4096, f_blocks=100, f_bfree=0, f_bavail=0)
    assert ex.health("1", "NTPSynchronized=yes", full)["var_used_pct"] == 100.0
    empty = ex.Vfs(f_frsize=4096, f_blocks=0, f_bfree=0, f_bavail=0)
    h = ex.health("1", "NTPSynchronized=yes", empty)
    assert h["var_used_pct"] is None and h["var_free_bytes"] == 0


# ── sections that cannot be collected come out empty, never as an error ──

@pytest.mark.parametrize("junk", [None, 0, "x", [], [1], {"status": None}, {"status": []}, {"status": {"booted": "x"}}])
def test_bootc_output_that_is_not_what_it_should_be_gives_an_empty_os_section(junk):
    o = build(bootc=junk)["os"]
    assert o["booted"] is None and o["staged"] is None and o["rollback"] is None
    assert o["rollback_queued"] is False and o["kernel"] == HOST["kernel"]


@pytest.mark.parametrize("junk", [None, [], "x", 5, {"A": "x"}, {"A": None}, {"A": []}, {"": {"version": "1"}}])
def test_an_esync_state_that_is_not_what_it_should_be_gives_no_components(junk):
    assert build(esync=junk)["components"] == []


def test_a_missing_input_gives_a_section_that_says_nothing_and_the_rest_still_comes():
    d = ex.build({}, now=NOW, mono=MONO, boot=BOOT)
    assert d["os"]["booted"] is None and d["components"] == [] and d["services"] == []
    assert d["health"]["selinux"] == "disabled" and d["health"]["ntp_synced"] is None
    assert d["health"]["var_used_pct"] is None and d["health"]["var_free_bytes"] is None
    assert ota.clean(d)["schema"] == 1                           # still a file the dashboard accepts


# ── what must never get out ──

SECRETS = ["registry.invalid", "example/os-image", "apikey-0123", "tok_live_abc", "192.0.2.7", "serial-SYNTH-0001",
           "hostname.corp", "ostree"]


def poisoned():
    b = json.loads(json.dumps(BOOTC))
    b["spec"]["image"]["image"] = "registry.invalid/example/os-image:tag"
    b["status"]["booted"]["image"]["image"]["image"] = "registry.invalid/example/os-image@sha256:" + "ab" * 32
    b["status"]["booted"]["image"]["apikey"] = "apikey-0123"
    b["status"]["booted"]["token"] = "tok_live_abc"
    b["status"]["booted"]["host"] = "192.0.2.7"
    e = json.loads(json.dumps(ESYNC))
    e["RHIVOS-APP-CANDUMP"]["apikey"] = "apikey-0123"
    e["RHIVOS-APP-CANDUMP"]["deviceId"] = "serial-SYNTH-0001"
    e["RHIVOS-APP-CANDUMP"]["server"] = "hostname.corp"
    e["SECRET-COMPONENT"] = {"version": "1", "provisionKey": "tok_live_abc"}
    return b, e


def test_nothing_in_the_inputs_but_the_named_fields_reaches_the_output():
    b, e = poisoned()
    text = json.dumps(build(bootc=b, esync=e))
    for secret in SECRETS:
        assert secret not in text, secret
    assert "provisionKey" not in text and "deviceId" not in text


def test_the_real_capture_alone_leaks_no_registry_checksum_or_server_field():
    text = json.dumps(build())
    for word in ("registry", "transport", "checksum", "ostree", "stateroot", "image\"", "spec", "bootOrder"):
        assert word not in text, word


def test_the_output_is_what_the_dashboards_reader_accepts_whole():
    """Nothing the exporter writes is dropped or blanked by the whitelist on the other side."""
    d = build()
    out = ota.clean(d)
    for key in ("os", "components", "services", "health"):
        assert out[key] == d[key], key
    assert out["next_boot"]["version"] == "4.5.0" and out["next_boot"]["source"] == "rollback"


def test_the_output_is_strict_json():
    json.dumps(build(), allow_nan=False)


# ── it only reads ──

READ_ONLY = {
    ("bootc", "status", "--format", "json"),
    ("timedatectl", "show", "-p", "NTPSynchronized"),
}


def test_the_commands_it_may_run_are_reads_and_nothing_else():
    ran = []

    def fake(cmd, timeout=10):
        ran.append(tuple(cmd))
        return {"bootc": json.dumps(BOOTC), "timedatectl": HOST["ntp"]}.get(cmd[0], HOST["systemctl_show"]["esync"])

    io = SimpleNamespace(run=fake, read_file=lambda p: json.dumps(ESYNC), statvfs=lambda p: vfs(),
                         kernel_release=lambda: HOST["kernel"])
    ex.collect(ex.parse_args(["--out", "/x/ota.json", "--service", "esync", "--service", "cangen"]), io)
    assert ran, "nothing was collected"
    for cmd in ran:
        assert cmd in READ_ONLY or (cmd[0] == "systemctl" and cmd[1] == "show" and cmd[2] in ("esync", "cangen")), cmd
    forbidden = {"rollback", "upgrade", "switch", "apply", "restart", "start", "stop", "kill", "reboot", "edit",
                 "enable", "disable", "mask", "set-property", "daemon-reload", "pull", "rm"}
    assert not forbidden & {part for cmd in ran for part in cmd}


def test_it_reads_one_esync_file_and_no_other():
    seen = []

    def read(path):
        seen.append(path)
        return json.dumps(ESYNC)

    io = SimpleNamespace(run=lambda c, timeout=10: None, read_file=read, statvfs=lambda p: vfs(), kernel_release=lambda: "k")
    ex.collect(ex.parse_args(["--out", "/x/ota.json"]), io)
    assert seen == ["/var/lib/esync/state.json", "/sys/fs/selinux/enforce"]


@pytest.mark.parametrize("name", ["--help", "-p", "-x", "a b", "a;b", "a\nb", "$(id)", "a/b", "", "x" * 300, "../x"])
def test_a_service_name_that_could_be_an_option_or_a_path_is_refused(name):
    with pytest.raises(SystemExit):
        ex.parse_args(["--out", "/x/o.json", "--service", name])


@pytest.mark.parametrize("name", ["esync", "candump", "cangen", "vehicletap", "getty@tty1", "systemd-resolved.service", "a_b"])
def test_ordinary_unit_names_are_fine(name):
    assert ex.parse_args(["--out", "/x/o.json", "--service", name]).service == [name]


def test_collecting_survives_every_source_failing():
    def boom(*a, **k):
        raise OSError("nope")

    io = SimpleNamespace(run=lambda c, timeout=10: None, read_file=boom, statvfs=boom, kernel_release=boom)
    src = ex.collect(ex.parse_args(["--out", "/x/o.json", "--service", "esync"]), io)
    d = ex.build(src, now=NOW, mono=MONO, boot=BOOT)
    assert d["os"]["booted"] is None and d["components"] == [] and d["services"][0]["active_state"] == "unknown"
    assert d["schema"] == 1


# ── the file ──

def test_the_file_is_written_whole_and_readable_by_the_container(tmp_path):
    path = tmp_path / "ota_status.json"
    doc = build()
    ex.write_atomic(str(path), doc)
    assert json.loads(path.read_text()) == doc
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644         # the container runs as another user
    assert sorted(os.listdir(tmp_path)) == ["ota_status.json"], "no temporary file left behind"
    assert path.read_text().endswith("\n")


def test_a_write_replaces_the_file_in_one_step_so_a_reader_never_sees_half_of_it(tmp_path, monkeypatch):
    path = tmp_path / "ota_status.json"
    path.write_text(json.dumps({"old": True}))
    replaced = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append((os.path.dirname(a), b)), real(a, b))[1])
    ex.write_atomic(str(path), build())
    assert replaced == [(str(tmp_path), str(path))], "the temporary file is in the same directory, so the rename is atomic"
    assert "old" not in json.loads(path.read_text())


def test_a_failed_write_leaves_the_old_file_and_no_litter(tmp_path, monkeypatch):
    path = tmp_path / "ota_status.json"
    path.write_text('{"keep": 1}')

    class Bad:
        pass

    with pytest.raises(TypeError):
        ex.write_atomic(str(path), {"x": Bad()})                # not serialisable
    assert json.loads(path.read_text()) == {"keep": 1}
    assert os.listdir(tmp_path) == ["ota_status.json"]


def test_a_directory_that_does_not_exist_is_an_error_not_created(tmp_path):
    with pytest.raises(OSError):
        ex.write_atomic(str(tmp_path / "nope" / "ota.json"), build())
    assert not (tmp_path / "nope").exists()


# ── the program ──

def fakes(monkeypatch):
    monkeypatch.setattr(ex, "run", lambda cmd, timeout=10: {"bootc": json.dumps(BOOTC), "timedatectl": HOST["ntp"]}.get(
        cmd[0], HOST["systemctl_show"]["esync"]))
    monkeypatch.setattr(ex, "read_file", lambda p: json.dumps(ESYNC) if "esync" in p else HOST["selinux_enforce"])
    monkeypatch.setattr(ex, "statvfs", lambda p: vfs())
    monkeypatch.setattr(ex, "kernel_release", lambda: HOST["kernel"])


def test_one_shot_writes_the_file_and_exits_zero(tmp_path, monkeypatch):
    fakes(monkeypatch)
    out = tmp_path / "ota_status.json"
    assert ex.main(["--out", str(out), "--service", "esync"]) == 0
    d = json.loads(out.read_text())
    assert d["schema"] == 1 and d["os"]["booted"]["version"] == "4.4.0" and d["services"][0]["name"] == "esync"
    assert ota.read(str(out), now=ota.parse_time(d["generated_at"]))["status"] == "ok"


def test_one_shot_exits_non_zero_when_it_cannot_write(tmp_path, monkeypatch, capsys):
    fakes(monkeypatch)
    assert ex.main(["--out", str(tmp_path / "nope" / "ota.json")]) == 1
    assert "cannot write" in capsys.readouterr().err


def test_interval_mode_keeps_going_after_a_bad_pass(tmp_path, monkeypatch, capsys):
    fakes(monkeypatch)
    out = tmp_path / "ota_status.json"
    calls = {"n": 0}
    real_write = ex.write_atomic

    def flaky(path, doc):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk hiccup")
        return real_write(path, doc)

    naps = []

    def nap(s):
        naps.append(s)
        if len(naps) == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(ex, "write_atomic", flaky)
    assert ex.main(["--out", str(out), "--interval", "30"], sleep=nap) == 0
    assert calls["n"] == 3 and naps == [30, 30, 30]
    assert out.exists() and "disk hiccup" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["0", "-5", "abc", "1.5", "99999999"])
def test_interval_must_be_a_sensible_number_of_seconds(bad):
    with pytest.raises(SystemExit):
        ex.parse_args(["--out", "/x/o.json", "--interval", bad])


def test_out_is_required():
    with pytest.raises(SystemExit):
        ex.parse_args([])


def test_the_script_is_standalone_it_imports_nothing_from_the_project():
    """It is copied to the board on its own; the project's modules are not there."""
    with open(os.path.join(ROOT, "tools", "ota_export.py")) as f:
        src = f.read()
    imported = {line.split()[1].split(".")[0] for line in src.splitlines() if line.startswith(("import ", "from "))}
    assert imported <= {"argparse", "json", "os", "re", "subprocess", "sys", "tempfile", "time", "collections",
                        "datetime", "__future__"}, imported
