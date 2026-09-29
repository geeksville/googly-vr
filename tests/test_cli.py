"""cli tests: loopback-only OSC, lazy OSC-driven connect, never-fatal retries.

Pure host-side: no hardware, no real sockets, no real sleeps. ``main()`` builds
its hub from ``cli._Hub``, reaches the pad only through ``cli.connect`` /
``cli.EyeRenderer``, reads time only through ``cli._now``, and binds through
``cli.osc_server.BlockingOSCUDPServer`` — so every one of those is faked here and
the whole loop is driven by a scripted "an update arrived" hub.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from click.testing import CliRunner
from touchy_pad.api import IncompatibleFirmwareError

# The exception touchy_open() raises when nothing is attached.
from touchy_pad.api._transport import DeviceNotFoundError

from googly_vr import cli
from googly_vr.osc_proto import LEFT_EYE_X, EyeState


def _all_output(result: Any) -> str:
    """Everything the command printed.

    click's CliRunner mixes stderr into ``output`` (and 8.2+ *also* exposes it
    separately), so only append ``stderr`` when it isn't already in there —
    that keeps this helper honest on either side of the click change.
    """
    out = result.output or ""
    err = getattr(result, "stderr", None) or ""
    return out if err in out else out + err


class FakeClock:
    """A monotonic clock the tests step by hand."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class FakeHub:
    """Scripted stand-in for ``cli._Hub``: one ``wait()`` per script step.

    Each step is how many seconds to advance the fake clock before "an update
    arrives"; when the script runs out, ``wait()`` raises ``KeyboardInterrupt``,
    which is exactly how ``main()`` ends in production.
    """

    def __init__(
        self, script: list[float] | tuple[float, ...] = (), clock: FakeClock | None = None
    ) -> None:
        self._script = list(script)
        self._clock = clock
        self.state = EyeState()
        self.waits = 0
        self.snapshots = 0
        self.osc_calls = 0

    def on_osc(self, address: str, *args: object) -> None:
        """Mapped by the dispatcher; the scripted loop doesn't need the values."""
        self.osc_calls += 1

    def wait(self) -> None:
        self.waits += 1
        if not self._script:
            raise KeyboardInterrupt
        if self._clock is not None:
            self._clock.advance(self._script.pop(0))

    def reset_update(self) -> None:
        return None

    def snapshot(self) -> EyeState:
        self.snapshots += 1
        return self.state


class FakePad:
    def __init__(self, width: int = 480, height: int = 320) -> None:
        self.board_info = SimpleNamespace(display_width=width, display_height=height)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeRenderer:
    """Records applied frames; can be told to fail one instance's first apply."""

    instances: ClassVar[list[FakeRenderer]] = []
    #: 1-based instance number whose first apply() raises (None = never).
    fail_apply_for: ClassVar[int | None] = None

    def __init__(self, pad: FakePad, width: int, height: int, name: str = "eyes") -> None:
        self.pad, self.width, self.height, self.name = pad, width, height, name
        self.applied: list[EyeState] = []
        FakeRenderer.instances.append(self)

    def apply(self, state: EyeState) -> int:
        if FakeRenderer.fail_apply_for == len(FakeRenderer.instances) and not self.applied:
            raise RuntimeError("pad went away")
        self.applied.append(state)
        return 1


class FakeServer:
    """Captures the bind address; ``serve_forever`` returns so the thread ends."""

    bound: ClassVar[list[tuple[str, int]]] = []

    def __init__(self, address: tuple[str, int], dispatch: Any) -> None:
        FakeServer.bound.append(address)

    def serve_forever(self) -> None:
        return None


