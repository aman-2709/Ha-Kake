# Ha-Kake demos

There are several demos, not one. Each shows a different part of the project, and none of them needs a car.

Run every command from the repo root with the project's virtual environment (`venv/bin/python`).

```bash
cd ~/dev/personal-projects/Ha-Kake
```

Stop a demo with `Ctrl-C` before starting the next one. The dashboard uses port 5000 in every demo, and the simulator demos also use port 8099 for the simulator's control API. If a port is busy, add `--port 5001` to the command.

| # | Demo | What it shows |
|---|---|---|
| 1 | Interactive simulated car | Drive the car yourself and inject faults |
| 2 | A scripted scenario | A drive, charge or failure that runs by itself |
| 3 | Replay | Real recorded data, decoded by the real code |
| 4 | Simulated CAN bus | The native CAN path at the real frame rate |
| 5 | Canned JSON | The page only, no reader |
| 6 | CAN frames on `vcan0` | Raw frames you can see with `candump`, read by the dashboard |

---

## 1. Interactive simulated car (best first demo)

```bash
venv/bin/python web/app.py --adapter sim
```

| Part | Meaning |
|---|---|
| `venv/bin/python` | The Python interpreter inside the project's virtual environment, so the installed packages are found. |
| `web/app.py` | The program that starts the Flask web server and, as a subprocess, the reader that collects the data. |
| `--adapter sim` | Where the data comes from. `sim` means a simulated car (a running model) instead of a real adapter. |

- Dashboard: `http://127.0.0.1:5000`
- Cockpit (the controls): `http://127.0.0.1:5000/sim`

**What to show:** press the power button, put the car in gear and press the pedal. Turn the A/C on, open a door, plug it in to charge, and watch the dashboard follow. Fault injection is the strongest part: degrade a cell, trigger low insulation resistance, make the car go to sleep or return an ECU error.

---

## 2. A scripted scenario that runs itself

```bash
venv/bin/python web/app.py --adapter sim --scenario commute --seed 1 --speed 10
```

| Argument | Meaning |
|---|---|
| `--adapter sim` | Use the simulated car, as in demo 1. |
| `--scenario commute` | Load a scripted timeline that moves the simulator's controls for you. `commute` is a drive: pull away, surface streets, a freeway cruise, two lift-off regen events, a stop at lights, then home and parked, with the A/C on all the way. Without this flag the car sits idle until you drive it. A scenario name, or the path to a scenario JSON file, is accepted. |
| `--seed 1` | The seed for the simulator's random number generator (sensor noise and similar). The same seed gives the same run; change it to get a different one. |
| `--speed 10` | Time scaling. `10` runs the scenario ten times faster than real time, so a drive of about a quarter of an hour takes about a minute and a half. `1` is real time and `60` runs an hour in a minute. It overrides a scenario's own clock setting. |

Scenarios you can name (all run at real time unless you pass `--speed`):

| Scenario | What it does |
|---|---|
| `drive` | Pull away, cruise at 45 mph, brake and stop. |
| `commute` | A longer drive with a freeway cruise, regen and a stop. |
| `idle` | Parked and READY in a warm car park. |
| `pull` | A standing-start acceleration, for the CAN rig and comparisons. |
| `pulls` | Five acceleration pulls in a row, to watch the pack sag in the 3D tile. |
| `charge` | Level 2 (3.3 kW) charge from 40 %, with the taper at the top. |
| `full_charge` | A Level 1 charge from 15 % to full, the whole curve. |
| `dc_fast` | A CHAdeMO fast charge with a hard taper (the numbers are asserted, not measured). |
| `degraded_pack` | One cell pair collapses under load and isolation starts to fail. |
| `degradation_arc` | Two years of ageing compressed into a couple of minutes. |

`lancer_idle` and `lancer_dtc` are for the Lancer profile (`--vehicle lancer_2009`). The cockpit also has a scenario picker.

---

## 3. Replay of a real recorded session

```bash
venv/bin/python web/app.py --adapter replay
venv/bin/python web/app.py --adapter replay --vehicle lancer_2009
```

| Argument | Meaning |
|---|---|
| `--adapter replay` | Play back a recording from `tests/fixtures/` through the whole real stack: transport, scheduler, decoders, database and page. Every record is flagged `replay: true` and goes into a throwaway database. |
| `--vehicle lancer_2009` | Choose the vehicle profile (the file in `vehicles/` that describes one car). The default is `leaf_ze0`. The second command shows a different car on the same engine. |

