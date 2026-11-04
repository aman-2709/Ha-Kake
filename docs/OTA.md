# OTA status: the file the dashboard reads

The board VehicleTap runs on can tell you which operating-system image it booted, what is waiting behind it, which
update components are installed and whether the services around them are up. The dashboard container cannot see
any of that itself: it runs `--read-only --cap-drop all`, with no `bootc`, no `systemctl` and no view of the host's
`/etc/os-release` or SELinux. So a process **on the host** writes one small JSON file, and the app only reads it.
Nothing in the app can change the board's state, and nothing here sends anything to a car.

This page is the contract for that file. It covers the file, the reader (`web/ota.py`), the endpoint, the page and
the host-side exporter (`tools/ota_export.py`).

## The endpoint and the page

| | |
|---|---|
| `GET /api/ota` | `ota.read()` as JSON. **Always 200**: a missing, broken or old file is a `status` in the body, not an error. The path is never taken from the request. |
| `GET /ota` | the page. It renders no board data itself; `web/static/ota.js` asks `/api/ota` every 5 s and writes the answer with `textContent`. |
| Other methods | 405. Nothing in the app can change the board. |
| `--demo` | serves `docs/demo/ota.json`, re-stamped so it looks current, with `demo: true`; the real file is never opened. |

The page shows the booted, staged and rollback images side by side with the rows that differ highlighted, the update
components, the services and the health facts. When a reboot would start an image other than the one running, a
one-sentence warning sits above the images, for example *A reboot would start 4.5.0, not the running 4.4.0 (queued
rollback).* It says nothing when nothing is queued or staged, and names an image by its digest if it has no version.
A banner says what `waiting`, `invalid` and `stale` mean; `stale` still shows the last state, labelled with its age.
The page is about the board, so it does not carry the vehicle's name. The dashboard header has an **OTA** link to it.

## Where the file is

| | |
|---|---|
| Default | `ota_status.json` in the data folder ([DATA.md](DATA.md)) |
| Override | `VEHICLETAP_OTA_FILE=/path/to/ota_status.json` |
| Size limit | 64 KB, refused unparsed beyond that (a real file is about 1 KB) |

Dropping a sample file into the data folder is the whole setup on a laptop. `docs/demo/ota.json` is a complete one.

## Schema 1

Times are ISO-8601 UTC with a zone (`2026-10-28T03:30:00Z`). Digests are `sha256:` and 64 lower-case hex digits.
A field that does not have its form is blanked (`""` or `null`), never passed through.

```
{ "schema": 1,
  "generated_at": "2026-10-28T03:30:00Z",
  "os": { "booted":   {"version": "4.4.0", "digest": "sha256:…", "built_at": "…Z"},
          "staged":   null,
          "rollback": {"version": "4.5.0", "digest": "sha256:…", "built_at": "…Z"},
          "rollback_queued": true,
          "kernel": "6.12.0-251.el10iv.aarch64",
          "booted_at": "…Z" },
  "components": [ {"id": "…", "version": "…", "transaction_digest": "sha256:…", "installed_at": "…Z"} ],
  "services":   [ {"name": "esync", "active_state": "active", "sub_state": "running", "since": "…Z", "restarts": 0} ],
  "health":     { "selinux": "enforcing", "ntp_synced": true, "var_used_pct": 25.0, "var_free_bytes": 22000000000 } }
```

* `generated_at` and `schema` are required; everything else may be absent. A missing section comes out empty.
* An image is `null` unless it has a version or a digest. It carries **no registry name and no transport**: those
  name a server.
* `active_state` is one of `active inactive failed activating deactivating reloading maintenance`, else `unknown`.
  `selinux` is `enforcing`, `permissive` or `disabled`, else `unknown`.
* At most 32 components and 32 services are kept. Strings are cleaned (control, zero-width and bidirectional
  characters removed, whitespace collapsed) and cut to 120 characters.
* Unknown keys are dropped at every level.
* `built_at` is the image's creation time as bootc reports it (`image.timestamp`), not when it was installed or
  booted, and the page labels the row **Image created**.
* **`components` is eSync's own record, and it can disagree with `os`.** The J7 test board's OS component had no
  `version` (the page shows "not reported"), a `transaction_digest` that matches neither bootc image, and an install
  date of 31 July against images from August. The page does not compare the two: an empty version has nothing to
  compare, and an eSync transaction digest is not known to be an image digest, so a mismatch flag would be a guess.
  The card says so; bootc, not eSync, says which image is running.

## What the reader answers