def _run(
    monkeypatch: pytest.MonkeyPatch,
    *,
    script: list[float] | tuple[float, ...] = (),
    outcomes: list[Any] | None = None,
    args: list[str] | None = None,
    period: float = 0.1,
    fail_apply_for: int | None = None,
) -> tuple[Any, FakeHub, dict[str, int], list[FakePad]]:
    """Invoke ``cli.main`` with everything faked.

    ``outcomes`` is the per-attempt result of ``connect()``: a ``FakePad`` to
    succeed with, or an exception instance to raise. The last entry repeats, so
    ``[DeviceNotFoundError("x")]`` means "never connects"; ``None`` means "a
    healthy pad every time". ``fail_apply_for`` makes that 1-based renderer
    instance's first ``apply()`` raise (a pad that goes away mid-run).
    """
    clock = FakeClock()
    hub = FakeHub(script, clock)
    calls = {"attempts": 0}
    pads: list[FakePad] = []
    outcomes = [FakePad()] if outcomes is None else list(outcomes)

    def fake_connect() -> FakePad:
        calls["attempts"] += 1
        outcome = outcomes[min(calls["attempts"] - 1, len(outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        pads.append(outcome)
        return outcome

    monkeypatch.setattr(cli, "_now", clock)
    monkeypatch.setattr(cli, "_Hub", lambda: hub)
    monkeypatch.setattr(cli, "connect", fake_connect)
    monkeypatch.setattr(cli, "EyeRenderer", FakeRenderer)
    monkeypatch.setattr(cli.osc_server, "BlockingOSCUDPServer", FakeServer)
    FakeRenderer.instances.clear()
    FakeRenderer.fail_apply_for = fail_apply_for
    FakeServer.bound.clear()

    result = CliRunner().invoke(cli.main, [*(args or []), "--period", str(period)])
    return result, hub, calls, pads


# -- item 1: loopback by default --------------------------------------------


def test_default_host_is_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    result, *_ = _run(monkeypatch)
    assert result.exit_code == 0
    assert FakeServer.bound == [("127.0.0.1", 9000)]


def test_host_flag_still_allows_all_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    result, *_ = _run(monkeypatch, args=["--host", "0.0.0.0"])
    assert result.exit_code == 0
    assert FakeServer.bound == [("0.0.0.0", 9000)]


# -- item 2: lazy, OSC-driven, never fatal ----------------------------------


def test_no_connect_attempt_while_osc_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the lazy search: no tracker → no device I/O at all."""
    result, hub, calls, _ = _run(monkeypatch)
    assert result.exit_code == 0
    assert calls["attempts"] == 0
    assert hub.snapshots == 0
    assert FakeRenderer.instances == []
    assert "googly-vr: bye" in _all_output(result)


def test_connect_only_on_updates_and_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    # Updates land at t=0, t=1 and t=6 s → attempts only at t=0 and t=6.
    result, _hub, calls, _ = _run(
        monkeypatch,
        script=[0.0, 1.0, 5.0],
        outcomes=[DeviceNotFoundError("no Touchy-Pad device found")],
    )
    assert calls["attempts"] == 2
    out = _all_output(result)
    assert out.count("looking for touchy-pad") == 1  # once per search episode
    assert "DeviceNotFoundError" in out  # … but the reason is always shown
    assert result.exit_code == 0


def test_pad_appearing_later_is_picked_up(monkeypatch: pytest.MonkeyPatch) -> None:
    pad = FakePad()
    result, _hub, calls, _ = _run(
        monkeypatch,
        script=[0.0, 5.0],
        outcomes=[DeviceNotFoundError("not yet"), pad],
    )
    assert calls["attempts"] == 2
    assert len(FakeRenderer.instances) == 1
    renderer = FakeRenderer.instances[0]
    assert (renderer.width, renderer.height, renderer.name) == (480, 320, "eyes")
    # The update that found the pad already painted a frame.
    assert len(renderer.applied) == 1
    assert "eyes on 480x320" in _all_output(result)


def test_headless_pad_keeps_searching_instead_of_exiting(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _hub, calls, pads = _run(
        monkeypatch,
        script=[0.0, 5.0],
        outcomes=[FakePad(width=0, height=0)],
    )
    assert calls["attempts"] == 2  # kept trying …
    assert pads[0].closed  # … and released the handle
    assert "touchy-pad reports no display (0x0)" in _all_output(result)
    assert result.exit_code == 0
    assert FakeRenderer.instances == []  # nothing was drawn


def test_incompatible_firmware_keeps_searching(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _hub, calls, _ = _run(
        monkeypatch,
        script=[0.0, 5.0],
        outcomes=[IncompatibleFirmwareError(5, 14)],
    )
    assert calls["attempts"] == 2
    assert "IncompatibleFirmwareError" in _all_output(result)
    assert result.exit_code == 0


def test_frame_failure_closes_the_pad_and_restarts_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _hub, calls, pads = _run(monkeypatch, script=[0.0, 0.0, 5.0], fail_apply_for=1)
    assert pads[0].closed
    assert "googly-vr: lost the touchy-pad (RuntimeError: pad went away)" in _all_output(result)
    assert calls["attempts"] == 2  # re-attempted after the rate limit
    assert len(FakeRenderer.instances) == 2
    assert len(FakeRenderer.instances[1].applied) == 1  # the new pad painted


def test_period_caps_the_frame_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    # 100 updates inside one 100 ms period → a single frame; then one more
    # period later → exactly one more.
    script = [0.0] * 100 + [0.2] + [0.0] * 3
    result, _hub, _calls, _ = _run(monkeypatch, script=script, period=0.1)
    assert result.exit_code == 0
    assert len(FakeRenderer.instances[0].applied) == 2


def test_ctrl_c_says_bye(monkeypatch: pytest.MonkeyPatch) -> None:
    result, *_ = _run(monkeypatch, script=[0.0])
    assert result.exit_code == 0
    assert "googly-vr: bye" in _all_output(result)


# -- the real hub (not faked) ------------------------------------------------


def test_hub_wakes_the_render_thread_on_update() -> None:
    hub = cli._Hub()
    hub.on_osc("/avatar/parameters/Bogus", 1.0)  # unknown address: ignored
    hub.on_osc(LEFT_EYE_X, 0.25)
    assert hub.snapshot().left_x == pytest.approx(0.25)

    hub.wait()  # returns immediately — an update is already pending
    hub.reset_update()

    woken = threading.Event()
    threading.Thread(target=lambda: (hub.wait(), woken.set()), daemon=True).start()
    time.sleep(0.01)  # let that thread park in Event.wait()
    assert not woken.is_set()

    hub.on_osc(LEFT_EYE_X, -0.5)  # a new value wakes it
    assert woken.wait(1.0)
    assert hub.snapshot().left_x == pytest.approx(-0.5)
