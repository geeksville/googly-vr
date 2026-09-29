# googly-vr Stage 5 — loopback OSC, auto-reconnect, and host activity that keeps the display awake

> **Status (2026-09-29): items 1–2 implemented; item 3 implemented in firmware.**
> * **Item 1 (loopback OSC)** — DONE. `--host` defaults to `127.0.0.1`;
>   `--host 0.0.0.0` is the documented opt-in. Covered by `tests/test_cli.py`.
> * **Item 2 (never exit; lazy, OSC-driven search)** — DONE. `_Hub` gained an
>   update `Event`; `_open_pad()` / `_PadSearch` / `_render_loop` replace the old
>   10 Hz `sleep` loop; no failure path is fatal. `just test` = 23 passed,
>   `just lint` clean.
> * **Item 3 (host property batch resets the auto-off timer)** — DONE in the
>   parent repo: `firmware/main/api/host_api.cpp` calls `backlight_wake()` for a
>   non-empty batch; recorded as `docs/design.md` → Stage lb15.
>   `just firmware-build` green (host_api.cpp recompiled clean). The
>   **on-hardware check** (the panel stays lit while the eyes animate) still
>   needs a board — see item 3's checklist.
>
> **End-to-end smoke (in-process simulator, no hardware):** with a fake OSC
> tracker on :9000, `googly-vr` printed `eyes on 480x272 (screen 'eyes')` and
> drove the sim's property engine; with **no** OSC traffic it parked (no
> `connect()`, no `looking for touchy-pad`) and a real `SIGINT` exited it
> cleanly (`googly-vr: bye`, exit 0).
>
> Supersedes the loose bullet list that used to live in this file (kept verbatim
> at the bottom under "Original notes"). Follows `docs/plans/general.md`
> (stages 0–3 — the eye-rendering core, landed).

## Goal / summary

Three small usability improvements: two googly-vr-only, one a touchy-pad
(parent repo) behaviour fix.

1. **Listen on localhost only by default.** `googly-vr` currently binds its OSC
   socket to `0.0.0.0`, i.e. it accepts "eye tracking" from *any* machine on the
   LAN. The default becomes `127.0.0.1`; binding every interface stays available
   as an explicit opt-in (`--host 0.0.0.0`).
2. **Never exit on our own — find the pad lazily, driven by OSC updates.**
   googly-vr keeps running until **ctrl-c**, no matter what: a pad that is absent
   at startup, unplugged mid-run, headless (`0x0`) or running an incompatible
   firmware is something we keep looking for, and a pad attached minutes later is
   picked up on the next update. To keep that free, the search is
   **event-driven**: a connection is only ever *attempted* when an OSC update
   arrives on :9000 (rate-limited to one attempt per 5 s), so while no eye
   tracking is running the process costs one blocked UDP read — no timer, no
   polling. Today a missing pad exits with a traceback and a pad unplugged
   mid-run kills the render loop.
3. **Host property writes count as display activity.** A `SetPropertiesCmd`
   batch should reset the display auto-off (auto-sleep) timer, exactly like a
   touch or `ScreenWakeCmd` does. Without this, a host that animates the panel
   (googly-vr at ~10 fps) goes dark after `screen_timeout_ms` of "inactivity"
   even though the panel is visibly changing. **This one is a firmware change in
   the parent repo.**

### What this stage touches

| Side | Where | Item |
|---|---|---|
| googly-vr (host) | `src/googly_vr/cli.py`, new `tests/test_cli.py`, `README.md`, `docs/plans/general.md` | 1 + 2 |
| touchy-pad firmware (parent repo) | `firmware/main/api/host_api.cpp` (+ docs) | 3 |
| touchy-pad host libs (parent repo) | *nothing* — no Python/Rust API change | — |

**Wire format: unchanged.** No new proto fields/commands, nothing moved, so **no
`Widget.Version` / `ProtocolVersion` / `PreferencesFile.Version` bump** — item 3
only adds a side effect to an existing dispatch case. The simulator needs **no**
mirror either: it has no backlight and no auto-off timer
(`sim/device.py::_cmd_set_preferences` already treats `screen_timeout_ms` as a
stored no-op), so there is nothing to keep in sync.

