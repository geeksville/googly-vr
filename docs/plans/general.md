# googly-vr — plan for the early days

Turn a cheap touchy-pad USB display into a pair of cute animated
"googly" eyes, driven (eventually) by real eye tracking.

> **Status (2026-09-28): implemented.** Stages 0–2 plus the Stage-3
> enhancements E1 (simulator honours `set_properties`) and E2
> (`SetPropertiesCmd` *replacing* `set_property`) are all landed and
> verified: parent-repo `just app-test` (251 passed) / `just app-lint` /
> `just firmware-build` / `just rust-test` green, googly-vr's own 12-case
> pytest suite green, and an end-to-end smoke (client batch → sim
> override engine → re-rendered screen proto) passes. The real-hardware
> run additionally needs the device **re-flashed** with the new
> protocol-14 firmware. See `docs/design.md` → "Stage lb14" for the
> parent-repo side of the change.
>
> **Next:** Stage 5 → `docs/plans/stage5.md` (loopback-only OSC by default,
> auto-reconnect / "looking for touchy-pad" retry loop, and a parent-repo
> firmware tweak so host property writes reset the display auto-off timer).

## Goal / vision

The end-state pipeline (once a Steam Frame arrives):

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

Until then we **simulate the EyeTrackVR half**: a `sim-eyes` command
broadcasts fake tracking data on the same OSC endpoint real EyeTrackVR
uses, so when the hardware arrives the only change is "stop running
`sim-eyes`, start running EyeTrackVR" — `googly-vr` never knows the
difference.

### What this plan covers (the early days)

* Stage 0 — project skeleton (README, Poetry, two console commands).
* Stage 1 — `sim-eyes`: an EyeTrackVR-lookalike OSC broadcaster.
* Stage 2 — `googly-vr`: OSC listener that draws + animates the eyes
  on a touchy-pad.
* Stage 3 — touchy-pad enhancements this project needs (they benefit
  the main project too — see "Stage 3" below).

### Non-goals for now

* No Steam Frame / Sightline / real EyeTrackVR integration (no
  hardware yet) — we just match their wire format.
* No VRChat / VRCFaceTracking output — googly-vr is a *consumer* of
  eye-tracking data, not a producer.
* No avatar-accurate rendering — the goal is *cute*, not photoreal:
  two circles with round pupils.
* Not yet published to PyPI (the touchy-pad dep is a path dependency
  until then).

## Approach & technology choices

| Choice | Rationale |
|---|---|
| Python 3.11+ / Poetry | Match touchy-pad's host stack exactly, so the eventual pypi pull-in and the devcontainer both "just work". |
| `python-osc` for OSC | EyeTrackVR speaks OSC over UDP loopback (see `docs/kh-notes.md`). `python-osc` gives us both the UDP client (broadcaster) and a dispatching UDP server (listener) from one tiny pure-Python dep. |
| OSC on **UDP 127.0.0.1:9000** | The EyeTrackVR/VRCFT convention (9000 = input to the consumer, 9001 = output). Matching it means zero code change when real EyeTrackVR replaces `sim-eyes`. We adopt the **VRCFT parameter routing** (`/avatar/parameters/...`, normalized −1..1 floats, independent left/right eyes) — the richer of the two dialects, and the one whose data we need. |
| touchy-pad as a **path dependency** on `../../app` | googly-vr is a git submodule inside touchy-pad *for now*; it will be extracted after initial development. Keep every touchy-pad import confined to one module (`renderer.py`) so extraction is a one-file diff. Later swap the path dep for `touchy-pad>=X` from PyPI. |
| Eyes = `button` widgets, circles via `style(radius=…)` | The screens DSL has no plain "box" widget, but a `button` with `style(bg_color=…, radius=…)` (radius ≥ half-size ⇒ circle) renders exactly what we need, no images to upload. |
| Absolute layout, motion via `set_properties` | Build the eye screen **once** at startup (see `docs/python-api.md` — `touchy_pad.api.screens` DSL + `pad.screen_save`), then animate with the **batched** runtime property overrides: `pad.set_properties([...])` — Stage 3's `SetPropertiesCmd`, which *replaces* the singular `set_property` (deliberate wire break, no backwards compat for now). `x` / `y` / `w` / `h` are integer properties, so each tracking frame is **one** cheap RPC carrying ~4 overrides — no screen re-upload. |

### OSC data we emit/consume (VRCFT addresses)

* `/avatar/parameters/LeftEyeX`, `/avatar/parameters/RightEyeX` —
  float −1.0 … 1.0 (left … right)
* `/avatar/parameters/LeftEyeY`, `/avatar/parameters/RightEyeY` —
  float −1.0 … 1.0 (down … up)
* `/avatar/parameters/LeftEyeLidExpanded`,
  `/avatar/parameters/RightEyeLidExpanded` — float 0.0 (shut) … 1.0
  (wide open)
* (later) `/avatar/parameters/EyesPupilDiameter` — pupil size

### Frame rate: ~10 fps max