This is real data, decoded by the real code. `--fixture PATH` picks a different recording, and `--speed` also works here (`2` plays twice as fast).

---

## 4. Simulated CAN bus at the real frame rate

```bash
venv/bin/python web/app.py --adapter sim --sim-can
venv/bin/python tools/bench_canrate.py --seconds 10
```

| Argument | Meaning |
|---|---|
| `--adapter sim` | The simulated car. |
| `--sim-can` | Put the simulated ECUs on an in-process virtual CAN bus and read it through the native CAN code, at about 1,700 frames per second, like a real Leaf's Car-CAN. Add `ev` (`--sim-can ev`) to also simulate the EV-CAN bus. Nothing leaves the Python process. |
| `tools/bench_canrate.py` | A benchmark that measures whether the reader keeps up with that frame rate. It prints the cycle time, frames per second and CPU use for each bus load. |
| `--seconds 10` | How long to measure at each bus load (the tool's own default is 8). |

Other bench flags: `--loads` (the bus-load levels to test, a comma-separated list), `--scenario` and `--seed` (as above), `--log PATH` (append the result table to a file) and `--json` (machine-readable output).

---

## 5. No reader at all

```bash
venv/bin/python web/app.py --demo
```

| Argument | Meaning |
|---|---|
| `--demo` | Serve frozen JSON from `docs/demo/` and start no reader. It is good for a quick look or for screenshots. `--demo PATH` uses another folder. |

---

## 6. Simulated CAN frames on `vcan0` (visible with `candump`)

Demo 4 keeps the CAN bus inside one Python process. This one puts it on a real Linux CAN device, so you can watch the frames and read them from a second program. Linux only.

One-time setup (it does not survive a reboot), then four terminals:

```bash
sudo modprobe vcan && sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
```

```bash
venv/bin/python -u tools/sim_to_can.py --scenario drive --knob soc=20     # 1: the simulated car
candump vcan0                                                               # 2: the raw frames
venv/bin/python web/app.py --adapter can --can-channel vcan0 --db /tmp/vcan.db # 3: the dashboard
```

| Part | Meaning |
|---|---|
| `tools/sim_to_can.py` | Runs the simulated ECUs and sends their frames, about 1,700 a second, on a SocketCAN device. |
| `--channel vcan0` | The device (the default). `can0` also works on a bench with `--bench`; see `docs/SIMULATOR.md`. |
| `--scenario drive` | The scripted drive from demo 2. |
| `--knob soc=20` | Set one simulator control. Here the battery starts at 20 %. Repeat the flag for more. |
| `-u` | Python flag: unbuffered output, so the progress line appears at once. |
| `candump vcan0` | From `can-utils`: prints every frame on the device. |
| `--adapter can` | Read a CAN device through the native CAN code. `config.local.json` must set `can_interface` (`socketcan`), `can_bus` (`car`) and `can_bitrate` (`500000`). |
| `--can-channel vcan0` | Which device to read. It overrides `can_channel` in the config, so the same command takes `can0` for the CANable. |
| `--db /tmp/vcan.db` | A scratch database. This path is not marked as simulated, so keep it away from the real one. |

To switch to the real CANable later, use `--can-channel can0`. Nothing else in the reader changes.

---

## Arguments used above

| Argument | Meaning |
|---|---|
| `--adapter` | The data source: `sim`, `replay`, `can`, or the real ones (`ble`, `usb`, `mqtt`). The default `auto` detects a real adapter. |
| `--scenario` | The scripted simulator timeline to run. |
| `--seed` | Random seed for the simulator, so a run can be repeated. |
| `--speed` | Time scaling for the simulator and for replay. |
| `--vehicle` | The vehicle profile: `leaf_ze0` (default) or `lancer_2009`. |
| `--sim-can [car\|ev]` | Simulated CAN bus (with `--adapter sim`). |
| `--demo [PATH]` | Canned JSON, no reader. |
| `--port` | The dashboard's port (default 5000). |
| `--sim-control PORT` / `--no-sim-control` | The simulator's control API port (default 8099), or switch it off. |

The full list is in `docs/SIMULATOR.md` ("Flags") and `python web/app.py --help`.

---

## What you can showcase

- **Live dashboard:** gauges, a 96-cell voltage grid and a 3D pack, with draggable tiles, per-tile audible alerts and a Playback button.
- **Fault handling:** injected failures show up on the dashboard in real time.
- **Same code, many sources:** one reader runs on a simulator, a replay and a simulated bus.
- **Architecture:** the Ha-Kake Field Guide page covers the structure and the protocols.
