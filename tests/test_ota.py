"""The OTA status file: what the dashboard reads from the host (docs/OTA.md).

The file is written by a process outside the container (tools/ota_export.py on the board), so it is
input from another trust domain: every key is whitelisted, every string cleaned and capped, every
number checked, and nothing here may raise. A missing file is "waiting", a broken one "invalid", an old
one "stale" -- never a 500.
"""
import copy
import json
import math

import pytest

from conftest import fixture

import ota  # noqa: E402  (web/ is on sys.path via conftest)

NOW = 1_790_000_000.0                      # an arbitrary "now" for the injected clock
GOOD = fixture("ota/status_v1.json")


def at(offset_s=0.0):
    """A generated_at string `offset_s` seconds before NOW (negative = in the future)."""
    t = ota.format_time(NOW - offset_s)
    assert ota.parse_time(t) == int(NOW - offset_s)
    return t


def good(**over):
    d = copy.deepcopy(GOOD)
    d["generated_at"] = at(5)
    d.update(over)
    return d


def write(tmp_path, obj, name="ota_status.json"):
    p = tmp_path / name
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj))
    return str(p)


# ── the clock: ISO-8601 in, epoch out, no dependency on Python 3.11's parser ──

@pytest.mark.parametrize("text,epoch", [
    ("2026-08-07T23:03:53Z", 1786143833),
    ("2026-08-07T23:03:53.358191364Z", 1786143833),        # bootc writes nanoseconds
    ("2026-08-07T16:03:53-07:00", 1786143833),
    ("2026-08-08T01:03:53+02:00", 1786143833),
])
def test_parse_time_accepts_iso_8601_with_a_zone(text, epoch):
    assert ota.parse_time(text) == epoch


@pytest.mark.parametrize("text", [
    "", None, 5, "yesterday", "2026-08-07", "2026-08-07 23:03:53Z", "2026-13-07T23:03:53Z",
    "2026-08-07T25:03:53Z", "2026-08-07T23:03:53", "2026-08-07T23:03:53+25:00", "2026-02-30T00:00:00Z",
    "Z" * 4000,
])
def test_parse_time_refuses_everything_else(text):
    assert ota.parse_time(text) is None


def test_format_time_round_trips():
    assert ota.format_time(1786143833) == "2026-08-07T23:03:53Z"
    assert ota.parse_time(ota.format_time(NOW)) == int(NOW)


# ── where the file is ──

def test_the_path_is_the_environment_variable_else_the_data_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("VEHICLETAP_OTA_FILE", raising=False)
    import datadir
    assert ota.path() == datadir.path("ota_status.json")
    monkeypatch.setenv("VEHICLETAP_OTA_FILE", str(tmp_path / "elsewhere.json"))
    assert ota.path() == str(tmp_path / "elsewhere.json")
    monkeypatch.setenv("VEHICLETAP_OTA_FILE", "")                 # empty is unset (util.env)
    assert ota.path() == datadir.path("ota_status.json")


# ── the three states that are not "ok" ──

def test_a_missing_file_is_waiting_and_says_how_to_fill_it(tmp_path):
    out = ota.read(str(tmp_path / "nope.json"), now=NOW)
    assert out["status"] == "waiting" and out["age_s"] is None
    assert "ota_export" in out["message"] and "docs/OTA.md" in out["message"]
    assert "os" not in out and "components" not in out


@pytest.mark.parametrize("content", ["", "{", '{"schema": 1,', "not json", "null", "[]", "42", '"str"', "\x00\x01"])
def test_a_file_that_is_not_a_json_object_is_invalid_not_an_error(tmp_path, content):
    out = ota.read(write(tmp_path, content), now=NOW)
    assert out["status"] == "invalid" and out["message"]
    assert "os" not in out


def test_deeply_nested_json_is_invalid_not_a_crash(tmp_path):
    """Well under the size cap, but deep enough to exhaust the parser's recursion limit."""
    nested = "[" * 30_000 + "]" * 30_000
    assert len(nested) < ota.FILE_MAX
    assert ota.read(write(tmp_path, nested), now=NOW)["status"] == "invalid"


