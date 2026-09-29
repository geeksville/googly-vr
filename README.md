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
| `googly-vr` | Builds the eye screen once at startup, then animates pupils/lids via batched `set_properties` overrides (`--period` default 100 ms ≈ the ~10 fps ceiling). |

## Dev

```sh
just test    # pytest: OSC round-trip over loopback UDP, mapping math, coalescing
just lint    # ruff format + check
```

Design + stage plan: [docs/plans/general.md](docs/plans/general.md) —
research notes: [docs/kh-notes.md](docs/kh-notes.md).

## Status

Early days (stage 0–2 + the touchy-pad `SetPropertiesCmd` prerequisite are
implemented; see the plan). The eye screen is `button`-based circles on an
absolute layout; motion is one `SetPropertiesCmd` batch per frame — no
screen re-uploads. Eye size/shape-from-pupil-diameter and the real
EyeTrackVR hookup are future stages.
