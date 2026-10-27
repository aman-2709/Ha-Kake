# Hardware test plan: the container on J7 and x5h

> **Temporary.** This file lives on the branch `feature/container-quadlet` only.
> It is never merged to `main`. When both boards have been tested the branch is
> deleted (`git push origin --delete feature/container-quadlet`), and whatever
> the tests proved goes into `docs/CONTAINER.md` through a normal PR from `main`.

You are a Claude Code session on a machine that can reach two boards: **J7**
(TI TDA4 / Jacinto 7, running RHIVOS, boots to a command line) and **x5h** (the
owner's name for the second board; find out what it runs, do not assume). The
author of this plan could not reach either board. Your job is to run the
checks below on each board, record exactly what happened, and report. You are
testing; you are not fixing.

## What is being tested

Ha-Kake's simulator (`--adapter sim`, a web dashboard backed by a simulated
car) packaged as an OCI image (`Containerfile`) and a Podman Quadlet unit
(`deploy/quadlet/`). Read `docs/CONTAINER.md` first: it explains the design and
has a table of what was already checked on an x86 laptop and what was not. The
"not checked" row is this plan: **a real board running RHIVOS, systemd running
the unit, SELinux and a writable `/etc`, and a browser reaching the page
through an SSH tunnel.** Nothing here connects to a car or sends anything on a
CAN bus.

## Rules (read before touching a board)

1. **Progress log.** `CLAUDE.md` §3b applies to you. Keep an append-only,
   timestamped log in `research/agent-logs/hardware-test-<board>-<YYYYMMDD>.md`
   (gitignored). The first entry is the brief of this task in one
   self-contained paragraph; then one entry per phase with PASS/FAIL, and a
   `NEXT:` line kept current, so a cut-off session can resume from the log.
2. **Record, don't fix.** Do not edit source, the `Containerfile` or the units
   in the repo. Do not commit, push, merge or open a PR. A fix you think of goes
   in your results as a suggested diff.
3. **Leave the board as you found it.** Ask the user before rebooting, and
   before using credentials you were not given. Do not change the SELinux mode
   (`setenforce`), do not touch services other than `ha-kake`, do not use
   `--privileged`, do not publish ports beyond loopback, and do not install
   packages: a minimal board may lack `ss`, `ip`, `free` or `uptime`, so the
   commands below fall back to `/proc` and `/sys`.
4. **No CAN.** Phase 6 only *looks* at what is there (`ip link`, `/sys`). Do not
   bring an interface up, set a bitrate or send a frame.
5. **A failure is a result.** Capture the exact command and its exact output.
   To isolate a cause you may re-run `podman run` by hand with *one* hardening
   flag removed at a time (`--read-only`, `--cap-drop all`,
   `--security-opt=no-new-privileges`); say that you did, and report which
   flag mattered. Never keep a weakened command as the "working" answer.
6. **Ask when stuck.** If a step blocks for more than ten minutes, stop and ask
   the user.
7. **Privacy.** Results leave this machine when the user pastes them back. Do
   not include serial numbers, MAC addresses, keys, tokens, real hostnames or
   IP addresses; write `<board>`, `<user>`, `<lan-ip>`.

## Setup

On the machine you work from (not necessarily a board):

```bash
git fetch origin && git switch feature/container-quadlet && git pull
```

Commands below say "on the board". Run them over `ssh` if you are not on it.
Use root or `sudo` for Podman and systemd: the Quadlet unit is a system unit
and uses root's image store, so an image loaded rootless is invisible to it.

Paste this once in each shell on the board. It lists what is listening on the
two ports, and falls back to `/proc` when `ss` is missing. In the `/proc`
output the local address `0100007F` is 127.0.0.1 (what we want) and `00000000`
is every interface (a failure):

```bash
listening() { ss -ltn 2>/dev/null | grep -E ':(5000|8099)\b' || grep -E ':(1388|1FA3) .* 0A ' /proc/net/tcp /proc/net/tcp6 2>/dev/null; }
```

## The phases

| # | Phase | Question it answers |
|---|---|---|
| 0 | Recon | What is this board, and what can it do? |
| 1 | Get the image there | Does an arm64 image build or load, and run on this CPU? |
| 2 | Run by hand | Does the hardened `podman run` work on this OS? |
| 3 | Quadlet and systemd | Does the unit install, start, stop cleanly and restart on failure? |
| 4 | Reach the page | Does the tunnel work, and does `/sim` go "live" in a real browser? |
| 5 | Soak | CPU, memory and how fast the simulator database grows |
| 6 | CAN, look only | What CAN interfaces exist (for later)? |
| 7 | Clean up | Is the board back to how it was? |