Validation: googly-vr `just test` / `just lint`; parent repo `just app-test`,
`just app-lint`, `just firmware-build` (default board `jc4827w543`).

## What exists today (findings)

* `src/googly_vr/cli.py::main()` does `pad = connect()` — one attempt, no
  retry — reads `pad.board_info` (a **cached** `SysBoardInfoResponse` captured at
  open time; `Touchy.board_info` is a plain attribute set in `__init__`, so a
  reconnect must call `touchy_open()` again to refresh it), builds
  `EyeRenderer(pad, w, h, name)`, starts the OSC server, and then paces a loop
  with `time.sleep(max(period, 0.01))` + `renderer.apply(hub.snapshot())` — i.e.
  a 10 Hz timer that runs whether or not anything happened.
* `_Hub` is a lock-guarded latest-value mailbox with **no wakeup signal**, so the
  loop cannot currently block on "an OSC update arrived" — item 2 adds a
  `threading.Event` to it (and the loop's pacing deadline moves into the loop),
  which is what lets the whole thing idle at zero CPU.
* `renderer.connect()` is a one-line wrapper over
  `touchy_pad.api.touchy_open()`, which enumerates USB → UART-bridge →
  `TOUCHY_SIM_URL` → in-process sim and **raises** when nothing is found
  (`DeviceNotFoundError`, a `TransportError`), when the device can't be opened,
  or when its firmware is too old/new (`IncompatibleFirmwareError`). A mid-run
  disconnect surfaces as `TransportError` / libusb `USBError` / `OSError` from the
  transport, or as a `TouchyError` from a failed RPC.
* `EyeRenderer.__init__` already saves **and** loads the eye screen, and
  `reset()` exists for "forget what was already sent (e.g. after a device
  reconnect)". So a reconnect is: new `touchy_open()` + new `EyeRenderer` (fresh
  screen upload, empty coalescing table). The building blocks are already there.
* Parent repo, `firmware/main/backlight.{h,cpp}`: the auto-sleep `esp_timer` is
  re-armed only by `backlight_wake()` (aliased as `backlight_touch_activity()`).
  Today's callers are the LVGL indev `LV_EVENT_PRESSED` lambda in `main.cpp`
  (touch) and the `screen_wake` case in `api/host_api.cpp`.
* `api/host_api.cpp`'s `set_properties` case (stage lb14) runs
  `widget_property_set_batch()` and returns — it never notifies the backlight
  manager, so an animating host does not count as activity.


## Item 1 — loopback-only OSC by default

**Change** (`src/googly_vr/cli.py`):

* `--host` default `"0.0.0.0"` → `"127.0.0.1"`, with the help text spelling out
  the trade-off:

  ```
  help="OSC listen address (default: loopback only). "
       "Use 0.0.0.0 to also accept a tracker running on another machine.",
  ```

* Nothing else changes: `osc_server.BlockingOSCUDPServer((host, port), disp)`
  already honours whatever the flag says, so `--host 0.0.0.0` remains the one-line
  opt-in for a remote tracker. `sim-eyes` already defaults to `127.0.0.1` as a
  *destination*, so the default pair works unchanged.

**Rationale.** This socket carries untrusted, unauthenticated input that directly
drives what the panel displays — it should not be reachable from the network
unless the user asks. Real EyeTrackVR runs on the *same* machine (loopback) by
definition, so this costs nothing for the intended pipeline; the `0.0.0.0` bind
was only ever needed for a hypothetical remote tracker.

**Docs.** `docs/plans/general.md` Stage 2 says the server binds `0.0.0.0:9000`
"(so real EyeTrackVR later is drop-in)" — reword to "127.0.0.1:9000 by default
(loopback is where EyeTrackVR runs); `--host 0.0.0.0` opts into a remote
tracker". Add a line to the README "Commands" table and mention the default in
the Quickstart.

## Item 2 — never exit on our own: find the pad lazily, from OSC updates