The whole pipeline targets **~10 fps** — plenty for googly eyes, and
comfortably within reach of one batched property RPC per frame over
USB. `sim-eyes` sends at ~10 Hz; `googly-vr`'s `--period` (default
100 ms) coalesces whatever arrives — including the faster stream real
EyeTrackVR will one day send — down to that same ~10 fps.

## File & component layout

```
tools/googly-vr/
├── README.md                    # stage 0 — pitch + quickstart
├── pyproject.toml               # Poetry; path dep on ../../app
├── docs/
│   ├── kh-notes.md              # research notes (EyeTrackVR pipeline, OSC)
│   └── plans/general.md         # this file
└── src/googly_vr/
    ├── __init__.py
    ├── osc_proto.py             # OSC address constants + EyeState dataclass
    │                            #   (shared by both commands — single source
    │                            #    of truth for the wire format)
    ├── sim_eyes.py              # `sim-eyes` entry: fake tracker → OSC
    ├── renderer.py              # eye screen DSL build + OSC→set_properties
    │                            #   mapping (the ONLY touchy_pad importer)
    └── cli.py                   # `googly-vr` entry: OSC listener loop
```

`pyproject.toml` console scripts (one shared src tree, two commands):

```toml
[project.scripts]
sim-eyes = "googly_vr.sim_eyes:main"
googly-vr = "googly_vr.cli:main"
```

## Stages

### Stage 0 — skeleton

* Write `README.md` (what/why, the pipeline diagram, quickstart).
* Poetry project: `pyproject.toml` with deps `python-osc` +
  `touchy-pad` (path `../../app`, develop = true), ruff + pytest dev
  group (same tooling expectations as the parent repo).
* **Poetry 2.x gotcha (learned in the parent repo):** path deps in
  `[tool.poetry.dependencies]` are *ignored* when a `[project]` table
  exists, so `poetry install` may not link touchy-pad. Fallback that
  is known to work there: `poetry run pip install -e ../../app`.
  Bake whichever works into a tiny `justfile` (`just install`,
  `just test`, `just run …`) so nobody hits this twice.
* Acceptance: `just install` then `sim-eyes --help` and
  `googly-vr --help` both run; `just test` green (even if only test
  collection).

### Stage 1 — `sim-eyes` (fake EyeTrackVR)

* `osc_proto.py`: the address constants above + an `EyeState` dataclass
  (left/right x, y, lid).
* `sim_eyes.py`: loop at ~10 Hz (our max target frame rate) sending the
  `EyeState` as individual OSC float messages to
  `udp://127.0.0.1:9000`.
  * Gaze: slow Lissajous/sine wander (`--pattern {wander,stare,crazy}`).
  * Blink: eyelid 1→0→1 over ~150 ms, Poisson-spaced
    (`--blink-rate`).
  * `--host`/`--port` flags (default localhost:9000) so we can also
    point it at another machine.
* Acceptance: `sim-eyes` runs and a debug listener (temporary
  `--dump` mode or `osc-dump`-style flag) sees plausible floats on
  port 9000.

### Stage 2 — `googly-vr` (eyes on the pad)

* `renderer.py`:
  * `build_eye_screen(pad)` — one screen, **absolute layout**, built
    from the DSL: per eye a socket `button` (`id="eye_l"` / `"eye_r"`,
    circle via `style(radius=…)`, dark sclera) plus a pupil `button`
    (`id="pupil_l"` / `"pupil_r"`, smaller circle). Saved once at
    startup via `pad.screen_save` and loaded. Widget ids are the
    contract — everything after startup addresses them by id.
  * `apply_eye_state(pad, state)` — map floats to pixels:
    * pupil `x` = socket center + `EyeX * max_travel_x`, `y` likewise
      (`max_travel` derived from socket size − pupil size);
    * blink: `LidExpanded < 0.2` ⇒ squash the socket's `h` to a slit
      (and shrink the pupil), else restore full `h`;
    * all through **one batched `pad.set_properties([...])` call per
      frame** (needs E2 landed first — see Stage 3) — never re-saving
      the screen.
  * Coalesce: build the per-frame batch from only the values whose
    integer pixels actually changed; if nothing moved, send nothing
    (at ~10 fps every round-trip is worth skipping).
* `cli.py`: `touchy_open()` (honors `TOUCHY_SIM_URL` for sim use),
  build + load the eye screen, then the `python-osc` UDP dispatch
  server on `127.0.0.1:9000` (loopback is where EyeTrackVR runs; a
  remote tracker is an explicit `--host 0.0.0.0`) → `apply_eye_state`.
  `--period` flag for the coalescing / target frame time (default
  100 ms — the ~10 fps ceiling; it also absorbs the faster rate real
  EyeTrackVR will one day send).
  *(Stage 5 refined this: the loop parks on an OSC update and only
  tries to connect to a touchy-pad as a side effect of one — at most
  every 5 s — so it costs nothing until tracking runs, and it never
  exits on its own.)*
* Acceptance: with real hardware attached, `sim-eyes` in one terminal
  and `googly-vr` in another, the eyes follow the sine wander and
  blink. (Against the *simulator* only the static screen shows — see
  Stage 3.)

### Stage 3 — touchy-pad enhancements (feed back to the parent project)

