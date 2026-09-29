"""``googly-vr`` — draw two cute googly eyes on a touchy-pad display,
driven by EyeTrackVR-style OSC messages (UDP :9000).

Runs against real USB hardware or the simulator (``export
TOUCHY_SIM_URL=...``); the connection comes from ``renderer.connect()``
because renderer.py is this project's only ``touchy_pad`` importer.
"""

from __future__ import annotations

import threading
import time

import click
from pythonosc import dispatcher, osc_server

from .osc_proto import ALL_ADDRESSES, EyeState
from .renderer import EyeRenderer, connect

DEFAULT_PORT = 9000
# ~10 fps ceiling — see docs/plans/general.md section 'Frame rate'.
DEFAULT_PERIOD = 0.1


class _Hub:
    """Latest-state mailbox between the OSC thread and the render loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = EyeState()

    def on_osc(self, address: str, *args: object) -> None:
        # pythonosc passes the mapped message args; our dialect is 1 float.
        if not args:
            return
        with self._lock:
            self._state.apply(address, float(args[0]))

    def snapshot(self) -> EyeState:
        with self._lock:
            return self._state.snapshot()


@click.command(name="googly-vr")
@click.option(
    "--host",
    default="0.0.0.0",
    show_default=True,
    help="OSC listen address (0.0.0.0 = also remote trackers).",
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
    pad = connect()
    info = pad.board_info
    width, height = info.display_width, info.display_height
    if not width or not height:
        raise click.ClickException("device reports no display (0x0) — can't draw eyes")

    renderer = EyeRenderer(pad, width, height, name=screen_name)

    hub = _Hub()
    disp = dispatcher.Dispatcher()
    for address in ALL_ADDRESSES:
        disp.map(address, hub.on_osc)
    server = osc_server.BlockingOSCUDPServer((host, port), disp)
    threading.Thread(target=server.serve_forever, daemon=True, name="osc-rx").start()

    click.echo(
        f"googly-vr: eyes on {width}x{height} (screen {screen_name!r}); "
        f"listening osc://{host}:{port}, frame time {period * 1000:.0f} ms"
    )
    try:
        while True:
            time.sleep(max(period, 0.01))
            renderer.apply(hub.snapshot())
    except KeyboardInterrupt:
        click.echo("googly-vr: bye")


if __name__ == "__main__":
    main()  # pragma: no cover
