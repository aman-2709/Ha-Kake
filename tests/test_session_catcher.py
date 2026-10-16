# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
"""tools/mqtt_session_catcher.py: line format, rotation, low-disk pause."""
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mqtt_session_catcher as msc  # noqa: E402


def test_record_line_embeds_json_and_keeps_text():
    rec = json.loads(msc.record_line("hakake/leaf/car/status", b'{"online": true}'))
    assert rec == {"topic": "hakake/leaf/car/status", "payload": {"online": True}}
    rec = json.loads(msc.record_line("hakake/leaf/link/x", b"not json"))
    assert rec["payload"] == "not json"
    assert json.loads(msc.record_line("t", b""))["payload"] is None


def test_rotating_gzip_rolls_and_reads_back(tmp_path):
    now = [1_800_000_000.0]
    out = msc.RotatingGzip(str(tmp_path), rotate_s=60, min_free_mb=0, clock=lambda: now[0], log=lambda s: None)
    assert out.write("a\n")
    now[0] += 61
    assert out.write("b\n")
    out.close()
    files = sorted(os.listdir(tmp_path))
    assert len(files) == 2 and all(f.startswith("session-") and f.endswith(".jsonl.gz") for f in files)
    assert [gzip.open(tmp_path / f, "rt").read() for f in files] == ["a\n", "b\n"]


def test_pauses_on_low_disk_and_resumes(tmp_path):
    logs = []
    out = msc.RotatingGzip(str(tmp_path), rotate_s=60, min_free_mb=100, log=logs.append)
    out._free_mb = lambda: 10
    assert out.write("x\n") is False and out.paused
    assert out.write("y\n") is False and len(logs) == 1        # says so once
    out._free_mb = lambda: 1000
    assert out.write("z\n") is True and not out.paused
    out.close()
    assert [json.loads(s)["event"] for s in logs] == ["paused", "resumed"]
