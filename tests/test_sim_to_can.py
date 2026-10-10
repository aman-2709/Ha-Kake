# SPDX-License-Identifier: AGPL-3.0-or-later
"""The channel guard of tools/sim_to_can.py: simulated frames only go where they should."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import sim_to_can  # noqa: E402


def link(up=True, kind="can", ctrl=(), bitrate=500000):
    data = {"ctrlmode": list(ctrl)}
    if bitrate:
        data["bittiming"] = {"bitrate": bitrate}
    return {"flags": ["NOARP", "UP"] if up else ["NOARP"],
            "linkinfo": {"info_kind": kind, "info_data": data}}


def check(channel, bench=True, **kw):
    return sim_to_can.check_channel(channel, bench, info=lambda ch: kw.get("info"))


def test_vcan_needs_nothing():
    assert sim_to_can.check_channel("vcan0", info=lambda ch: None) is None


def test_physical_channel_without_bench_is_refused():
    assert "--bench" in check("can0", bench=False, info=link())


def test_bench_with_a_good_link_is_allowed():
    assert check("can0", info=link()) is None


def test_missing_link_down_listen_only_and_wrong_bitrate_are_refused():
    assert "no such link" in check("can0", info=None)
    assert "down" in check("can0", info=link(up=False))
    assert "listen-only" in check("can0", info=link(ctrl=["LISTEN-ONLY"]))
    assert "expected 500000" in check("can0", info=link(bitrate=250000))
    assert "expected 500000" in check("can0", info=link(bitrate=None))
    assert "not a CAN" in check("eth0", info=link(kind="veth"))