def test_a_pipe_or_other_special_file_is_refused_without_blocking(tmp_path):
    import os
    fifo = str(tmp_path / "fifo")
    os.mkfifo(fifo)
    out = ota.read(fifo, now=NOW)                         # would hang forever if it were opened for reading
    assert out["status"] == "invalid" and "regular" in out["message"]


def test_a_path_that_cannot_be_read_is_invalid_not_an_error(tmp_path):
    d = tmp_path / "a_directory"
    d.mkdir()
    out = ota.read(str(d), now=NOW)
    assert out["status"] == "invalid" and "read" in out["message"]


def test_an_oversize_file_is_refused_without_parsing_it(tmp_path):
    pad = " " * (ota.FILE_MAX + 1)
    out = ota.read(write(tmp_path, json.dumps(good()) + pad), now=NOW)
    assert out["status"] == "invalid" and "large" in out["message"]
    just_under = json.dumps(good())
    assert len(just_under) < ota.FILE_MAX
    assert ota.read(write(tmp_path, just_under), now=NOW)["status"] == "ok"


@pytest.mark.parametrize("schema", [None, 0, 2, "1", 1.5, True, [1]])
def test_an_unknown_schema_is_invalid(tmp_path, schema):
    d = good()
    d["schema"] = schema
    out = ota.read(write(tmp_path, d), now=NOW)
    assert out["status"] == "invalid" and "schema" in out["message"]


def test_a_missing_schema_is_invalid(tmp_path):
    d = good()
    del d["schema"]
    assert ota.read(write(tmp_path, d), now=NOW)["status"] == "invalid"


@pytest.mark.parametrize("stamp", [None, "", "soon", 1790000000, "2026-08-07", "2026-13-01T00:00:00Z"])
def test_a_file_that_does_not_say_when_it_was_written_is_invalid(tmp_path, stamp):
    d = good()
    d["generated_at"] = stamp
    out = ota.read(write(tmp_path, d), now=NOW)
    assert out["status"] == "invalid" and "generated_at" in out["message"]


def test_a_fresh_file_is_ok_with_its_age(tmp_path):
    out = ota.read(write(tmp_path, good()), now=NOW)
    assert out["status"] == "ok" and out["age_s"] == 5
    assert out["schema"] == 1 and out["generated_at"] == at(5)


def test_an_old_file_is_stale_but_still_shown(tmp_path):
    d = good(generated_at=at(ota.STALE_AFTER_S + 1))
    out = ota.read(write(tmp_path, d), now=NOW)
    assert out["status"] == "stale" and out["age_s"] == ota.STALE_AFTER_S + 1
    assert out["os"]["booted"]["version"] == GOOD["os"]["booted"]["version"]    # the last known state, labelled
    assert "ago" in out["message"] or "old" in out["message"]
    on_the_line = good(generated_at=at(ota.STALE_AFTER_S))
    assert ota.read(write(tmp_path, on_the_line, "b.json"), now=NOW)["status"] == "ok"


def test_a_timestamp_in_the_future_is_stale_not_trusted(tmp_path):
    out = ota.read(write(tmp_path, good(generated_at=at(-ota.SKEW_S - 5))), now=NOW)
    assert out["status"] == "stale" and "ahead" in out["message"]
    near = ota.read(write(tmp_path, good(generated_at=at(-ota.SKEW_S + 5)), "b.json"), now=NOW)
    assert near["status"] == "ok" and near["age_s"] == 0       # small skew: clamped, never negative


def test_each_read_stands_alone(tmp_path):
    p = write(tmp_path, good())
    assert ota.read(p, now=NOW)["status"] == "ok"
    write(tmp_path, "{")
    again = ota.read(p, now=NOW)
    assert again["status"] == "invalid" and "os" not in again, "an invalid file must not show the last good one"


# ── the whitelist: nothing the exporter did not mean to say gets through ──

