#!/usr/bin/env python3
"""
ota_export.py — write the board's OTA status file for the dashboard (docs/OTA.md).

Runs on the HOST, not in the container: the dashboard container is --read-only with no `bootc`, no
`systemctl` and no view of the host, so this reads those and writes one small JSON file that the container
only reads. Standalone on purpose (standard library only, imports nothing from the project) so it can be
copied to a board on its own.

What it reads, and nothing else:

  bootc status --format json            the booted / staged / rollback images, whether a rollback is queued
  /var/lib/esync/state.json             the installed update components (the one eSync file it opens)
  systemctl show <unit> -p ...          for each --service: state, sub-state, start time, restart count
  timedatectl show -p NTPSynchronized   whether the clock is synchronised
  /sys/fs/selinux/enforce, uname, statvfs("/var")

It never changes anything: the commands it may run are the three above and are fixed, a --service name
cannot be an option or a path, and nothing is written but the output file (a temporary file beside it,
renamed over it, so a reader never sees half of one).

The document is built from named fields. The `bootc` output also carries the image registry and transport
and ostree checksums, and esync's state may carry more than a version: none of that is read out of its
input, so it cannot be in the output. The dashboard's reader whitelists again on the other side.

Usage:
  python3 ota_export.py --out /var/lib/vehicletap-ota/ota_status.json --service esync --service candump
  python3 ota_export.py --out FILE --service esync --interval 30      # keep it fresh; Ctrl-C to stop
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import namedtuple
from datetime import datetime, timezone

SCHEMA = 1
ESYNC_STATE = "/var/lib/esync/state.json"
SELINUX_FLAG = "/sys/fs/selinux/enforce"
TEXT_MAX = 120
INTERVAL_MAX = 86400
ACTIVE_STATES = ("active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance")

Vfs = namedtuple("Vfs", "f_frsize f_blocks f_bfree f_bavail")

_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_UNIT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,99}")
_SUB = re.compile(r"[a-z][a-z-]{0,39}")


def warn(msg):
    print(f"ota_export: {msg}", file=sys.stderr)


# ── small, pure helpers ──────────────────────────────────────────────────

def iso(epoch):
    """'2026-10-28T03:58:12Z' for epoch seconds."""
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_seconds(text):
    """An ISO-8601 time with a zone, cut to whole seconds ('...53.358191364Z' -> '...53Z'); '' if it is not one."""
    m = _TIME.fullmatch(text) if isinstance(text, str) else None
    if not m:
        return ""
    y, mo, d, h, mi, s = (int(g) for g in m.groups()[:6])
    zone = m.group(7)
    try:
        datetime(y, mo, d, h, mi, s)
        if zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
            return ""
    except ValueError:
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{zone}"


def text(v):
    return " ".join(v.split())[:TEXT_MAX] if isinstance(v, str) else ""


def digest(v):
    return v if isinstance(v, str) and _DIGEST.fullmatch(v) else ""


def image(deployment):
    """{version, digest, built_at} of one bootc deployment, or None. Not the registry, not the transport."""
    img = deployment.get("image") if isinstance(deployment, dict) else None
    if not isinstance(img, dict):
        return None
    out = {"version": text(img.get("version")), "digest": digest(img.get("imageDigest")),
           "built_at": iso_seconds(img.get("timestamp"))}
    return out if out["version"] or out["digest"] else None


def os_section(bootc, kernel, now, boot):
    status = bootc.get("status") if isinstance(bootc, dict) else None
    status = status if isinstance(status, dict) else {}
    return {"booted": image(status.get("booted")), "staged": image(status.get("staged")),
            "rollback": image(status.get("rollback")), "rollback_queued": status.get("rollbackQueued") is True,
            "kernel": text(kernel), "booted_at": iso(now - boot)}


def components(esync):
    out = []
    for name in sorted(esync) if isinstance(esync, dict) else []:
        entry = esync[name]
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            continue
        out.append({"id": text(name), "version": text(entry.get("version")),
                    "transaction_digest": digest(entry.get("transactionDigest")),
                    "installed_at": iso_seconds(entry.get("installedAt"))})
    return out


def service(name, show, now, mono):
    """One unit from `systemctl show` text. `since` is on the wall clock: the unit's monotonic start time is
    moved by how far the monotonic clock is from now."""
    props = {}
    for line in (show or "").splitlines():
        key, eq, value = line.partition("=")
        if eq and key:
            props[key] = value
    if props.get("LoadState") == "not-found":
        state, sub = "inactive", "not-found"
    else:
        state = props.get("ActiveState")
        state = state if state in ACTIVE_STATES else "unknown"
        sub = props.get("SubState", "")
        sub = sub if _SUB.fullmatch(sub) else ""
    enter = props.get("ActiveEnterTimestampMonotonic", "")
    since = iso(now - mono + int(enter) / 1e6) if enter.isdigit() and int(enter) > 0 else ""
    n = props.get("NRestarts", "")
    return {"name": name, "active_state": state, "sub_state": sub, "since": since,
            "restarts": int(n) if n.isdigit() else None}


def selinux_mode(flag):
    """`/sys/fs/selinux/enforce` holds 1 or 0; no such file means SELinux is not enabled."""
    if flag is None:
        return "disabled"
    return {"1": "enforcing", "0": "permissive"}.get(flag.strip(), "unknown")


def ntp_synced(show):
    value = (show or "").strip().partition("=")
    if value[0] != "NTPSynchronized":
        return None
    return {"yes": True, "no": False}.get(value[2])


def health(selinux, ntp, vfs):
    """The same percentage `df` prints: used / (used + available), so root-reserved blocks do not count."""
    used_pct = free = None
    if vfs is not None:
        used = (vfs.f_blocks - vfs.f_bfree) * vfs.f_frsize
        avail = vfs.f_bavail * vfs.f_frsize
        free = avail
        if used + avail > 0:
            used_pct = round(100.0 * used / (used + avail), 1)
    return {"selinux": selinux_mode(selinux), "ntp_synced": ntp_synced(ntp), "var_used_pct": used_pct,
            "var_free_bytes": free}


def build(src, now, mono, boot):
    """The status document from what was collected. `mono` and `boot` are the monotonic and boot-time clocks
    now; `now` is the wall clock."""
    units = src.get("units") or {}
    return {"schema": SCHEMA, "generated_at": iso(now),
            "os": os_section(src.get("bootc"), src.get("kernel"), now, boot),
            "components": components(src.get("esync")),
            "services": [service(n, units.get(n), now, mono) for n in units],
            "health": health(src.get("selinux"), src.get("ntp"), src.get("vfs"))}


# ── the only things that touch the host ──────────────────────────────────

def run(cmd, timeout=10):
    """stdout of a read-only command, or None if it cannot be run or fails."""
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        warn(f"{cmd[0]}: {e}")
        return None
    if r.returncode != 0:
        warn(f"{cmd[0]} exited {r.returncode}")
        return None
    return r.stdout


def read_file(path):
    """The file's text, None if it does not exist."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def statvfs(path):
    v = os.statvfs(path)
    return Vfs(v.f_frsize, v.f_blocks, v.f_bfree, v.f_bavail)