These are changes to `app/src/touchy_pad/` (and possibly firmware),
made because googly-vr needs them — but designed as general features
of touchy-pad, not googly-vr specials. Each lands as its own commit in
the parent repo with its own tests. (User has explicitly blessed this:
enhancing touchy-pad for googly-vr's sake is a welcome outcome.)

* **E1 — simulator honors property overrides.** Today
  `sim/device.py::_cmd_set_property` WARNs and returns OK (Qt, not
  LVGL), which means googly-vr's whole dev loop — the flagship
  no-hardware workflow of touchy-pad — can't animate. Teach the sim a
  small, explicitly-documented subset: `x`, `y`, `w`, `h` → Qt
  geometry, `bg_color`/`text_color` → styles, `text` → label text,
  `opa` → the existing opacity effect; anything else keeps the WARN +
  OK. Update the sim caveat in `docs/python-api.md` accordingly.
  Host-only change, no wire impact; pytest via the existing sim test
  harness. *This unblocks sim-driven development of googly-vr and any
  other live-property app.*
* **E2 — `SetPropertiesCmd` *replaces* `set_property`** (prerequisite
  for stage 2, not a "when profiling demands" nice-to-have): per-frame
  eye motion wants ~4 property writes (pupil x/y per eye, blink squash)
  and we want them in **one** round-trip. Per the project owner, this
  is done **instead of** keeping the singular form — *backwards
  compatibility is explicitly not a concern for now*. Wire change:
  new message `SetPropertiesCmd { repeated SetPropertyCmd props = 1; }`
  and `Command.set_properties = 14` **replacing** `Command.set_property`
  (tag reused with a new type — a deliberate wire break;
  `SysBoardInfoResponse.ProtocolVersion.CURRENT` 13→14). nanopb
  `.options`: cap `SetPropertiesCmd.props max_count:16` (two eyes fit
  easily). Firmware: the `set_properties` dispatch case funnels every
  entry through the existing Stage-lb12 override engine, all under
  **one** `lvgl_port_lock` section. Host: `TouchyClient.set_properties(...)`
  + `Touchy.set_properties(...)`; the singular `set_property` is
  **removed** (sweep `cli.py`'s `property set`, the sim, `docs/`, and
  the tests). Sim: `_cmd_set_property` becomes the batch-aware
  `_cmd_set_properties` — which is exactly where E1's real
  implementation lands. Docs: rewrite the `docs/python-api.md`
  §"Overriding widget properties at runtime" around the batched call.
  At the ~10 fps target, one batched RPC per frame is trivially cheap.
  googly-vr speaks only the batched form from day one.
* **E3 (speculative — do NOT build early) — smoothed/animator mode.**
  If USB jitter makes 10 fps pupil motion look steppy, a device-side
  "lerp to target" property flag would offload smoothing to LVGL
  animations. Only design this if reality demands it; do not grow the
  wire format speculatively.

Process note: E1/E2 follow the parent repo's rules — `just app-test`
+ `just app-lint` green, `just build-proto` after any proto edit, sim
behavior mirrored + pytested, and no auto-commits.

## Testing strategy

* googly-vr's own pytest suite (pure host-side, no hardware):
  * `osc_proto` round-trip: pack an `EyeState` → real OSC UDP send →
    python-osc server decodes → compare (loopback socket test).
  * Mapping math: float→pixel clamping, coalescing (no duplicate
    sends for unchanged values), blink hysteresis.
  * Screen build: constructing the eye screen produces the expected
    widget ids/geometry (no device needed — DSL objects are
    protobufs).
* Integration (manual, real + sim): `sim-eyes` and `googly-vr` in two
  terminals; the sim needs E1 for visible motion.
* touchy-pad changes: the parent repo's `just app-test` / `app-lint`.

## Risks & open questions

* **LVGL property names on-device**: the docs prove `"x"` and
  `"bg_color"` resolve; `"y"`, `"w"`, `"h"`, `"opa"` are expected
  members of the same LVGL v9 property-name table but must be
  confirmed on hardware early in stage 2 (one `touchy property set`
  session settles it). Fallback: numeric `lv_prop_id_t` — each batch
  entry carries `property_id` instead of `property_name`.
* **10 fps × ~4 property writes over USB** — a non-issue once E2
  batches them into one RPC per frame; even four singular round-trips
  at 10 Hz would likely be fine (the bulk pair is fast), but batching
  is cleaner anyway.
* **Poetry path-dep quirk** — handled in stage 0; revisit at pypi
  extraction time.
* **Submodule → standalone extraction**: keep `touchy_pad` imports in
  `renderer.py` only; keep the OSC vocabulary in `osc_proto.py`; no
  imports of parent-repo internals (`touchy_pad._proto` is off
  limits — public `touchy_pad.api` only).
* **Both eyes on one screen vs. VR-later**: left/right eye widgets are
  independent from day one (per-eye ids + per-eye OSC addresses), so a
  future two-display setup (one eye per panel) is a layout change, not
  a redesign.
* **UDP is stateless/lossy** — fine; `apply_eye_state` is idempotent
  and driven by absolute (not delta) values, so a dropped packet just
  costs one frame.