POISON = ["ghcr.example/secret/image", "apikey-0123", "tok_live_abc", "192.0.2.7", "serial-SYNTH-0001", "hostname.corp"]


def poisoned():
    d = good()
    d["apikey"] = POISON[1]
    d["os"]["spec"] = {"image": POISON[0], "transport": "registry"}
    d["os"]["booted"]["image"] = POISON[0]
    d["os"]["booted"]["registry"] = POISON[0]
    d["os"]["rollback"]["transport"] = "registry"
    d["components"][0]["token"] = POISON[2]
    d["components"][0]["device_id"] = POISON[4]
    d["services"][0]["exec_start"] = f"/usr/bin/x --key={POISON[1]}"
    d["services"][0]["host"] = POISON[3]
    d["health"]["hostname"] = POISON[5]
    return d


def test_keys_that_are_not_in_the_schema_are_dropped_at_every_level(tmp_path):
    out = ota.read(write(tmp_path, poisoned()), now=NOW)
    assert out["status"] == "ok"
    blob = json.dumps(out)
    for secret in POISON:
        assert secret not in blob, secret
    assert set(out) == {"status", "age_s", "message", "schema", "generated_at", "os", "components", "services",
                        "health", "next_boot"}
    assert set(out["os"]["booted"]) == {"version", "digest", "built_at"}
    assert set(out["components"][0]) == {"id", "version", "transaction_digest", "installed_at"}
    assert set(out["services"][0]) == {"name", "active_state", "sub_state", "since", "restarts"}
    assert set(out["health"]) == {"selinux", "ntp_synced", "var_used_pct", "var_free_bytes"}
    assert set(out["os"]) == {"booted", "staged", "rollback", "rollback_queued", "kernel", "booted_at"}


def test_a_string_in_an_image_field_is_cleaned_not_trusted():
    d = good()
    d["os"]["booted"]["version"] = "4.4.0\n<script>alert(1)</script>​‮"
    out = ota.clean(d)
    v = out["os"]["booted"]["version"]
    assert "\n" not in v and "​" not in v and "‮" not in v
    assert len(v) <= ota.TEXT_MAX
    # markup is left alone here (this is data); the page renders with textContent -- tests/test_html_escape.py


def test_strings_are_capped():
    d = good()
    d["os"]["kernel"] = "k" * 5000
    d["components"][0]["id"] = "c" * 5000
    out = ota.clean(d)
    assert len(out["os"]["kernel"]) <= ota.TEXT_MAX and len(out["components"][0]["id"]) <= ota.TEXT_MAX


@pytest.mark.parametrize("digest,kept", [
    ("sha256:" + "ab" * 32, True),
    ("sha256:" + "AB" * 32, False),                       # the form tools print is lower case
    ("sha256:" + "ab" * 31, False), ("sha256:" + "zz" * 32, False), ("md5:abc", False),
    ("ab" * 32, False), ("", False), (None, False), (12, False), ("sha256:" + "ab" * 32 + "\n", False),
])
def test_a_digest_is_kept_only_in_the_one_form_a_digest_has(digest, kept):
    d = good()
    d["os"]["booted"]["digest"] = digest
    out = ota.clean(d)["os"]["booted"]["digest"]
    assert (out == digest) if kept else (out == "")


def test_times_are_kept_only_when_they_are_times():
    d = good()
    d["os"]["booted_at"] = "not a time"
    d["os"]["booted"]["built_at"] = "2026-08-07T23:03:53.358191364Z"
    d["components"][0]["installed_at"] = "2026-13-45T00:00:00Z"
    d["services"][0]["since"] = "Tue 2026-10-27 23:47:46 UTC"       # systemd's own format is not ours
    out = ota.clean(d)
    assert out["os"]["booted_at"] == ""
    assert out["os"]["booted"]["built_at"] == "2026-08-07T23:03:53.358191364Z"
    assert out["components"][0]["installed_at"] == ""
    assert out["services"][0]["since"] == ""


