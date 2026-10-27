# Running Ha-Kake in a container

The dashboard and the simulator as an OCI image, for a board that boots to a
command line (a TDA4 / Jacinto 7 running RHIVOS, say). The board only *serves*
the page; the browser that draws it is on another machine.

> This runs the **simulator** (`--adapter sim`). Nothing here reads a car. Real
> CAN from a container is not covered: see "Not covered" below.

## The short version

```bash
# on a build machine (needs qemu-user-static / binfmt for a cross-build)
podman build --platform linux/arm64 -t localhost/ha-kake .
podman save -o /tmp/ha-kake.tar localhost/ha-kake
scp /tmp/ha-kake.tar deploy/quadlet/ha-kake.container deploy/quadlet/ha-kake.volume <user>@<board>:

# on the board, as root (or with sudo; <user> needs sudo)
sudo podman load -i ha-kake.tar
sudo cp ha-kake.container ha-kake.volume /etc/containers/systemd/
sudo systemctl daemon-reload && sudo systemctl start ha-kake
sudo journalctl -u ha-kake -f

# on your laptop: forward BOTH ports, with the same numbers
ssh -L 5000:127.0.0.1:5000 -L 8099:127.0.0.1:8099 <user>@<board>
# then open http://127.0.0.1:5000  and  http://127.0.0.1:5000/sim
```

This is the **rootful** flow, and every step on the board must be root: a Quadlet
unit under `/etc/containers/systemd/` runs as root and sees only root's image
store, so an image loaded by a normal user (`podman load` without `sudo`) is
invisible to it. The archive is copied first and loaded in a second step on
purpose: piping it into `ssh ... sudo podman load` works only with passwordless
sudo (`sudo -n`) or as `root@`, because `sudo` needs a terminal for its password
and stdin is busy carrying the image. The image can also be built on the board
(`sudo podman build -t localhost/ha-kake .` in a checkout).

A **rootless** setup is a different flow, not a variation: load the image as that
user (`podman load -i ha-kake.tar`), put the units in `~/.config/containers/systemd/`,
use `systemctl --user`, and run `loginctl enable-linger <user>` if it must start at
boot without a login. In the copy you install, change `WantedBy=multi-user.target`
to `WantedBy=default.target`: a user manager has no `multi-user.target`, so lingering
would not start the unit otherwise. Don't mix the two flows. Neither was tried on a
board.

## With Docker, or on an x86 machine

The image is plain OCI. Docker builds the `Containerfile` with `-f`, and an
amd64 build runs on any x86 Linux machine (that is where most of the checks
below were made). The page is on the same machine, so no tunnel:

```bash
docker build -f Containerfile -t localhost/ha-kake .
docker run -d --name ha-kake --network=host --read-only --tmpfs /tmp \
    --cap-drop ALL --security-opt no-new-privileges \
    -v ha-kake-data:/data localhost/ha-kake
# open http://127.0.0.1:5000  and  http://127.0.0.1:5000/sim
docker rm -f ha-kake            # stop it; the volume keeps the data
```

To build for the board from an x86 machine, with qemu binfmt set up:

```bash
docker buildx build --platform linux/arm64 -f Containerfile -t localhost/ha-kake --load .
docker save -o /tmp/ha-kake.tar localhost/ha-kake
scp /tmp/ha-kake.tar <user>@<board>:
# then on the board: sudo podman load -i ha-kake.tar
```

(Copy, then load as root, for the reasons above. The archive goes to `/tmp` on
purpose: it is about 200 MB, and saved into the checkout `git add -A` would stage it.)

The `localhost/` prefix is what makes `podman load` name the image
`localhost/ha-kake:latest`, the name the Quadlet unit uses. The Quadlet files
themselves are Podman-only. Docker Desktop (macOS, Windows) was not tried: its
host network is the VM's, so the loopback-only page would probably not be
reachable from your browser. Use Linux.

## Why host networking, and why a tunnel

The app is loopback-only on purpose (`SECURITY.md`): the dashboard binds
`127.0.0.1:5000`, every request must name a loopback host, and the simulator's
control API (`127.0.0.1:8099`) has no authentication and "must never be
exposed". A published port (`-p`) reaches a container's own network address,
not its loopback, so it cannot reach a service bound there. Host networking
makes the container's loopback the board's loopback, and nothing listens on
the LAN.

The `/sim` cockpit's JavaScript calls the control API **from the browser**, at
`http://127.0.0.1:8099`. Through a tunnel that means your laptop's port 8099
must lead to the board's 8099, so forward both ports and keep the numbers. If
5000 or 8099 is taken on the board, the Quadlet `Exec=` line takes
`--port N` and `--sim-control M`; forward those instead.

## What the image holds