Do the phases in order on one board, then repeat on the other. Phases 2, 3 and
5 can overlap: start the soak (5) as soon as 3 passes.

### Phase 0: recon

Record the answers; nothing here changes anything.

```bash
uname -m; cat /etc/os-release | head -6; cat /proc/device-tree/model 2>/dev/null; echo
podman --version; systemctl --version | head -1
getenforce 2>/dev/null || echo "no selinux tools"
nproc; grep -E 'MemTotal|MemAvailable' /proc/meminfo; df -h / /var /etc 2>/dev/null
touch /etc/.writetest && echo "/etc writable" && rm /etc/.writetest || echo "/etc NOT writable"
ls -d /etc/containers/systemd /etc/qm 2>&1; systemctl list-units --all 2>/dev/null | grep -iE "qm|bluechi" || echo "no qm/bluechi units"
listening || echo "ports 5000 and 8099 are free"
for t in ss ip curl sqlite3 ausearch journalctl; do command -v $t >/dev/null || echo "missing tool: $t"; done
getent hosts registry.access.redhat.com pypi.org >/dev/null && echo "internet name resolution works" || echo "offline"
```

Things to watch for:

- **RHIVOS may run non-safety workloads inside a nested "QM" container**
  (from the `qm` project, as I recall it; verify). If `qm`/`bluechi` units
  exist, the Quadlet directory may be inside QM (for example `/etc/qm/...`),
  and "host networking" may then mean QM's network namespace rather than the
  board's. Phase 3 and 4 check this; record what you find.
- The CPU architecture must match the image (`aarch64` expected).

### Phase 1: get the image onto the board

Either route works; record which you used and how long it took.

**A. Build elsewhere, load here** (the board may be offline). On an x86 machine
with qemu binfmt (`docker buildx ls` lists `linux/arm64`):

```bash
docker buildx build --platform linux/arm64 -f Containerfile -t localhost/ha-kake --load .
docker save -o /tmp/ha-kake.tar localhost/ha-kake
scp /tmp/ha-kake.tar deploy/quadlet/ha-kake.container deploy/quadlet/ha-kake.volume <user>@<board>:
# then, on the board (this lands in <user>'s home directory):
sudo podman load -i ha-kake.tar
```

Do not pipe the archive into `ssh ... sudo podman load`: `sudo` needs a terminal
for its password and stdin is busy carrying the image, so it fails unless sudo is
passwordless. The two unit files are copied in the same step because Phase 3
installs them from the board. Save the archive under `/tmp`, not in the checkout
(about 200 MB, and not git-ignored).

Use `podman build --platform linux/arm64 -t localhost/ha-kake .` instead of
docker if that is what you have. The `localhost/` prefix is required: it makes
the image `localhost/ha-kake:latest`, the name `ha-kake.container` uses.

**B. Build on the board** (needs the registry and PyPI):
`sudo podman build -t localhost/ha-kake .` from a checkout (the unit files are
then in that checkout, under `deploy/quadlet/`).

Then, on the board:

```bash
sudo podman images localhost/ha-kake
sudo podman image inspect localhost/ha-kake --format '{{.Architecture}} {{.Size}}'   # architecture must equal uname -m
```

### Phase 2: run by hand

These are the flags the Quadlet generator produces, run directly.

```bash
sudo podman volume create ha-kake-data
sudo podman run -d --name ha-kake --replace --network host --security-opt=no-new-privileges \
    --cap-drop all --read-only -v ha-kake-data:/data --env HAKAKE_DATA_DIR=/data \
    localhost/ha-kake:latest python web/app.py --adapter sim

# how long until it answers (the laptop under qemu answered within 25 s)
t0=$(date +%s); until sudo podman exec ha-kake python -c "import urllib.request as u;u.urlopen('http://127.0.0.1:5000/api/status',timeout=2)" 2>/dev/null; do sleep 1; done; echo "ready after $(( $(date +%s)-t0 )) s"
```

Then check each and record the output:

