#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Put the simulated car's ECUs on a SocketCAN device (`vcan0`, or a bench `can0`).

    sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0   # once
    python tools/sim_to_can.py                        # Car-CAN, ~1,700 frames/s
    candump vcan0                                     # in another terminal

On a physical adapter (the bench: a CANable wired to an ELM327 dongle, no car):

    sudo ip link set can0 down && sudo ip link set can0 type can bitrate 500000
    sudo ip link set can0 up
    python tools/sim_to_can.py --channel can0 --bench

`--adapter sim --sim-can` keeps the same ECUs on an in-process python-can
`virtual` channel that no other process can see. This puts them on a kernel
CAN device instead, so `candump`, the dashboard's `--adapter can` path
(`can_interface: socketcan`, `can_channel: vcan0`) or any other tool can read
them.

The simulator's control API runs beside it (127.0.0.1:8099, `--control PORT`,
`--no-control`), so the cockpit can drive this very process: open
`http://127.0.0.1:5000/sim?control=http://127.0.0.1:8099` on any dashboard. Gear,
speed, lights and faults then change the frames on the bus. A running
`--scenario` writes the same knobs on its own timeline, so leave it off for the cockpit.

Every frame is ASSERTED / simulated (see `simulator/canbus.py`).

A physical channel needs `--bench` (or the controller in loopback mode, where
nothing reaches the wire), and is refused unless the link is up, in
normal (not listen-only) mode, at the expected bitrate. This tool TRANSMITS
fake ECU frames. Never run it with the adapter plugged into a car: the car's
own modules would hear a second battery pack on their bus. A bus with only one
node on it gets no ACK, so the frames go nowhere; the second node is the
ELM327 dongle (or any other CAN node) on the bench harness.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import can  # noqa: E402

from simulator import make_sim  # noqa: E402
from simulator.canbus import SimCanEcu  # noqa: E402


def link_info(channel):
    """`ip -j -d link show CHANNEL` as a dict, or None if there is no such link."""
    try:
        out = subprocess.run(["ip", "-j", "-d", "link", "show", channel], capture_output=True,
                             text=True, timeout=5, check=True).stdout
        return json.loads(out)[0]
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def check_channel(channel, bench=False, bitrate=500000, info=link_info):
    """Return None if the channel may carry simulated frames, else the reason it may not.

    `vcan*` is always fine. Anything else needs `--bench` and a link that is up,
    in normal mode, at `bitrate`. The kernel only reports a bitrate once one is set."""
    if channel.startswith("vcan"):
        return None
    link = info(channel)
    data = ((link or {}).get("linkinfo") or {}).get("info_data") or {}
    ctrl = data.get("ctrlmode") or []
    loop = "LOOPBACK" in ctrl and "UP" in ((link or {}).get("flags") or [])
    if not bench and not loop:
        return (f"refusing {channel!r}: simulated frames on a physical adapter need --bench "
                "(bench harness, never a car) or the controller in loopback mode "
                f"(sudo ip link set {channel} type can bitrate {bitrate} loopback on)")
    if link is None:
        return f"no such link {channel!r} (is the adapter plugged in?)"
    if link["linkinfo"].get("info_kind") != "can":
        return f"{channel!r} is not a CAN device"
    if "UP" not in (link.get("flags") or []):
        return f"{channel!r} is down: sudo ip link set {channel} type can bitrate {bitrate}; sudo ip link set {channel} up"
    if "LISTEN-ONLY" in ctrl:
        return f"{channel!r} is in listen-only mode and cannot transmit; drop 'listen-only on'"
    got = (data.get("bittiming") or {}).get("bitrate")
    if got != bitrate:
        return f"{channel!r} is at {got} bit/s, expected {bitrate}"
    return None


def start_control(sim, port, lock, log=print):
    """Serve the simulator's control API on 127.0.0.1:port. Returns (server, bound_port).

    A busy port falls back to a free one, and says so, rather than failing a run
    that is otherwise fine (a dashboard's own simulator may already hold 8099)."""
    from hakake_sim import serve_control      # lazy: utility, not a dependency
    try:
        httpd = serve_control(sim, port, lock=lock, log=log)
    except OSError as e:
        if port == 0:
            raise
        httpd = serve_control(sim, 0, lock=lock, log=log)
        log(f"  *** control port {port} is busy ({e.strerror or e}); serving on "
            f"{httpd.server_address[1]} instead ***")
    return httpd, httpd.server_address[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", default="vcan0", help="SocketCAN device (default vcan0)")
    ap.add_argument("--bench", action="store_true",
                    help="allow a physical adapter (bench harness only, never a car)")
    ap.add_argument("--bitrate", type=int, default=500000,
                    help="bitrate the physical link must already be set to (default 500000)")
    ap.add_argument("--bus", choices=["car", "ev"], default="car",
                    help="which bus's frames to emit (ev has no UDS responder)")
    ap.add_argument("--vehicle", default=None)
    ap.add_argument("--scenario", default=None)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--speed", type=float, default=None,
                    help="time scaling for the scenario (10 = ten times real time)")
    ap.add_argument("--control", type=int, default=8099, metavar="PORT",
                    help="simulator control API port on 127.0.0.1 (default 8099; 0 = any free port)")
    ap.add_argument("--no-control", action="store_true", help="do not serve the control API")
    ap.add_argument("--knob", action="append", default=[], metavar="NAME=VALUE")
    args = ap.parse_args()

    why = check_channel(args.channel, args.bench, args.bitrate)
    if why:
        sys.exit(why)
    if not args.channel.startswith("vcan"):
        print("BENCH MODE: transmitting simulated ECU frames on a physical adapter. "
              "Unplug it from any car NOW; starting in 3 s.")
        time.sleep(3)

    knobs = {}
    for kv in args.knob:
        k, _, v = kv.partition("=")
        knobs[k] = {"true": True, "false": False}.get(v.lower(), v)
        if isinstance(knobs[k], str):
            try:
                knobs[k] = float(v)
            except ValueError:
                pass

    sim = make_sim(vehicle=args.vehicle, knobs=knobs or None, seed=args.seed, scenario=args.scenario,
                   speed=args.speed)
    ecu = SimCanEcu(sim, bus=args.bus, clock=True, log=print,
                    bus_factory=lambda: can.Bus(interface="socketcan", channel=args.channel,
                                                receive_own_messages=False))
    ecu.start()
    httpd = None
    if not args.no_control:
        httpd, port = start_control(sim, args.control, ecu.lock)
        print(f"  control API  http://127.0.0.1:{port}/sim/schema\n"
              f"  cockpit      http://127.0.0.1:5000/sim?control=http://127.0.0.1:{port}"
              "   (any running dashboard's /sim page)")
    print(f"simulated {args.bus}-CAN on {args.channel}, ~{ecu.expected_fps():.0f} frames/s expected; Ctrl-C stops")
    try:
        while True:
            time.sleep(2)
            print(f"  sent {ecu.sent} frames, {len(ecu.requests)} UDS requests heard")
    except KeyboardInterrupt:
        pass
    finally:
        if httpd:
            httpd.shutdown()
        ecu.stop()


if __name__ == "__main__":
    main()