`ota.read()` returns a status, the file's age and the cleaned data. It never raises.

| Status | When | Data shown |
|---|---|---|
| `waiting` | no file yet | none; the message says how to fill it |
| `invalid` | not JSON, not an object, too big, an unsupported `schema`, or no usable `generated_at` | none |
| `stale` | older than 5 minutes, or its timestamp is more than a minute ahead of this machine's clock | the last written state, labelled with its age |
| `ok` | otherwise | all of it |

Each read stands alone: a broken file never shows the previous good one.

### Which image boots next

`next_boot` is derived, not read: `{"source": "rollback"|"staged"|"booted", "version", "digest"}`.

1. If `rollback_queued` is true and there is a rollback image, that image. `bootc rollback` "queues the deployment
   under `rollback` for the next boot" and discards a staged update (bootc 1.16.6, `bootc rollback --help`), so a
   queued rollback outranks a staged one.
2. Otherwise a staged update, which boots next.
3. Otherwise the image that is running.

On the J7 test board the file would read `booted 4.4.0`, `rollback 4.5.0`, `rollback_queued: true`: **a reboot
there starts 4.5.0.**

## The exporter

`tools/ota_export.py` runs on the **host**, as root, and writes the file. It is standard library only and imports
nothing from the project, so it is copied to a board on its own.

```bash
python3 ota_export.py --out /var/lib/vehicletap-ota/ota_status.json --service esync --service candump
python3 ota_export.py --out FILE --service esync --interval 30        # keep it fresh; Ctrl-C to stop
```

| Reads | For |
|---|---|
| `bootc status --format json` | booted / staged / rollback image (version, digest, build time) and `rollbackQueued` |
| `/var/lib/esync/state.json` | the components (the one eSync file it opens; the rest of that directory may hold identifiers and keys) |
| `systemctl show <unit> -p …` per `--service` | state, sub-state, restart count, and when it started (moved from the unit's monotonic time to the wall clock) |
| `timedatectl show -p NTPSynchronized`, `/sys/fs/selinux/enforce`, `uname`, `statvfs /var` | the health facts; `var_used_pct` is what `df` prints |

* **It only reads.** The commands it can run are fixed, a `--service` name cannot be an option or a path, and the
  only thing written is the output file: a temporary file in the same directory renamed over it, mode 0644 because
  the container runs as another user. The directory must exist; it is never created.
* **It builds from named fields.** The `bootc` output also carries the image registry, the transport and ostree
  checksums, and esync's state may carry more than a version. None of that is read out of its input, so none can be
  in the output; the dashboard's reader whitelists again on the other side. Services come from `--service`, not a
  built-in list.
* **A source that fails is an empty section**, with one line on stderr, never an error: the rest of the file is still
  written. In `--interval` mode a bad pass is logged and the next one runs. A one-shot run exits 1 only if it cannot
  write the file.
* **Mount the directory, not the file** (`deploy/quadlet/optional/vehicletap.container.d/10-ota.conf` does, and CONTAINER.md
  says how to install it). An atomic replace gives the file a new inode, and a single-file bind mount
  keeps pointing at the old one. Give the container the directory, read-only, and set `VEHICLETAP_OTA_FILE` to the file
  in it.

Run once on the J7 test board (2026-10-28) it produced a file the dashboard's reader accepted whole, with `booted
4.4.0`, `rollback 4.5.0`, `rollback_queued true`, three services and the two eSync components, and no registry
address anywhere in it. **How the exporter is kept running on that board is not decided:** `/etc` there is rebuilt at
every boot and the units that survive a reboot come from a signed deployment, so a persistent exporter has to go that
way (see [CONTAINER.md](CONTAINER.md)).

## What is deliberately not in it

Registry names and image references, device or vehicle identifiers, VINs, host names, IP addresses, API keys and
tokens never reach this file, and the reader would drop them if they did. There is also no campaign timeline (no
source for one was found on the board) and no signature or chain-of-trust display: OS images are not signature
verified on the test board, so a tick would claim something nobody checked.

## Tests

`tests/test_ota_export.py`: the document built from real captures (registry, digests and checksums replaced), what
must never get out, the allowlist of commands it may run, the atomic write, and that its output is exactly what the
reader accepts. `tests/test_ota.py`: the clock, every state, the whitelist (including a file seeded with secrets that must not come
out), caps, enumerations, number ranges, the derived `next_boot`, junk in every field, and a shipped sample that must
come through whole. `tests/fixtures/ota/` and `docs/demo/ota.json` use synthetic digests.
