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


def test_loopback_needs_no_bench_flag_but_still_a_good_link():
    assert check("can0", bench=False, info=link(ctrl=["LOOPBACK"])) is None
    assert "expected 500000" in check("can0", bench=False, info=link(ctrl=["LOOPBACK"], bitrate=250000))
    assert "--bench" in check("can0", bench=False, info=link(up=False, ctrl=["LOOPBACK"]))


def test_speed_flag_scales_the_simulated_clock():
    from simulator import make_sim
    assert make_sim(scenario="drive", seed=1, speed=None).time_scale() == 1.0
    assert make_sim(scenario="drive", seed=1, speed=10).time_scale() == 10.0


def test_the_control_api_drives_the_model_the_bus_is_sending():
    """POST /sim/knobs on the tool's control port changes the sim the ECUs read, under their lock."""
    import json
    import threading
    import urllib.request
    from simulator import make_sim
    sim = make_sim(seed=1)
    httpd, port = sim_to_can.start_control(sim, 0, threading.RLock(), log=lambda *_: None)
    try:
        base = f"http://127.0.0.1:{port}"
        assert "knobs" in json.load(urllib.request.urlopen(base + "/sim/schema"))
        req = urllib.request.Request(base + "/sim/knobs", data=json.dumps({"gear": "R"}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)
        assert sim.get_knobs()["gear"] == "R"
    finally:
        httpd.shutdown()


def test_a_busy_control_port_falls_back_to_a_free_one():
    import threading
    from simulator import make_sim
    sim, lock, log = make_sim(seed=1), threading.RLock(), []
    first, p1 = sim_to_can.start_control(sim, 0, lock, log=lambda *_: None)
    try:
        second, p2 = sim_to_can.start_control(sim, p1, lock, log=log.append)
        second.shutdown()
        assert p2 != p1 and any("busy" in m for m in log)
    finally:
        first.shutdown()


def test_a_peer_that_hangs_up_prints_no_traceback(capsys):
    """A browser resets its idle keep-alive socket; the control server must not shout about it."""
    import socket
    import struct
    import threading
    import time
    from simulator import make_sim
    httpd, port = sim_to_can.start_control(make_sim(seed=1), 0, threading.RLock(), log=lambda *_: None)
    try:
        s = socket.create_connection(("127.0.0.1", port))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))   # close sends RST
        s.close()
        time.sleep(0.5)
    finally:
        httpd.shutdown()
    assert "Traceback" not in capsys.readouterr().err