`Containerfile` copies explicit paths (code, `vehicles/`, `simulator/`, and
`web/`'s code, templates, static files and shipped layouts), never `COPY . .`,
so a build that ignores both ignore files still cannot pick up
`config.local.json`, a database or `research/`. `.containerignore` (podman,
buildah) and `.dockerignore` (docker) hold the same allowlist, which keeps the
build context at about 2 MB instead of uploading local databases; a test keeps
the two equal.

The allowlist names directories, so it does not list the files inside them: an
untracked file sitting in `vehicles/`, `simulator/` or `web/static/` is copied
unless a rule denies it. The ignore files deny the usual private patterns there
(`.env*`, `*.pem`, `*.key`, `*.log`, `*.tmp`, `*.jsonl`, databases, state files,
`config.local.json`), and a test builds a throwaway context with docker's own
ignore handling and checks that nested private files stay out. Real Podman 5.8.9
gave the same result with `.containerignore` (checked once by hand, not in the
test suite). That is a backstop, not a proof about every name. For a build that cannot see anything
untracked, build from the committed files:

```bash
git archive HEAD | docker build -f Containerfile -t localhost/ha-kake -
```

(With the Docker used here, 29.8 with BuildKit, a context read from stdin ignored
the `.dockerignore` inside it, and the image contents matched the normal build.)

The base is UBI 9 Python 3.12 minimal (`ARG BASE_IMAGE` swaps it); it runs as uid 1001
with a read-only root, no capabilities and no new privileges. About 200 MB.

The data folder (`docs/DATA.md`) is `/data`, a named volume `ha-kake-data`. It
holds the tile layouts, bookmarks and the simulator's database, and survives
image updates. `podman volume rm ha-kake-data` resets it.

## Disk use: the simulator database is never pruned

The simulator writes `sim_leaf_ze0.db` to the volume and nothing deletes rows
(`docs/DATA.md`). With the default store period (5 s) that is about **90 MB a
day**: 17,280 readings at ~4.6 KB each, plus ~370,000 cell rows at ~30 B (the
default layout stored 384 cell rows in 90 s). *Derived* from the table sizes of
a local simulator database and the row rates seen in the container, not
measured on a board. A board with a small eMMC will fill in weeks. Until the app can bound it, stop
the service and reset the volume now and then, or watch `du` on the volume.

## What was verified, and what was not

| Checked | Result | How |
|---|---|---|
| `linux/arm64` image builds and starts | dashboard, `/sim` and control API answer; `platform.machine()` is `aarch64` | qemu emulation on an x86 laptop, **not hardware** |
| Hardened run (read-only root, `--cap-drop ALL`, no-new-privileges, host network, fresh volume) | runs; writes only to the volume | amd64 image, Docker 29.8 |
| Docker-built image run under real Podman | `podman load` names it `localhost/ha-kake:latest`; runs read-only, `--cap-drop all`, host network; a `podman volume create` volume is writable by uid 1001; exits 143 on stop | rootful Podman 5.8.9 in a privileged `quay.io/podman/stable` container on the laptop, amd64 |
| `/sim` cockpit in a browser | "live", 68 knobs from the control API, no console errors | A browser driven by Playwright, direct to loopback |
| Data survives a restart | the 46 earlier readings were found | amd64 image |
| Quadlet files | accepted; generated `podman run … --network host --read-only --cap-drop all …` | `quadlet -dryrun` in `quay.io/podman/stable` (Podman 5.8.9) |
| SIGTERM | stops in 0.15 s, exit **143** (the app exits 128+signal), so the unit sets `SuccessExitStatus=143` | amd64 image |
| **A real TDA4 running RHIVOS** | **not tried** | its Podman version, SELinux policy and writable `/etc`, systemd actually running the unit, and an SSH tunnel to a real browser are all untested |

Re-run the Quadlet check after editing the units:

```bash
podman run --rm -v "$PWD/deploy/quadlet:/q:ro" -e QUADLET_UNIT_DIRS=/q \
    quay.io/podman/stable /usr/libexec/podman/quadlet -dryrun
```

`tests/test_container_files.py` guards the files without an engine: every
`COPY` source exists, no `COPY` names the whole tree or a private path, the user
is not root, the ignore files hold the same rules with the denylist last, and the
unit stays on host networking with no `PublishPort=`. One more test builds a
throwaway context with docker to check that nested private files stay out; it
skips when docker, buildx or the daemon is missing.

## Not covered

- **A screen on the board.** A Wayland kiosk (`cage` plus a browser) in a
  second container sharing the network namespace would show it locally, but it
  needs DRM access and, on a PowerVR GPU, a working driver in the container;
  the 3D pack tile is the only WebGL part and would crawl on software
  rendering. Not built, not tried.
- **Browsing to the board's address** instead of a tunnel. It needs a
  configurable bind address (`app.run` is hard-coded to `127.0.0.1`),
  `HAKAKE_ALLOWED_HOSTS`, and a way for `/sim` to reach the control API
  without exposing it. The Flask development server is out of scope for
  network exposure in `SECURITY.md`.
- **Real CAN.** The code supports SocketCAN (`--adapter can`,
  `docs/CAN_TRANSPORT.md`); whether the board's CAN controllers appear as
  `can0` on RHIVOS, and what the container needs to open them, is unchecked.