def test_an_image_with_neither_version_nor_digest_is_nothing():
    d = good()
    d["os"]["staged"] = {"built_at": at(1)}
    d["os"]["rollback"] = {}
    d["os"]["booted"] = "4.4.0"
    out = ota.clean(d)["os"]
    assert out["staged"] is None and out["rollback"] is None and out["booted"] is None


def test_enumerations_are_checked():
    d = good()
    d["services"][0]["active_state"] = "<b>active</b>"
    d["services"][1]["active_state"] = "failed"
    d["health"]["selinux"] = "Enforcing"                  # case matters: the exporter lower-cases it
    out = ota.clean(d)
    assert out["services"][0]["active_state"] == "unknown" and out["services"][1]["active_state"] == "failed"
    assert out["health"]["selinux"] == "unknown"
    d["health"]["selinux"] = "permissive"
    assert ota.clean(d)["health"]["selinux"] == "permissive"


@pytest.mark.parametrize("bad", [-1, 1.5, "3", None, True, float("nan"), 10 ** 9, [1]])
def test_a_restart_count_is_a_small_non_negative_integer_or_nothing(bad):
    d = good()
    d["services"][0]["restarts"] = bad
    assert ota.clean(d)["services"][0]["restarts"] is None


def test_a_restart_count_that_is_good_is_kept():
    d = good()
    d["services"][0]["restarts"] = 3
    assert ota.clean(d)["services"][0]["restarts"] == 3


@pytest.mark.parametrize("bad", [-0.1, 100.1, float("nan"), float("inf"), "25", None, True, [25]])
def test_a_percentage_outside_zero_to_a_hundred_is_nothing(bad):
    d = good()
    d["health"]["var_used_pct"] = bad
    assert ota.clean(d)["health"]["var_used_pct"] is None


def test_health_numbers_that_are_good_are_kept():
    d = good()
    d["health"].update(var_used_pct=25.4, var_free_bytes=22_000_000_000, ntp_synced=True)
    h = ota.clean(d)["health"]
    assert h["var_used_pct"] == 25.4 and h["var_free_bytes"] == 22_000_000_000 and h["ntp_synced"] is True
    d["health"].update(var_free_bytes=-5, ntp_synced="yes")
    h = ota.clean(d)["health"]
    assert h["var_free_bytes"] is None and h["ntp_synced"] is None, "only a real boolean counts"


def test_a_queued_rollback_needs_a_real_true():
    for v, want in [(True, True), (False, False), ("true", False), (1, False), (None, False)]:
        d = good()
        d["os"]["rollback_queued"] = v
        assert ota.clean(d)["os"]["rollback_queued"] is want, v


def test_lists_are_capped_and_junk_entries_skipped():
    d = good()
    d["components"] = [{"id": f"c{i}", "version": "1"} for i in range(ota.LIST_MAX + 40)] + [None, 5, "x", [], {}]
    d["services"] = [{"name": f"s{i}"} for i in range(ota.LIST_MAX + 40)] + [{"name": ""}, {"active_state": "active"}]
    out = ota.clean(d)
    assert len(out["components"]) == ota.LIST_MAX and len(out["services"]) == ota.LIST_MAX
    assert all(c["id"] for c in out["components"]) and all(s["name"] for s in out["services"])
    d["components"] = "not a list"
    d["services"] = {"name": "esync"}
    out = ota.clean(d)
    assert out["components"] == [] and out["services"] == []


def test_sections_that_are_missing_or_the_wrong_type_come_out_empty_not_broken():
    for section in ("os", "components", "services", "health"):
        for junk in (None, 5, "x", [], [1, 2]):
            d = good()
            d[section] = junk
            out = ota.clean(d)
            assert set(out) >= {"os", "components", "services", "health"}
    minimal = ota.clean({"schema": 1, "generated_at": at(1)})
    assert minimal["os"]["booted"] is None and minimal["components"] == [] and minimal["services"] == []
    assert minimal["health"]["selinux"] == "unknown" and minimal["health"]["ntp_synced"] is None


