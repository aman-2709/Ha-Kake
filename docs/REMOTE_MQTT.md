<!--
SPDX-FileCopyrightText: 2026 David D. Karnowski
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Watching your car remotely over MQTT

A common use: the car sits in a garage, and you want to see its state of charge (and a few other values) from the
house, over wifi, without leaving a laptop in the car. Ha-Kake supports this with two small pieces and a broker you
run yourself.

```
 car ──CAN──▶ Raspberry Pi (bridge) ──MQTT──▶ broker ──▶ Ha-Kake on your computer (--adapter mqtt)
                                                      └─▶ any other MQTT client (a gauge, a phone app, an alert)
```

- **The bridge** (`bridge/`, `bridge/README.md`) runs on a Raspberry Pi wired to the car's OBD-II connector with a CAN
  adapter. It publishes the car's CAN frames to MQTT and carries out the reader's *read-only* requests.
- **The broker** is any MQTT broker, such as Mosquitto. Ha-Kake does not install or manage it.
- **The reader** is Ha-Kake on your computer, started with `--adapter mqtt`. It sees the same data as if the adapter
  were plugged into it. The wire format is `docs/MQTT.md`.

How your computer and the Pi reach the broker (the same wifi, a VPN, a tunnel) is your own network's business and is
not covered here. Keep the broker off the open internet: plain MQTT has no encryption, and a broker anyone can write to
could be used to send requests toward the car's bus (the bridge only ever sends read-only service requests to the
ids in its allow-list, but there is no reason to expose it).

## 1. The broker

Install Mosquitto on a machine that is always on (the Pi itself works for a home setup) and bind it to the interface
you intend, not to every interface:

```
# /etc/mosquitto/conf.d/hakake.conf
listener 1883 127.0.0.1          # this machine only; use your LAN address to serve other machines
allow_anonymous true             # fine on a private network you control; use a password file otherwise
```

## 2. The bridge on the Pi

Wire the Pi to the car through a CAN adapter that appears as a kernel `can0` (a gs_usb / candleLight adapter, a CAN HAT),
bring `can0` up at 500 kbit/s, then run the bridge as a service. `bridge/README.md` has the config file, the
service unit, the read-only request rules and how to check it; a minimal run is:

```bash
sudo ip link set can0 up type can bitrate 500000 restart-ms 100
./venv/bin/python bridge/hakake_bridge.py --config config.json
```

with `host` in `config.json` pointing at your broker. The bridge publishes a retained `status` message every two
seconds, so `mosquitto_sub -h <broker> -t 'hakake/leaf/car/status' -v` shows at a glance whether it is alive.

## 3. Ha-Kake on your computer

In `config.local.json` (not tracked by git) point the reader at the broker:

```json
{ "mqtt": { "host": "<broker address>", "prefix": "hakake/leaf" } }
```

```bash
./venv/bin/python web/app.py --adapter mqtt
```

The dashboard then shows the charge, pack voltage, 12 V battery and the rest from the car in the garage.
`docs/MQTT.md` §3 lists the topics, including `signal/<key>` values (state of charge, 12 V volts, and so on) that any
MQTT client can subscribe to for a simple gauge or an alert.

## Things to know

- **Read-only.** The bridge refuses anything but read services, sends only on the allow-listed id pairs, and can be
  started `--listen-only` to send nothing at all.
- **A parked car and its 12 V battery.** A reader left polling a parked car draws a little power. Watch the 12 V
  value over a few days before leaving it unattended, and poll no faster than you need.
- **Several readers.** Two readers on one bridge share the reply stream and can confuse each other's replies. Use one
  requester per bridge, or give each its own bridge.
- **Reconnects.** Both ends reconnect on their own after a network drop (back-off capped at 10 s).
