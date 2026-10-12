#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 David D. Karnowski
# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Session catcher — record a bridge's MQTT stream unattended, for hours.

Subscribes to ``<prefix>/#`` on a broker and writes every message as one JSON
line, ``{"topic": ..., "payload": ...}`` — the same capture docs/MQTT.md makes
with ``mosquitto_sub -F``, so the files feed straight into

    python record_session.py --from-mqtt <file.jsonl> --vehicle leaf_ze0 --out drive.json
    python tools/compare_sessions.py expected.json <file.jsonl>

(gunzip first). Files are gzip-compressed and rotate every ``--rotate-min``
minutes into ``--out-dir`` as ``session-YYYYmmdd-HHMMSS.jsonl.gz`` (UTC). A
JSON stats line goes to stdout every ``--stats`` seconds: messages, rate,
bridge online/offline, broker connects — the persistence record of the run.

It only listens: it never publishes, so it cannot send anything on the car's bus.
It stops writing (and says so) when free disk falls under ``--min-free-mb``.

    python tools/mqtt_session_catcher.py --host 127.0.0.1 --port 1883 --out-dir ~/sessions
"""
import argparse
import gzip
import json
import os
import shutil
import signal
import sys
import threading
import time


def record_line(topic, payload_bytes):
    """One capture line. A JSON payload is embedded as JSON (as ``-F %p`` does);
    anything else is kept as a string, never dropped."""
    text = payload_bytes.decode("utf-8", "replace")
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = text
    return json.dumps({"topic": topic, "payload": payload}, separators=(",", ":")) + "\n"


class RotatingGzip:
    """gzip JSONL files that roll over every ``rotate_s`` seconds (and on close)."""

    def __init__(self, out_dir, rotate_s=3600, min_free_mb=2048, clock=time.time, log=print):
        self.out_dir, self.rotate_s, self.min_free_mb = out_dir, rotate_s, min_free_mb
        self.clock, self.log = clock, log
        self.f = None
        self.opened = 0.0
        self.path = None
        self.paused = False
        os.makedirs(out_dir, exist_ok=True)

    def _free_mb(self):
        return shutil.disk_usage(self.out_dir).free // (1024 * 1024)

    def _roll(self, now):
        self.close()
        name = time.strftime("session-%Y%m%d-%H%M%S.jsonl.gz", time.gmtime(now))
        self.path = os.path.join(self.out_dir, name)
        self.f = gzip.open(self.path, "at", compresslevel=6)
        self.opened = now

    def write(self, line):
        now = self.clock()
        if self.f is None or now - self.opened >= self.rotate_s:
            free = self._free_mb()
            if free < self.min_free_mb:
                if not self.paused:
                    self.log(json.dumps({"event": "paused", "reason": "low disk", "free_mb": free}))
                self.close()
                self.paused = True
                return False
            if self.paused:
                self.log(json.dumps({"event": "resumed", "free_mb": free}))
            self.paused = False
            self._roll(now)
        self.f.write(line)
        return True

    def close(self):
        if self.f is not None:
            self.f.close()
            self.f = None


class Catcher:
    def __init__(self, args, log=print):
        self.args, self.log = args, log
        self.out = RotatingGzip(args.out_dir, args.rotate_min * 60, args.min_free_mb, log=log)
        self.lock = threading.Lock()
        self.msgs = self.window = self.written = self.connects = 0
        self.bridge_online = None
        self.started = time.time()

    def on_connect(self, client, userdata, flags, rc, props=None):
        self.connects += 1
        client.subscribe(f"{self.args.prefix}/#", qos=0)
        self.log(json.dumps({"event": "connected", "rc": str(rc), "connects": self.connects,
                             "t": round(time.time(), 3)}))

    def on_disconnect(self, client, userdata, *a):
        self.log(json.dumps({"event": "disconnected", "t": round(time.time(), 3)}))

    def on_message(self, client, userdata, msg):
        line = record_line(msg.topic, msg.payload)
        if msg.topic.endswith("/status"):
            try:
                self.bridge_online = bool(json.loads(msg.payload).get("online"))
            except (ValueError, AttributeError):
                pass
        with self.lock:
            self.msgs += 1
            self.window += 1
            if self.out.write(line):
                self.written += 1

    def stats(self, period):
        with self.lock:
            n, self.window = self.window, 0
            rec = {"event": "stats", "t": round(time.time(), 3), "up_s": int(time.time() - self.started),
                   "msgs": self.msgs, "written": self.written, "rate": round(n / period, 1),
                   "bridge_online": self.bridge_online, "connects": self.connects,
                   "file": os.path.basename(self.out.path) if self.out.path else None,
                   "paused": self.out.paused}
        self.log(json.dumps(rec))

    def close(self):
        with self.lock:
            self.out.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--prefix", default="hakake/leaf")
    ap.add_argument("--out-dir", default=None,
                    help="where the session files go (default: a sessions/ folder in the Ha-Kake data folder)")
    ap.add_argument("--rotate-min", type=int, default=60)
    ap.add_argument("--min-free-mb", type=int, default=2048)
    ap.add_argument("--stats", type=float, default=60.0, help="stats line period, seconds")
    args = ap.parse_args(argv)

    import paho.mqtt.client as mqtt
    log = lambda s: print(s, flush=True)
    if not args.out_dir:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import datadir
        args.out_dir = datadir.path("sessions")
    c = Catcher(args, log=log)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"hakake-catcher-{os.getpid()}")
    client.on_connect, client.on_disconnect, client.on_message = c.on_connect, c.on_disconnect, c.on_message
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log(json.dumps({"event": "start", "broker": f"{args.host}:{args.port}", "prefix": args.prefix,
                    "out_dir": args.out_dir}))
    client.connect_async(args.host, args.port, keepalive=30)
    client.loop_start()
    try:
        while not stop.wait(args.stats):
            c.stats(args.stats)
    finally:
        client.loop_stop()
        c.close()
        c.stats(args.stats)
        log(json.dumps({"event": "stop"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
