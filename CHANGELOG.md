# Changelog

VehicleTap is based on **Ha-Kake**, created by David D. Karnowski
(<https://github.com/davidkarnowski/Ha-Kake>), and keeps its AGPL-3.0-or-later license and its copyright notices
(see [NOTICE](NOTICE)). This file records what was changed in VehicleTap, with dates. The first change was made on
2026-10-09; the git history is the full record, and everything before that date is the original project's.

## 2026-11-03: the project is renamed VehicleTap

Ha-Kake and its leaf logo are trademarks of the original author, who asks forks to use their own name and logo.

**Nothing you have has to be moved or re-recorded.** The old names keep working:

- The data folder. An existing `Ha-Kake` (Linux: `ha-kake`) folder is used as it is when there is no `VehicleTap`
  one; nothing is created beside it, moved, copied or deleted. See [docs/DATA.md](docs/DATA.md).
- Environment variables. Every `HAKAKE_*` name is still read; the `VEHICLETAP_*` name wins if both are set.
- Replay recordings. Files with the old `"hakake_replay": 1` key still load; only the new
  `"vehicletap_replay": 1` is written.
- Saved layouts and settings in the browser (their storage keys are unchanged).

**What does change, and what to do about it:**

| Was | Is now | If you use it |
|---|---|---|
| `HAKAKE_*` variables | `VEHICLETAP_*` | nothing; the old names still work |
| `hakake_sim.py` | `vehicletap_sim.py` | change the command you type |
| `bridge/hakake_bridge.py`, `hakake-bridge.service` | `vehicletap_bridge.py`, `vehicletap-bridge.service` | reinstall the unit on the Pi; the old one keeps running until you do |
| MQTT topic root `hakake/leaf` (default) | `vehicletap/leaf` | **breaking if you rely on the default**: a bridge and a reader on different versions see nothing until both are updated, or set `prefix` explicitly to the old root |
| JSON schema ids `hakake/mqtt/*`, bridge name `hakake-bridge` | `vehicletap/mqtt/*`, `vehicletap-bridge` | only if you match on them |
| Container image, Quadlet unit and volume `ha-kake` | `vehicletap` | rename them on a board that has the old ones |
| the header's leaf mark and the profile's `LOGO` field | a neutral dial for every vehicle; `LOGO` is no longer read | nothing, unless your own profile sets `LOGO`: it is ignored |
| `web/static/hakake.css` | `web/static/vehicletap.css` | only if you link it |

The commercial-licensing offer in the original project is the original author's to make, so it is not carried
over: contributions to VehicleTap are accepted under AGPL-3.0-or-later, and anyone who wants a commercial license
for the original code should ask the upstream project. Vulnerability reports go through the repository's GitHub
private reporting instead of a personal e-mail address.

## 2026-10-27 to 2026-10-28: the board's OS-update state on an /ota page

- `/ota` and `GET /api/ota`: which OS image is booted, staged or queued for rollback, which image the next
  boot starts, the update components, the services around them and basic health. The dashboard container cannot
  see any of that, so a host process writes one JSON file and the app only reads it through a whitelist.
  [docs/OTA.md](docs/OTA.md).
- `tools/ota_export.py`: the host-side writer (standard library only, read-only commands, atomic write).
- An opt-in Quadlet drop-in that gives the container the status file read-only.

## 2026-10-24 to 2026-10-27: containers

- A `Containerfile` and a Podman Quadlet unit that run the dashboard and simulator on a headless board
  (RHIVOS / TDA4), viewed through an SSH tunnel; demos 1 and 2 in a container. [docs/CONTAINER.md](docs/CONTAINER.md).

## 2026-10-09 to 2026-10-16: the simulator and its cockpit

- `tools/sim_to_can.py` puts the simulated ECUs on a kernel CAN device and serves the simulator's control API, so
  the `/sim` cockpit can drive a real bus; `--can-channel` and `--sim-control-url` on the dashboard.
- `/sim` cockpit: a tidy first-run layout, a filterable live model state that flashes what changed, foldable knob
  panels with compact switches, shipped dashboard and cockpit arrangements, and a favicon on both pages.
- The body, vehicle and climate tiles: rolling wheels, reverse lamps with a beam, a larger shifter, boxed readings.
- `Demo-Readme.md` (how to bring up each demo and what every argument does), Ubuntu setup notes and Credits.
- `pyobjc` packages install only on macOS.
