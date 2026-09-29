"""``sim-eyes`` — broadcast fake EyeTrackVR tracking over OSC.

Stand-in for the EyeTrackVR half of the pipeline (no Steam Frame yet):
sends plausible per-eye gaze/lid floats to UDP 127.0.0.1:9000 at the ~10 fps
target frame rate, in the exact VRCFT dialect a real tracker will one day
use — so swapping in the real thing later means stopping this process.
"""

from __future__ import annotations

import math
import random
import time

import click
from pythonosc.udp_client import SimpleUDPClient

from .osc_proto import EyeState

#: One blink lasts this long (seconds), lid 1 → 0 → 1.
BLINK_DURATION_S = 0.15

#: Default send rate — the pipeline's ~10 fps ceiling (see docs/plans/general.md).
DEFAULT_RATE_HZ = 10.0


def gaze_at(t: float, pattern: str) -> tuple[float, float]:
    """Pure gaze generator: (x, y) in −1…1 for wall-clock seconds *t*."""
    if pattern == "stare":
        return 0.0, 0.0
    if pattern == "crazy":
        return math.sin(t * 6.0), math.sin(t * 4.3 + 1.0)
    if pattern == "wander":
        return math.sin(t * 0.7), math.sin(t * 0.45 + 0.3)
    raise ValueError(f"unknown pattern {pattern!r} (want wander/stare/crazy)")


def frame_state(t: float, pattern: str, lid: float) -> EyeState:
    """The tracking frame to broadcast at time *t* with lid openness *lid*."""
    x, y = gaze_at(t, pattern)
    # Slight natural asymmetry so the two eyes don't move in perfect sync.
    return EyeState(
        left_x=x,
        left_y=y * 0.9 + 0.05,
        left_lid=lid,
        right_x=x,
        right_y=y,
        right_lid=lid,
    )


class Blinker:
    """Poisson-spaced blinks; ``lid(now)`` is 1.0 except during a blink."""

    def __init__(self, per_minute: float, seed: int | None = None) -> None:
        self._rate = max(per_minute, 0.0) / 60.0  # blinks per second
        self._rng = random.Random(seed)
        self._next_blink = self._interval()
        self._start: float | None = None

    def _interval(self) -> float:
        if self._rate <= 0.0:
            return float("inf")
        # expovariate(k) has mean 1/k — exactly the Poisson inter-arrival gap.
        return self._rng.expovariate(self._rate)

    def lid(self, now: float) -> float:
        """Lid openness at wall-clock time *now* (seconds, monotonic-ish)."""
        if self._start is None and now >= self._next_blink:
            self._start = now
            self._next_blink = now + max(self._interval(), BLINK_DURATION_S * 4)
        if self._start is not None:
            dt = now - self._start
            if 0.0 <= dt < BLINK_DURATION_S:
                # 1 → 0 → 1 over the blink window (cosine hump, upside down).
                return 1.0 - math.sin(math.pi * dt / BLINK_DURATION_S)
            self._start = None
        return 1.0


@click.command(name="sim-eyes")
@click.option("--host", default="127.0.0.1", show_default=True, help="OSC destination host.")
@click.option("--port", type=int, default=9000, show_default=True, help="OSC destination port.")
@click.option(
    "--rate",
    type=float,
    default=DEFAULT_RATE_HZ,
    show_default=True,
    help="Send rate in Hz (~10 fps ceiling).",
)
@click.option(
    "--pattern",
    type=click.Choice(["wander", "stare", "crazy"]),
    default="wander",
    show_default=True,
    help="Gaze pattern.",
)
@click.option(
    "--blink-rate",
    type=float,
    default=12.0,
    show_default=True,
    help="Average blinks per minute (0 = never).",
)
@click.option(
    "--seed", type=int, default=None, help="Blink-schedule RNG seed (deterministic runs)."
)
def main(
    host: str, port: int, rate: float, pattern: str, blink_rate: float, seed: int | None
) -> None:
    """Broadcast fake EyeTrackVR eye tracking on UDP HOST:PORT."""
    client = SimpleUDPClient(host, port)
    blinker = Blinker(blink_rate, seed)
    period = 1.0 / max(rate, 0.1)
    click.echo(
        f"sim-eyes: sending to udp://{host}:{port} "
        f"(pattern={pattern}, ~{rate:g} Hz, blinks {blink_rate:g}/min)"
    )
    t0 = time.monotonic()
    try:
        while True:
            tick = time.monotonic()
            state = frame_state(tick - t0, pattern, blinker.lid(tick - t0))
            for address, value in state.as_messages():
                client.send_message(address, value)
            time.sleep(max(0.0, period - (time.monotonic() - tick)))
    except KeyboardInterrupt:
        click.echo("sim-eyes: bye")


if __name__ == "__main__":
    main()  # pragma: no cover