**Shape of the change** (`src/googly_vr/cli.py`). The render loop stops being a
10 Hz polling timer and becomes *event-driven*: it blocks until an OSC update
lands, and a connection attempt happens **only** as a side effect of such an
update. With no tracking running, or with the pad away and nothing changing, the
process is parked in two blocked waits (the UDP `recvfrom` in the OSC thread and
an `Event.wait()` in the render thread) — zero CPU, no timer. Nothing is ever
fatal: every failure just becomes a retry reason printed at most once every 5 s.

```python
#: Minimum gap between touchy-pad connection attempts (seconds).
RECONNECT_INTERVAL_S = 5.0

def _now() -> float:                     # seam: tests patch googly_vr.cli._now
    return time.monotonic()

class _Hub:
    """Latest-state mailbox + a zero-cost 'a value arrived' wakeup.

    `wait()` blocks until an OSC update lands, so while the tracker is quiet
    the render thread costs one parked Event — no polling.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = EyeState()
        self._update = threading.Event()

    def on_osc(self, address: str, *args: object) -> None:
        if not args:
            return
        with self._lock:
            self._state.apply(address, float(args[0]))
        self._update.set()               # wakes the render thread

    def snapshot(self) -> EyeState:
        with self._lock:
            return self._state.snapshot()

    def wait(self) -> None:
        """Block until an update (or an update that already arrived) is seen."""
        self._update.wait()

    def reset_update(self) -> None:
        """Re-arm; call *before* sampling so a concurrent update is not lost."""
        self._update.clear()

def _open_pad() -> Touchy:
    """Connect and prove we can drive it — raises on anything wrong."""
    pad = connect()                      # module-level: tests patch it
    info = pad.board_info
    if not info.display_width or not info.display_height:
        pad.close()                      # 0x0: not drivable, but *not* fatal —
        raise RuntimeError(              #   a later pad may well have a panel
            f"touchy-pad reports no display ({info.display_width}x{info.display_height})"
        )
    return pad

class _PadSearch:
    """Rate-limited, OSC-driven search for a drivable touchy-pad.

    `maybe_connect()` is called on every OSC update and is suppressed until
    `interval` has elapsed since the previous attempt, so even a 100 Hz
    tracker costs at most one enumeration per 5 s while nothing is attached.
    The 'looking for touchy-pad' banner is printed once per search episode.
    """

    def __init__(
        self,
        interval: float = RECONNECT_INTERVAL_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._interval = interval
        self._clock = clock or _now      # late-bound, so tests patch cli._now
        self._next_at = 0.0              # nothing tried yet → the 1st is now
        self._searching = False

    def maybe_connect(self, echo) -> Touchy | None:
        now = self._clock()
        if now < self._next_at:
            return None                  # rate-limited: a cheap no-op, no I/O
        self._next_at = now + self._interval
        try:
            pad = _open_pad()
        except Exception as exc:         # transports raise a zoo of types
            if not self._searching:
                echo("looking for touchy-pad (ctrl-c to exit)…", err=True)
                self._searching = True
            echo(f"  … not found ({type(exc).__name__}: {exc}); "
                 f"retrying at most every {self._interval:g}s", err=True)
            return None
        self._searching = False
        return pad
```

`main()` keeps the OSC server + dispatch map it has today, then hands off to a
loop that is driven entirely by updates:

```python
def _render_loop(hub: _Hub, search: _PadSearch, period: float,
                 screen_name: str, echo) -> None:
    """Drive the eyes from OSC updates until ctrl-c.

    Blocks for an update before doing anything, so an idle process costs
    nothing. A frame is *sent* at most once every `period` (the ~10 fps
    ceiling), which also coalesces a faster real tracker down to that rate.
    A missing / unplugged / undrivable pad is never fatal: it just means the
    next update tries to connect again (rate-limited inside `_PadSearch`).
    """
    pad: Touchy | None = None
    renderer: EyeRenderer | None = None
    next_frame = 0.0

    while True:
        hub.wait()                       # ← the whole idle cost: one parked wait
        hub.reset_update()               # consume this wakeup: the paths below
        #                                  either sample the state or skip it
        if renderer is None:
            pad = search.maybe_connect(echo)     # only ever on an update …
            if pad is None:
                continue                         # … and rate-limited inside
            try:
                info = pad.board_info
                renderer = EyeRenderer(pad, info.display_width,
                                       info.display_height, name=screen_name)
            except Exception as exc:
                echo(f"googly-vr: found a touchy-pad but can't drive it "
                     f"({type(exc).__name__}: {exc}) — looking again…", err=True)
                pad.close()
                pad = renderer = None
                continue
            echo(f"eyes on {info.display_width}x{info.display_height} "
                 f"(screen {screen_name!r})")
            next_frame = 0.0             # paint on this very update

        if _now() < next_frame:
            continue                     # `--period` ceiling: wait for the next one

        state = hub.snapshot()           # sampled after the clear above, so an
        #                                  update during apply() re-arms the flag
        try:
            renderer.apply(state)
            next_frame = _now() + period
        except Exception as exc:
            echo(f"googly-vr: lost the touchy-pad ({type(exc).__name__}: {exc}) "
                 f"— looking again…", err=True)
            pad.close()                  # release the handle before re-enumerating
            pad = renderer = None        # the next update restarts the search


@click.command(name="googly-vr")
...
def main(host: str, port: int, period: float, screen_name: str) -> None:
    """Listen to OSC eye tracking and animate the googly eyes."""
    hub = _Hub()
    disp = dispatcher.Dispatcher()
    for address in ALL_ADDRESSES:
        disp.map(address, hub.on_osc)
    server = osc_server.BlockingOSCUDPServer((host, port), disp)
    threading.Thread(target=server.serve_forever, daemon=True, name="osc-rx").start()

    click.echo(
        f"googly-vr (https://github.com/geeksville/googly-vr): listening "
        f"osc://{host}:{port} — waiting for eye tracking, frame time "
        f"{period * 1000:.0f} ms (ctrl-c to exit)"
    )
    try:
        _render_loop(hub, _PadSearch(), period, screen_name, click.echo)
    except KeyboardInterrupt:
        click.echo("googly-vr: bye")
```

**Design decisions and why:**

* **Connections are attempted *only* when an OSC update arrives** — this is the
  owner's refinement of the original "retry every 5 s": keep trying forever, but
  do it *lazily*. `search.maybe_connect()` is only reachable from the render
  loop, which only runs after `hub.wait()` returns, i.e. after a packet. So a
  googly-vr that is running before the tracker (or after it dies) costs exactly
  one blocked `Event.wait()` plus the OSC thread's blocked `recvfrom`, and a pad
  attached minutes later is picked up on the next update. The 5 s interval stays
  as a **rate limit** so a 10–100 Hz stream can't become 10–100 USB enumerations
  per second while nothing is attached.
* **Nothing is fatal.** `_open_pad()` is the "connect *and* drive" test:
  `touchy_open()` already performs a `sys_board_info_get` RPC before returning,
  and we additionally require a non-zero display, because a `0x0` panel (a
  headless board, an unconfigured LED matrix, a failed bring-up) can't show eyes
  *yet*. That, an incompatible firmware, or any transport error is raised as a
  **retry reason** (`… not found (RuntimeError: touchy-pad reports no display
  (0x0))`) and looked at again on the next update — the process exits only on
  ctrl-c.
* **No lost wakeups.** `hub.wait()` parks on a `threading.Event` that every OSC
  packet sets, and the loop clears it immediately after `wait()` returns (i.e.
  before it samples). An update landing during `apply()` re-arms the flag, and
  an update the loop deliberately skips (rate-limited connect, `--period`
  ceiling) still reaches the *next* sample because the hub always holds the
  latest state — so nothing is dropped and `wait()` never spins on a stale flag.
* **The ~10 fps ceiling survives the refactor.** `--period` now means "at most one
  `set_properties` batch per N ms", enforced by a deadline (`next_frame`) rather
  than by `sleep`. A fast real tracker (EyeTrackVR can push 100+ Hz) wakes the
  loop once per packet but *sends* once per period; a slow one sends once per
  packet. Nothing is dropped — the state sampled is always the latest.