```bash
sudo podman logs ha-kake | head -20                       # expect "SIMULATOR MODE" and "data folder: /data"
for p in 5000/ 5000/sim 5000/api/status 8099/sim/schema; do
  sudo podman exec ha-kake python -c "import urllib.request as u;print('$p', u.urlopen('http://127.0.0.1:$p',timeout=5).status)"; done
listening                                                 # on the BOARD host: both must be 127.0.0.1 only
sudo podman run --rm -v ha-kake-data:/data --entrypoint sh localhost/ha-kake:latest -c 'ls -ln /data'   # files owned by uid 1001, gid 0
sudo podman exec ha-kake sh -c 'touch /app/x' 2>&1        # expect "Read-only file system"
sudo podman exec ha-kake sh -c 'grep CapEff /proc/self/status'   # expect all zeros
time sudo podman stop ha-kake; sudo podman inspect ha-kake --format '{{.State.ExitCode}}'   # expect 143
sudo podman start ha-kake; sleep 12; sudo podman logs ha-kake 2>&1 | grep -E "store:.*readings"   # N > 0: data survived
sudo podman rm -f ha-kake
```

The line that matters most: `listening` **on the board host**. If it shows
nothing while the container answers from inside, the container is in its own
network namespace, and Phase 4 will fail for that reason.

### Phase 3: Quadlet and systemd

Start from a clean slate so the volume is created by the unit:

```bash
sudo podman rm -f ha-kake; sudo podman volume rm ha-kake-data
```

Find the units directory from Phase 0 (`/etc/containers/systemd/` unless QM
says otherwise). Run the next block from the directory that holds the two unit
files: your home directory after route A, `deploy/quadlet/` in the checkout after
route B.

```bash
sudo cp ha-kake.container ha-kake.volume /etc/containers/systemd/
sudo /usr/libexec/podman/quadlet -dryrun                  # or: /usr/lib/systemd/system-generators/podman-system-generator --dryrun
sudo systemctl daemon-reload
systemctl cat ha-kake | head -40                          # the generated unit; expect --network host --read-only --cap-drop all
sudo systemctl start ha-kake; sleep 15
systemctl status ha-kake --no-pager; journalctl -u ha-kake -n 40 --no-pager
systemctl is-enabled ha-kake                              # a Quadlet unit with [Install] reports "generated"
```

Re-run the Phase 2 endpoint, `listening`, volume and read-only checks against
this container (it is also named `ha-kake`). Then the lifecycle, recording the
exact states each time (`systemctl show ha-kake -p ActiveState -p SubState -p Result -p NRestarts`):

```bash
sudo systemctl stop ha-kake;  systemctl is-failed ha-kake     # expect inactive, NOT failed (SuccessExitStatus=143)
sudo systemctl start ha-kake; sleep 10
sudo podman kill ha-kake;     sleep 12; systemctl show ha-kake -p ActiveState -p NRestarts   # SIGKILL: expect restarted (Restart=on-failure, RestartSec=5)
sudo podman kill --signal TERM ha-kake; sleep 12; systemctl show ha-kake -p ActiveState -p Result -p NRestarts   # observe; I did not predict whether a TERM is restarted
```

**Reboot test (ask the user first):** reboot the board and check the unit came
up by itself (`systemctl status ha-kake`, then the endpoint check).

**SELinux:** after the unit has run for a minute, look for denials and record
them whether or not anything broke. Do not change the mode.

```bash
sudo ausearch -m avc -ts recent 2>/dev/null | tail -20 || sudo journalctl -k --no-pager | grep -i avc | tail -20
sudo ls -dZ $(sudo podman volume inspect ha-kake-data --format '{{.Mountpoint}}')
```

### Phase 4: reach the page

