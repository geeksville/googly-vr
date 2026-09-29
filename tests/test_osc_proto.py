"""osc_proto tests: value mapping + a real OSC round-trip over loopback UDP."""

from __future__ import annotations

import socket
import threading
import time

import pytest
from pythonosc import dispatcher, osc_server
from pythonosc.udp_client import SimpleUDPClient

from googly_vr.osc_proto import ALL_ADDRESSES, EyeState


def test_clamping():
    wild = EyeState(
        left_x=5.0,
        left_y=-3.0,
        left_lid=2.0,
        right_x=-0.5,
        right_y=0.5,
        right_lid=-1.0,
    )
    s = wild.clamped()
    assert s.left_x == 1.0
    assert s.left_y == -1.0
    assert s.left_lid == 1.0
    assert s.right_lid == 0.0
    assert s.right_x == -0.5  # already in range


def test_apply_known_and_unknown():
    st = EyeState()
    assert st.apply("/avatar/parameters/LeftEyeX", 0.25)
    assert st.left_x == 0.25
    assert not st.apply("/avatar/parameters/SomeFutureParam", 1.0)
    assert not st.apply("/not-even-ours", 1.0)


def test_messages_cover_every_address():
    st = EyeState(left_x=0.1, right_x=0.2)
    addresses = {a for a, _ in st.as_messages()}
    assert addresses == set(ALL_ADDRESSES)


def test_udp_roundtrip():
    """Send an EyeState via python-osc over loopback; reassemble it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    received: list[tuple[str, float]] = []
    disp = dispatcher.Dispatcher()

    def handler(address: str, *args: object) -> None:
        received.append((address, float(args[0])))

    for address in ALL_ADDRESSES:
        disp.map(address, handler)
    server = osc_server.BlockingOSCUDPServer(("127.0.0.1", port), disp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    sent = EyeState(
        left_x=-0.25,
        left_y=0.5,
        left_lid=1.0,
        right_x=0.75,
        right_y=-0.1,  # OSC carries float32 — compare with approx below
        right_lid=0.0,
    )
    client = SimpleUDPClient("127.0.0.1", port)
    for address, value in sent.as_messages():
        client.send_message(address, value)

    deadline = time.monotonic() + 2.0
    while len(received) < len(ALL_ADDRESSES) and time.monotonic() < deadline:
        time.sleep(0.01)
    server.shutdown()

    got = EyeState()
    for address, value in received:
        got.apply(address, value)
    # OSC payloads are 32-bit floats — the wire quantises small decimals.
    for field in ("left_x", "left_y", "left_lid", "right_x", "right_y", "right_lid"):
        assert getattr(got, field) == pytest.approx(getattr(sent, field)), field
