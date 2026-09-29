"""``googly-vr`` — draw two cute googly eyes on a touchy-pad display,
driven by EyeTrackVR-style OSC messages (UDP :9000).

Runs against real USB hardware or the simulator (``export
TOUCHY_SIM_URL=...``); the connection comes from ``renderer.connect()``
because renderer.py is this project's only ``touchy_pad`` importer.

The render loop is *event-driven* (stage 5): it parks on an OSC update and only
ever tries to connect to a touchy-pad as a side effect of one, so running before
the tracker — or with the pad unplugged — costs a blocked UDP read and nothing
else (no timer, no polling). Nothing is fatal: a pad attached at any moment is
picked up on the next update, and the process exits only on ctrl-c.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import click
from pythonosc import dispatcher, osc_server

from .osc_proto import ALL_ADDRESSES, EyeState
from .renderer import EyeRenderer, connect

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Type-only: cli.py must not import touchy_pad at runtime (docs/plans/general.md,
    # "keep every touchy_pad import in renderer.py").
    from .renderer import Touchy

DEFAULT_PORT = 9000
# ~10 fps ceiling — see docs/plans/general.md section 'Frame rate'.
DEFAULT_PERIOD = 0.1
#: Minimum gap between touchy-pad connection attempts (seconds).
RECONNECT_INTERVAL_S = 5.0

#: ``click.echo``-shaped sink (tests pass a recorder).
Echo = Callable[..., None]


def _now() -> float:
    """Monotonic clock — an indirection so tests can drive the loop's timing."""
    return time.monotonic()


class _Hub:
    """Latest-state mailbox between the OSC thread and the render loop.

    Besides the lock-guarded latest :class:`EyeState` this carries a
    :class:`threading.Event` that every OSC update sets, so the render loop can
    *block* on "an update arrived" instead of polling: while the tracker is
    quiet the whole process parks in one ``Event.wait()``.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = EyeState()
        self._update = threading.Event()

    def on_osc(self, address: str, *args: object) -> None:
        # pythonosc passes the mapped message args; our dialect is 1 float.
        if not args:
            return
        with self._lock:
            self._state.apply(address, float(args[0]))
        self._update.set()  # wake the render loop

    def snapshot(self) -> EyeState:
        with self._lock:
            return self._state.snapshot()

    def wait(self) -> None:
        """Park until an OSC update lands (immediately, if one already has)."""
        self._update.wait()

    def reset_update(self) -> None:
        """Re-arm the wakeup — called right after :meth:`wait` returns, so the
        callers below either sample the state or deliberately skip this update
        (the hub always holds the latest state, so a skip never loses data)."""
        self._update.clear()


def _open_pad() -> Touchy:
    """Connect to a touchy-pad and prove we can drive it.

    Raises (rather than returning ``None``) on anything wrong — no device
    attached, an incompatible firmware, or a panel with no usable display —
    because every one of those is a *retry reason* for :class:`_PadSearch`,
    never a fatal error.
    """
    pad = connect()
    info = pad.board_info
    if not info.display_width or not info.display_height:
        pad.close()
        raise RuntimeError(
            f"touchy-pad reports no display ({info.display_width}x{info.display_height})"
        )
    return pad


class _PadSearch:
    """Rate-limited, OSC-driven search for a drivable touchy-pad.

    ``maybe_connect()`` is called for every OSC update (see
    :func:`_render_loop`) and is suppressed until ``interval`` has elapsed
    since the previous attempt, so even a 100 Hz tracker costs at most one
    device enumeration per 5 s while nothing is attached. The
    ``looking for touchy-pad`` banner is printed once per search episode.
    """

    def __init__(
        self,
        interval: float = RECONNECT_INTERVAL_S,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._interval = interval
        self._clock = clock or _now
        self._next_at = 0.0  # nothing tried yet → the first attempt is "now"
        self._searching = False

    def maybe_connect(self, echo: Echo) -> Touchy | None:
        now = self._clock()
        if now < self._next_at:
            return None  # rate-limited: a cheap no-op, no device I/O
        self._next_at = now + self._interval
        try:
            pad = _open_pad()
        except Exception as exc:  # noqa: BLE001 — every failure is retryable
            if not self._searching:
                echo("looking for touchy-pad (ctrl-c to exit)…", err=True)
                self._searching = True
            echo(
                f"  … not found ({type(exc).__name__}: {exc}); "
                f"retrying at most every {self._interval:g}s",
                err=True,
            )
            return None
        self._searching = False
        return pad


def _render_loop(
    hub: _Hub,
    search: _PadSearch,
    period: float,
    screen_name: str,
    echo: Echo,
) -> None:
    """Drive the eyes from OSC updates until ctrl-c.

    Blocks for an update before doing anything, so an idle process costs
    nothing. A frame is *sent* at most once every ``period`` (the ~10 fps
    ceiling), which also coalesces a faster real tracker down to that rate. A
    missing / unplugged / undrivable pad is never fatal: the next update simply
    tries to connect again (rate-limited by ``search``).
    """
    pad: Touchy | None = None
    renderer: EyeRenderer | None = None
    next_frame = 0.0

    while True:
        hub.wait()  # ← the whole idle cost: one parked wait
        # Consume this wakeup. Every path below either samples the state or
        # deliberately skips it; the hub always holds the latest state, so a
        # skip never loses data — and clearing here keeps `wait()` from
        # spinning on a stale flag.
        hub.reset_update()

        if renderer is None:
            pad = search.maybe_connect(echo)  # only ever on an update …
            if pad is None:
                continue  # … and rate-limited inside `search`
            try:
                info = pad.board_info
                renderer = EyeRenderer(
                    pad, info.display_width, info.display_height, name=screen_name
                )
            except Exception as exc:  # noqa: BLE001 — retry on the next update
                echo(
                    f"googly-vr: found a touchy-pad but can't drive it "
                    f"({type(exc).__name__}: {exc}) — looking again…",
                    err=True,
                )
                pad.close()
                pad = renderer = None
                continue
            echo(f"eyes on {info.display_width}x{info.display_height} (screen {screen_name!r})")
            next_frame = 0.0  # paint on this very update

        if _now() < next_frame:
            continue  # `--period` ceiling: wait for a later update

        state = hub.snapshot()
        try:
            renderer.apply(state)
            next_frame = _now() + period
        except Exception as exc:  # noqa: BLE001 — a dead pad is not fatal
            echo(
                f"googly-vr: lost the touchy-pad ({type(exc).__name__}: {exc}) — looking again…",
                err=True,
            )
            if pad is not None:
                pad.close()  # release the handle before re-enumerating
            pad = renderer = None  # the next update restarts the search


@click.command(name="googly-vr")
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help=(
        "OSC listen address (loopback only by default). "
        "Use 0.0.0.0 to also accept a tracker running on another machine."
    ),
)
@click.option(
    "--port",
    type=int,
    default=DEFAULT_PORT,
    show_default=True,
    help="OSC listen port (EyeTrackVR convention: 9000).",
)
@click.option(
    "--period",
    type=float,
    default=DEFAULT_PERIOD,
    show_default=True,
    help="Target frame time in seconds — the ~10 fps ceiling; also absorbs a faster real tracker.",
)
@click.option(
    "--screen-name",
    default="eyes",
    show_default=True,
    help="On-device screen name (F:host/s/<name>.pb).",
)
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


if __name__ == "__main__":
    main()  # pragma: no cover