def kernel_release():
    return os.uname().release


def _json(raw, what):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        warn(f"{what} is not JSON")
        return None


def collect(args, io=None):
    """Everything the document is built from. `io` supplies the host (this module by default; tests pass a fake).
    A source that cannot be read is None and the rest still comes."""
    io = io or sys.modules[__name__]

    def attempt(what, fn, default=None):
        try:
            return fn()
        except Exception as e:                 # a broken source must not stop the others
            warn(f"{what}: {e}")
            return default

    units = {}
    for name in args.service:
        units[name] = io.run(["systemctl", "show", name, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState",
                              "-p", "ActiveEnterTimestampMonotonic", "-p", "NRestarts"])
    return {"bootc": _json(io.run(["bootc", "status", "--format", "json"]), "bootc status"),
            "esync": attempt("esync state", lambda: _json(io.read_file(args.esync_state), "esync state")),
            "kernel": attempt("kernel", io.kernel_release),
            "units": units,
            "selinux": attempt("selinux", lambda: io.read_file(SELINUX_FLAG), default=""),
            "ntp": io.run(["timedatectl", "show", "-p", "NTPSynchronized"]),
            "vfs": attempt("/var", lambda: io.statvfs("/var"))}


def write_atomic(path, doc):
    """Write `doc` to `path` so a reader sees the old file or the new one, never half. The temporary file is
    beside the target (same filesystem, so the rename is atomic) and the result is world-readable: the
    dashboard container runs as another user."""
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".ota_status.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── the program ──────────────────────────────────────────────────────────

def unit_name(value):
    """A systemd unit name. Not an option, not a path: it is passed to `systemctl show` as an argument."""
    if not _UNIT.fullmatch(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a plain unit name")
    return value


def seconds(value):
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number of seconds") from None
    if not 1 <= n <= INTERVAL_MAX:
        raise argparse.ArgumentTypeError(f"interval must be 1 to {INTERVAL_MAX} seconds")
    return n


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Write the board's OTA status file for the VehicleTap dashboard (docs/OTA.md).")
    p.add_argument("--out", required=True, help="the status file to write (its directory must exist)")
    p.add_argument("--service", action="append", type=unit_name, metavar="UNIT",
                   help="a systemd unit to report on; repeat for several")
    p.add_argument("--esync-state", default=ESYNC_STATE, metavar="FILE", help=f"eSync's component state (default {ESYNC_STATE})")
    p.add_argument("--interval", type=seconds, metavar="SECONDS", help="keep running, rewriting the file this often")
    args = p.parse_args(argv)
    args.service = args.service or []
    return args


def once(args):
    write_atomic(args.out, build(collect(args), now=time.time(), mono=time.monotonic(),
                                 boot=time.clock_gettime(time.CLOCK_BOOTTIME)))


def main(argv=None, sleep=time.sleep):
    args = parse_args(argv)
    if not args.interval:
        try:
            once(args)
        except OSError as e:
            warn(f"cannot write {args.out}: {e}")
            return 1
        return 0
    try:
        while True:
            try:
                once(args)
            except Exception as e:             # keep the file fresh through a bad pass
                warn(f"cannot write {args.out}: {e}")
            sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