The page is on the board's loopback, so you need a tunnel. From the machine
with the browser (the user's, or yours if you have browser tools):

```bash
ssh -N -L 5000:127.0.0.1:5000 -L 8099:127.0.0.1:8099 <user>@<board>
```

Both ports, same numbers: the `/sim` page's JavaScript calls the control API at
`http://127.0.0.1:8099` from the browser. Open `http://127.0.0.1:5000/` and
`http://127.0.0.1:5000/sim`. Expect:

- the dashboard draws, with a **SIMULATED** banner;
- `/sim` shows a green **live** badge, the instrument cluster and climate
  panel, and no visible "No simulator behind this page" notice;
- holding the brake or pressing a climate button on `/sim` changes the dashboard.

If you cannot drive a browser, ask the user to do this and quote what they say.
If another service already holds 5000 or 8099 on the board, edit **a copy** of
the unit's `Exec=` to add `--port N --sim-control M`, forward those ports, and
record that you had to.

### Phase 5: soak

With the unit running, record at 1, 5 and 15 minutes:

```bash
sudo podman stats --no-stream ha-kake || sudo podman exec ha-kake sh -c 'grep -H VmRSS /proc/[0-9]*/status'
cat /proc/loadavg
sudo podman exec ha-kake python -c "
import sqlite3, os
c = sqlite3.connect('file:/data/sim_leaf_ze0.db?mode=ro', uri=True)
print('readings', c.execute('select count(*) from readings').fetchone()[0],
      'cells', c.execute('select count(*) from cells').fetchone()[0],
      'bytes', sum(os.path.getsize('/data/'+f) for f in os.listdir('/data') if f.startswith('sim_leaf_ze0.db')))"
```

Compute rows per minute from the counts; the byte figure includes a write-ahead
log that grows in steps, so trust the row counts and the later samples more than
the early byte counts. Also record `df -h` for the volume's filesystem and
`sudo du -sh $(sudo podman volume inspect ha-kake-data --format '{{.Mountpoint}}')`.
This replaces the "about 90 MB a day, derived" figure in `docs/CONTAINER.md`
with a measured one.

### Phase 6: CAN, look only

```bash
# a CAN interface has link type 280 in sysfs, whatever it is named; no extra tools needed
found=0
for d in /sys/class/net/*; do
  [ "$(cat $d/type 2>/dev/null)" = 280 ] && { echo "$(basename $d): CAN, state $(cat $d/operstate)"; found=1; }
done
[ $found = 1 ] || echo "no CAN interface"
ls /sys/class/net                                         # everything else, for the record
```

Record what exists and its state. A virtual `vcan` also has type 280; say
whether each one is hardware. Do nothing else.

### Phase 7: clean up

Unless the user says to keep them:

```bash
sudo systemctl stop ha-kake
sudo rm /etc/containers/systemd/ha-kake.container /etc/containers/systemd/ha-kake.volume   # or the QM directory you used
sudo systemctl daemon-reload
sudo podman rm -f ha-kake; sudo podman volume rm ha-kake-data
sudo podman rmi localhost/ha-kake                         # ask first if the other board will reuse it from here
listening || echo "ports free again"
```

Close any `ssh -N -L` tunnels you opened.

## Report

Write `research/hardware-test/results-<board>-<YYYYMMDD>.md` (gitignored; the
privacy sweep refuses tracked files under `research/`), and end with a short
summary in the chat for the user to paste back. For each board:

| Phase | Result | Evidence and notes |
|---|---|---|
| 0 Recon | | board model, OS and version, `uname -m`, Podman version, SELinux mode, `/etc` writable?, QM present?, free ports?, missing tools |
| 1 Image | | route A or B, time taken, image architecture and size |
| 2 By hand | | ready-after seconds, host `ss` output, volume owner, read-only, CapEff, stop exit code, restart kept data |
| 3 Quadlet | | `quadlet -dryrun` ok?, `is-enabled`, stop leaves inactive or failed?, SIGKILL restart, SIGTERM behaviour, reboot, AVC denials |
| 4 Page | | tunnel worked?, dashboard, `/sim` "live", a control changed the dashboard |
| 5 Soak | | CPU% and RSS at 1/5/15 min, readings and cell rows per minute, measured MB/day, free space |
| 6 CAN | | interfaces found and their state |
| 7 Clean up | | board restored? |

Use PASS, FAIL or SKIPPED (with why). Then list, separately: **deviations from
the baselines below**, **anything that needs a change in the repo** (as a
suggested diff, not applied), and **what you did not get to**.

## Baselines from the x86 laptop

So that a difference stands out. All amd64 unless stated.

| Thing | Laptop |
|---|---|
| Image size | about 202 MB (arm64, built under qemu: about 207 MB) |
| Ready after start | answered within 10 s; arm64 under qemu within 25 s |
| `/api/status` | 145 keys, `simulated: true`, `soc` about 85 |
| `/sim/schema` | 68 entries under `knobs` |
| Volume files | owned by uid 1001, gid 0 (root) |
| Stop | 0.15 s, exit code **143** (the app exits 128+15 on SIGTERM) |
| Simulator database | about 12 readings and about 256 cell rows per minute; about 4.6 KB per readings row and about 30 B per cell row, so about 90 MB a day (derived, not measured on a board) |
| Quadlet generator | Podman 5.8.9 accepted both unit files; generated `--network host --read-only --cap-drop all --security-opt=no-new-privileges -v ha-kake-data:/data` |
| Podman run | rootful Podman 5.8.9 in a privileged container: loads as `localhost/ha-kake:latest`, runs, exit 143 |

Not measured on the laptop, so there is no baseline: CPU and memory use, how a
SIGTERM from outside interacts with `Restart=on-failure`, boot-time start,
SELinux behaviour, and anything on RHIVOS.
