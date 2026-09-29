# googly-vr

Cute animated **googly eyes** on a [touchy-pad](../../) USB display,
driven (eventually) by real eye tracking.

```
[Steam Frame eye cameras]
        │
        ▼
 [Sightline]  (Valve's app — streams the eye-cam feeds over HTTP)
        │
        ▼
 [EyeTrackVR] (pupil position, blink, eye openness)
        │        OSC / UDP 127.0.0.1:9000
        ▼
 [googly-vr]  (this project — maps tracking → eye widget geometry)
        │        touchy-pad python API (USB, or sim)
        ▼
 [touchy-pad device]  (LVGL renders two googly eyes on the panel)
```

No Steam Frame yet, so the EyeTrackVR half is **simulated**: `sim-eyes`
broadcasts fake tracking on the exact OSC endpoint (UDP `127.0.0.1:9000`,
VRCFT `/avatar/parameters/...` addresses) a real tracker will one day use.
When hardware arrives, stop `sim-eyes`, start EyeTrackVR — `googly-vr`
never knows the difference.

## Quickstart

```sh
just install     # one-time: venv + deps (touchy-pad via path dep on ../../app)

# Terminal 1 — the fake tracker (~10 fps, sine wander + blinks):
just sim-eyes

# Terminal 2 — the eyes (real USB device, or the simulator):
just run
```

`just run` doesn't need the pad (or the tracker) to be there first: it listens on
`udp://127.0.0.1:9000`, waits for eye tracking to arrive, and then picks up a
touchy-pad — retrying every 5 s while updates keep coming (plug the pad in at any
moment; exit with ctrl-c). Only OSC from this machine is accepted by default; add
`-- --host 0.0.0.0` to listen on every interface.

Against the touchy-pad **simulator** instead of hardware:

```sh
just app-run -- --sim-gui   # in the parent repo: start the Qt sim
export TOUCHY_SIM_URL=tcp://127.0.0.1:8935   # or whatever the sim prints
just run
```

## Commands

| Command | What it does |
|---|---|
| `sim-eyes` | Broadcasts fake EyeTrackVR tracking (`--pattern {wander,stare,crazy}`, `--blink-rate`, `--rate`). |
| `googly-vr` | Listens for OSC tracking on `127.0.0.1:9000` (loopback only unless `--host` says otherwise), finds the touchy-pad lazily — a connection is only attempted when an update arrives, every 5 s at most — builds the eye screen once, then animates pupils/lids via batched `set_properties` overrides (`--period` default 100 ms ≈ the ~10 fps ceiling). Runs until ctrl-c, so a pad attached later is picked up. |

## Dev

```sh
just test    # pytest: OSC round-trip over loopback UDP, mapping math, coalescing
just lint    # ruff format + check
```

## Status

you probably don't want this yet.

## AI slop and development
I'm okay with using AI tools to help make code.  In fact, I used them a fair amount so far on this project (one of my first experiments with not writing all my code 'by hand').  So far it has been pretty fun.

However, in some of my other open-source projects, I've seen the current hell PR management is becoming.  So I'd **love** any code contributions y'all want to make (and I promise to be kind) but:

* Please only send in PRs **you** are willing to sign off as 'nicely written' (using your experience as a software engineer).  If your little AI buddy made something a bit ugly, please iterate with it first to make it not ugly.
* Send in PRs that are fairly 'atomic' (touch just the code they need to touch for one nicely defined feature or bug-fix)
* Only send in tested code you've run on real hardware (not just the simulator)