@pytest.mark.parametrize("junk", [None, 0, 1, -1, 1.5, float("nan"), float("inf"), "", "x", "x" * 10_000, True, [], {}, [None],
                                  {"a": {"b": [1, {"c": None}]}}, "\x00", "�"])
def test_junk_in_every_field_never_raises(junk):
    def fuzz(node):
        if isinstance(node, dict):
            return {k: fuzz(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fuzz(v) for v in node]
        return junk
    d = fuzz(good())
    d["schema"], d["generated_at"] = 1, at(1)
    out = ota.view(d, now=NOW)
    assert out["status"] in ("ok", "stale", "invalid")
    json.dumps(out, allow_nan=False)                      # whatever comes out is valid JSON, no NaN


def test_the_payload_is_strict_json(tmp_path):
    out = ota.read(write(tmp_path, good()), now=NOW)
    assert json.loads(json.dumps(out, allow_nan=False)) == out
    assert not any(isinstance(v, float) and not math.isfinite(v) for v in out.values())


# ── the one derived field: what the board will boot next ──

def nb(**os_over):
    d = good()
    d["os"].update(os_over)
    return ota.clean(d)["next_boot"]


def test_next_boot_is_the_booted_image_when_nothing_is_queued():
    n = nb(staged=None, rollback_queued=False)
    assert n["source"] == "booted" and n["version"] == GOOD["os"]["booted"]["version"]


def test_next_boot_is_the_staged_image_when_an_update_is_waiting():
    n = nb(staged={"version": "9.9.9", "digest": "sha256:" + "cd" * 32}, rollback_queued=False)
    assert n["source"] == "staged" and n["version"] == "9.9.9" and n["digest"] == "sha256:" + "cd" * 32


def test_next_boot_is_the_rollback_image_when_a_rollback_is_queued():
    """`bootc rollback` queues the deployment under `rollback` for the next boot (bootc 1.16.6 help text)."""
    n = nb(staged=None, rollback_queued=True)
    assert n["source"] == "rollback" and n["version"] == GOOD["os"]["rollback"]["version"]


def test_a_queued_rollback_discards_a_staged_update_so_staged_does_not_win_over_it():
    """bootc's own rule: queuing a rollback discards a staged entry. If a file claims both, trust the queue."""
    n = nb(staged={"version": "9.9.9"}, rollback_queued=True)
    assert n["source"] == "rollback"


def test_next_boot_is_nothing_when_no_image_is_known():
    d = good()
    d["os"] = {}
    assert ota.clean(d)["next_boot"] is None
    d["os"] = {"rollback_queued": True}                   # queued, but there is no rollback image to name
    assert ota.clean(d)["next_boot"] is None


def test_a_queued_rollback_with_no_rollback_image_falls_back_to_booted():
    n = nb(rollback=None, staged=None, rollback_queued=True)
    assert n["source"] == "booted"


# ── the file the repo ships for demos and docs ──

def test_the_demo_file_is_a_valid_current_schema_file():
    import os
    from conftest import ROOT
    with open(os.path.join(ROOT, "docs", "demo", "ota.json")) as f:
        raw = json.load(f)
    raw["generated_at"] = at(1)
    out = ota.view(raw, now=NOW)
    assert out["status"] == "ok" and out["os"]["booted"]["version"]
    assert out["components"] and out["services"]


def test_the_fixture_is_clean_as_it_stands():
    """Nothing in the shipped sample is dropped: the whitelist and the sample agree."""
    cleaned = ota.clean(GOOD)
    for k in ("booted", "rollback"):
        assert cleaned["os"][k] == GOOD["os"][k]
    assert cleaned["os"]["staged"] is None
    assert cleaned["components"] == GOOD["components"]
    assert cleaned["services"] == GOOD["services"]
    assert cleaned["health"] == GOOD["health"]
    assert {k: cleaned["os"][k] for k in ("rollback_queued", "kernel", "booted_at")} == \
        {k: GOOD["os"][k] for k in ("rollback_queued", "kernel", "booted_at")}