* **A new `EyeRenderer` per connection,** never a reused one: the pad object is
  new, the display size may differ (different board, or firmware update), and the
  device may have rebooted — wiping the saved screen *and* the sticky RAM-only
  overrides. Re-building re-uploads + re-loads the eye screen and starts with an
  empty coalescing table, so the first frame after a connect re-sends every
  property. (`EyeRenderer.reset()` stays as the public "reuse a live pad" API,
  still covered by the existing renderer tests; this loop just doesn't need it.)
* **`pad.close()` on every failure path** (a failed `EyeRenderer` build, a failed
  frame, a drop). Without it the libusb handle stays claimed and the next open can
  fail even though the pad is back — which would turn a three-second cable wobble
  into a stuck search.
* **Status on stderr, stdout stays the one "running" line.** The banner, the
  per-attempt lines and "lost the touchy-pad" use `click.echo(..., err=True)`;
  the startup line and "eyes on …" stay on stdout. The startup line names what we
  are waiting for (`… listening osc://127.0.0.1:9000 — waiting for eye tracking,
  frame time 100 ms (ctrl-c to exit)`), so an inactive process doesn't look hung.
* **`cli.py` keeps its "no runtime `touchy_pad` imports" rule** (the submodule
  extraction rule from `general.md`): the `Touchy` / `EyeRenderer` annotations in
  the sketches come from a `TYPE_CHECKING` guard or are dropped — at runtime
  `cli.py` only reaches the pad through `renderer.connect()` /
  `renderer.EyeRenderer`, exactly as today.

**User-visible behaviour:**

| Situation | What the user sees |
|---|---|
| Started, no eye tracking yet | the startup line, then silence — the process is parked on the OSC socket (nothing is polled, nothing is attempted) |
| Tracker starts, no pad attached | `looking for touchy-pad (ctrl-c to exit)…` plus one `… not found (…)` line per attempt — at most one attempt every 5 s, for as long as updates keep arriving |
| Pad attached at any time | `eyes on 480x320 (screen 'eyes')` and the eyes start animating on the next update (≤100 ms at 10 Hz) |
| Pad unplugged mid-run | `googly-vr: lost the touchy-pad (…) — looking again…`, then the banner + 5 s attempts on subsequent updates |
| Pad plugged back in | eyes re-drawn within ~5 s (the next attempt window) |
| Headless pad (`0x0`) | `… not found (RuntimeError: touchy-pad reports no display (0x0))`, retried forever, **never fatal** |
| Pad on old/new firmware | same, with `IncompatibleFirmwareError: …` as the reason |
| Tracker stops (pad still fine) | the panel holds the last frame; nothing is sent (no timer) |
| ctrl-c | `googly-vr: bye`, exit 0 |
| Simulator | identical (`TOUCHY_SIM_URL` is just another transport behind `touchy_open()`) |

**Not in scope** (deliberate): pinning a specific device (`--serial` / `--url`
pass-through to `touchy_open()`); proactive drop detection while the tracker is
silent (a USB hotplug watch or a keepalive poll would reintroduce exactly the
polling this item removes — see R11); and any change to `bin/start-real.sh` (still
a `fixme` stub for the future frameeyeosc integration). Start order no longer
matters: `googly-vr` first, pad and/or tracker whenever.

## Item 3 — a host property batch resets the display auto-off timer (parent repo, **Stage lb15**)

**Change** (`firmware/main/api/host_api.cpp`, `set_properties` case):

```cpp
    case touchy_Command_set_properties_tag: {
        // googly-vr / stage lb14 — override a batch of LVGL properties on
        // named widgets, applied in order under one lock acquisition. …
        resp->code = widget_property_set_batch(cmd->cmd.set_properties)
                         ? touchy_ResultCode_OK
                         : touchy_ResultCode_INVALID_ARG;
        // Stage lb15 — a host-driven property write is display *activity*:
        // reset the auto-sleep countdown (and wake if already asleep), the
        // same way a touch or a ScreenWakeCmd does. Otherwise a host that
        // animates the panel (googly-vr at ~10 fps) goes dark after
        // `screen_timeout_ms` of "inactivity" while the panel is visibly
        // changing. Nothing to do for an empty batch.
        if (cmd->cmd.set_properties.props_count > 0) backlight_wake();
        break;
    }
```

One `#include "backlight.h"` is added to `host_api.cpp`. That is the whole
firmware change: no new proto field, no new command, no version bump, and **no
host-side change** — googly-vr keeps sending its normal `set_properties` batches
and the panel simply stops blanking.

**Why this call site:**

* `api/host_api.cpp` is the single transport-independent chokepoint — USB vendor
  bulk, USB-CDC, UART, the HTTP(S) protobuf endpoint and the JSON endpoint all
  funnel through `host_api_dispatch_message()` → this `dispatch()`, so one line
  covers every way a host can set a property.
* It is the existing home of "a host command counts as activity": the
  `screen_wake` case two branches up already calls `backlight_wake()`.
* Rejected alternatives: poking inside `widget_property_set_batch()` (puts host
  activity policy in the widget layer, and would also fire for an empty batch);
  adding a `backlight_host_activity()` alias next to `backlight_touch_activity()`
  (the touch alias exists because its call site is an opaque LVGL lambda; here a
  one-line comment is enough — the API surface stays as it is); and a host-side
  heartbeat (`screen_wake` every frame from googly-vr) — that is a workaround for
  a device-side omission, wastes an RPC per frame, and would leave every other
  animating host broken.

**Scope note (open question, see below):** `run_actions` and `set_preferences`
keep today's behaviour — only *property setting* resets the timer, per the
requirement.

**Docs to update in the parent repo:**

* `docs/design.md` — new `## Stage lb15: host property writes reset the display
  auto-off timer — DONE` section (same shape as Stage lb14), stating explicitly
  that the wire format is unchanged.
* `AGENTS.md` — one highlight bullet after the lb14 entry.
* `docs/host-api.md` — `Screen_Wake` / auto-sleep bullet: list the activity
  sources (touch, `Screen_Wake`, `SetPropertiesCmd` batch). Drive-by: the same
  list still says `Screen_Sleep_Timeout(msec) — Auto sleep after msec of
  inactivity`, which Stage 82 replaced with `SetPreferencesCmd` — fix or annotate
  while there.
* `docs/python-api.md` — one sentence in "Overriding widget properties at
  runtime": a batch also counts as display activity, so an animation keeps the
  panel awake.
* No simulator change and no sim test: the sim has no backlight/auto-off, and
  `sim/device.py::_cmd_set_preferences` already stores `screen_timeout_ms` as a
  no-op. Say so in the `docs/design.md` section so the omission is clearly
  deliberate.

**How this is verified** (firmware has no unit tests):

1. `just firmware-build` green (points 1–3 are all compile-safe).
2. On hardware: `touchy pref backlight-timeout 5` (5 s auto-off), then run
   `googly-vr` against `sim-eyes` — the panel must **stay lit** while the eyes
   move, and must still blank ~5 s after the OSC stream *and* the property
   batches stop (e.g. ctrl-c both).
3. Regression: with googly-vr stopped, `screen_timeout_ms` still blanks the
   panel after 5 s (i.e. the poke did not disable auto-sleep), and touching the
   panel still wakes it.

**Independent of item 1/2.** The three items touch disjoint files and can land as
three separate commits (see the parent repo's no-auto-commit rule).

## File & component layout

```
tools/googly-vr/                        # this submodule
├── src/googly_vr/
│   ├── cli.py                          # items 1+2: --host default, _Hub Event,
│   │                                   #   _open_pad/_PadSearch, OSC-driven loop
│   ├── renderer.py                     # unchanged (connect()/EyeRenderer already fit)
│   └── osc_proto.py, sim_eyes.py       # unchanged
├── tests/
│   ├── test_cli.py                     # NEW — loopback default + retry/reconnect
│   ├── test_renderer.py                # unchanged
│   └── test_osc_proto.py               # unchanged
├── README.md                           # commands table + quickstart wording
└── docs/plans/general.md               # Stage-2 bind-address wording; link stage 5

touchy-pad (parent repo)
├── firmware/main/api/host_api.cpp      # item 3: backlight_wake() on property batches
├── docs/design.md                      # Stage lb15 section
├── AGENTS.md                           # lb15 highlight bullet
├── docs/host-api.md                    # auto-sleep activity list (+ stale line)
└── docs/python-api.md                  # one sentence on auto-activity
```

## Phased implementation sequence

| Phase | Work | Acceptance |
|---|---|---|
| 0 | Land item 1 alone: `--host` default + help, README + `general.md` wording | `just test` green; `googly-vr --help` shows `127.0.0.1`; `ss -lun` shows the socket bound to loopback |
| 1 | Item 2 refactor: `_Hub` update event, `_now`, `_open_pad`, `_PadSearch`, `_render_loop`; new `tests/test_cli.py` | `just test`/`just lint` green; manual with `sim-eyes` running and no pad: banner + 5 s attempts; pad attached at any moment → eyes; unplug → banner again; re-plug → eyes; stop `sim-eyes` → no further attempts (and no wakeups in `top`) |
| 2 | Item 3 firmware poke + the four doc updates (parent repo) | `just firmware-build` green; hardware checklist in item 3 (stay lit while animating, still blank when idle) |
| 3 | Bookkeeping: `general.md` links this plan (**already added**); `docs/design.md` Stage lb15 status → DONE when phase 2 lands; parent `activeContext.md`/`progress.md` refreshed | docs match reality; nothing committed by the agent |

Phases 0–1 are pure googly-vr (Poetry/pytest only, no hardware needed). Phase 2
needs a board for its acceptance, but its compile check is part of the normal
firmware build. Phase 3 is documentation only.

## Testing strategy

**googly-vr — new `tests/test_cli.py`** (pure host-side, no hardware, no real
sleeps, no real sockets). Seams: `cli._Hub` is built inside `main()` and
`cli.connect` / `cli.EyeRenderer` are module-level names; time is read only via
`cli._now`, and `_PadSearch` takes an injectable `clock`. So a test scripts a
sequence of updates plus clock readings, and a fake hub whose `wait()` raises
`KeyboardInterrupt` once its script is exhausted ends `main()` deterministically.

* `test_default_host_is_loopback_only` — capture the
  `osc_server.BlockingOSCUDPServer` address; assert `("127.0.0.1", 9000)` by
  default and that `--host 0.0.0.0` still passes `0.0.0.0` through.
* `test_no_connect_attempt_while_osc_is_silent` — a fake hub that ends the loop
  with no update at all; assert `connect` was **never** called and nothing was
  rendered (the "idle costs one blocked wait" guarantee).
* `test_connect_only_on_updates_and_rate_limited` — updates at t=0, 1, 6 s with
  `connect` always raising `DeviceNotFoundError`; assert exactly two attempts,
  and that the banner printed once and each reason line once.
* `test_pad_appearing_later_is_picked_up` — `connect` fails once then returns a
  fake pad; assert `EyeRenderer` was built, `eyes on …` printed, and the same
  update already drove a `set_properties` batch.
* `test_no_display_keeps_searching` — `board_info` of `0x0`: no exception, a
  "no display" retry line, and a second attempt after the interval (never fatal).
* `test_incompatible_firmware_keeps_searching` — same shape with
  `IncompatibleFirmwareError`, pinning the "no fatal path" rule.
* `test_frame_failure_closes_the_pad_and_restarts_the_search` — a fake pad whose
  `set_properties` raises; assert the "lost the touchy-pad" line, that `close()`
  was called on it, and that a later update rebuilt the renderer.
* `test_period_caps_the_frame_rate` — 100 updates inside one `period` → exactly
  one `apply()`; updates spaced 2 × `period` apart → one `apply()` each.
* `test_ctrl_c_says_bye` — `KeyboardInterrupt` from the fake hub's `wait()` →
  `googly-vr: bye`, exit 0.

Existing `test_renderer.py` / `test_osc_proto.py` are untouched and keep passing
(the coalescing test still covers `reset()`), and the OSC loopback round-trip test
still proves the `python-osc` server/client pair works on loopback.

**Parent repo:** item 3 adds no Python/Rust surface, so `just app-test` /
`just app-lint` are a regression check only. Verification of the behaviour is
the three-step hardware checklist in item 3 plus `just firmware-build`.

## Risks & open questions

| # | Item | Risk / question | Proposed handling |
|---|---|---|---|
| R1 | 2 | Broad `except Exception` can mask a real bug (e.g. a typo'd attribute) as an endless "looking for touchy-pad" loop. | The exception type + message is echoed, so a wrong failure is visible rather than silent; attempts (and therefore lines) are capped at one per 5 s, so it can't flood; `tests/test_cli.py` drives the loop with fakes, so an obvious regression fails CI. |
| R2 | 2 | A raw traceback can still appear *between* our friendly lines: `Touchy`'s background event thread prints one when the transport dies (a path we cannot reach from googly-vr). | Accept for now — it is genuinely diagnostic, and our line is the friendly one. Optional later: parent-repo change to route it through `logging.getLogger(__name__)` at WARNING instead of `traceback.print_exc()`. Not in this stage (it would also silence the diagnostic for everyone else). |
| R3 | 2 | A **headless (`0x0`)** or **incompatible-firmware** pad retries forever and cannot succeed until the user acts (provision a board config, re-flash). | Intentional per the owner: never exit on our own — and a *different* pad may be attached at any time. The reason is printed (≤1 line per 5 s), so it is diagnosed rather than hidden. Nicety for later: after N consecutive `IncompatibleFirmwareError`s, add a "run `touchy update`" hint — still without exiting. |
| R4 | 2 | Two pads attached: `touchy_open()` picks the first found and the user cannot select one. | Out of scope; the retry loop makes it at worst sticky, never fatal. Add `--serial`/`--url` pass-through later if it bites. |
| R5 | 2 | The re-`connect()` after a drop can succeed against a *different* pad and silently move the eyes there. | Same as R4 — acceptable for now; mentioned so it is a conscious choice. |
| R6 | 3 | Should `run_actions` (which can also mutate the live UI, e.g. `ActionChangeWidgetRef`) and `set_preferences` (which includes `current_screen`) also reset the timer? | Requirement says *property setting*; keep those as they are and revisit if another host app needs it. One-line change either way. |
| R7 | 3 | A misbehaving host that sets one property every 4 s now keeps the panel awake indefinitely — i.e. it can defeat auto-off. | Accepted: that *is* the requested behaviour (explicit host activity beats the idle timer, exactly like touch), it is bounded by the user's own host process, and `screen_timeout_ms = 0` remains the explicit "never sleep". |
| R8 | — | The parent-repo half is described *here* rather than in the parent's `docs/plans/` (the parent rule says plans live in `docs/plans/<topic>.md`; that directory is still empty). | Deliberately kept in this submodule's plan, since it is one line of firmware serving *this* app's plan, and it will be recorded as Stage lb15 in the parent's `docs/design.md`. Say the word if you'd rather it also appear as `docs/plans/googly-vr-support.md` in the parent repo. |
| R9 | 1 | Binding to `127.0.0.1` breaks a genuinely remote tracker (e.g. EyeTrackVR on another box). | `--host 0.0.0.0` is the documented opt-in, in the help text and README. |
| R10 | 2 | **Nothing is attempted until tracking data arrives**, so a googly-vr started on its own looks idle — a user might think it hung. | Mitigated by the startup line, which names what it is waiting for (`… listening osc://127.0.0.1:9000 — waiting for eye tracking … (ctrl-c to exit)`), and by the behaviour table. Tracking traffic is the trigger by design. |
| R11 | 2 | A drop is only noticed on the **next update**: if the tracker is silent when the pad goes away, a stale claimed handle (and a stale on-screen frame) can persist indefinitely. | Accepted: nothing needs displaying in that window, the device keeps rendering its last frame, and noticing the drop without traffic would need a timer or a USB hotplug watcher — exactly the polling this item removes. Revisit if a real case shows up. |
| R12 | 2 | A very fast tracker wakes the loop once per packet (one `Event.wait()` + two `monotonic()` calls per packet). | Bounded and cheap, and one RPC per `--period` is still guaranteed (pinned by `test_period_caps_the_frame_rate`); `--period` keeps its 100 ms default. |

