"""renderer tests: geometry math, blink mapping, screen build, coalescing."""

from __future__ import annotations

from googly_vr.osc_proto import EyeState
from googly_vr.renderer import (
    BLINK_SLIT_FRACTION,
    EYE_L,
    EYE_R,
    PUPIL_L,
    PUPIL_R,
    EyeGeometry,
    EyeRenderer,
    build_eye_screen,
    compute_pixels,
)


def _iter_ids(widget):
    yield widget.id
    kind = widget.WhichOneof("kind")
    if kind in ("layout_absolute", "layout_flex", "layout_grid"):
        for child in getattr(widget, kind).layout.children:
            yield from _iter_ids(child)


def test_geometry_fits_display():
    g = EyeGeometry.for_display(480, 320)
    assert 0 <= g.left_x
    assert g.right_x + g.socket_w <= 480
    assert 0 <= g.top_y
    assert g.top_y + g.socket_h <= 320
    assert g.pupil_w <= g.socket_w
    assert g.pupil_h <= g.socket_h


def test_pupil_extremes_stay_inside_socket():
    g = EyeGeometry.for_display(480, 320)
    for left in (True, False):
        sx = g.left_x if left else g.right_x
        for gx, gy in ((-1.0, -1.0), (0.0, 0.0), (1.0, 1.0), (5.0, -5.0)):
            px, py = g.pupil_rect(left, gx, gy)
            assert sx <= px <= sx + g.socket_w - g.pupil_w
            assert g.top_y <= py <= g.top_y + g.socket_h - g.pupil_h


def test_open_eyes_use_full_height():
    g = EyeGeometry.for_display(480, 320)
    pixels = compute_pixels(g, EyeState())  # default = relaxed open
    assert pixels[(EYE_L, "h")] == g.socket_h
    assert pixels[(EYE_R, "h")] == g.socket_h


def test_blink_squashes_to_a_slit():
    g = EyeGeometry.for_display(480, 320)
    pixels = compute_pixels(g, EyeState(left_lid=0.0, right_lid=0.0))
    slit = round(g.socket_h * BLINK_SLIT_FRACTION)
    assert pixels[(EYE_L, "h")] == slit
    # Socket squashes towards its centre.
    assert pixels[(EYE_L, "y")] > g.top_y
    # Pupil stays inside the visible slit.
    assert pixels[(PUPIL_L, "y")] >= pixels[(EYE_L, "y")]
    assert pixels[(PUPIL_L, "h")] <= pixels[(EYE_L, "h")]


def test_gaze_moves_pupil():
    g = EyeGeometry.for_display(480, 320)
    centre = compute_pixels(g, EyeState())[(PUPIL_L, "x")]
    right = compute_pixels(g, EyeState(left_x=1.0))[(PUPIL_L, "x")]
    left = compute_pixels(g, EyeState(left_x=-1.0))[(PUPIL_L, "x")]
    assert left < centre < right


def test_screen_has_the_four_widget_ids():
    g = EyeGeometry.for_display(480, 320)
    screen = build_eye_screen(g)
    proto = screen.to_proto()
    ids = set()
    for layer in ("active", "top", "sys", "bottom"):
        if proto.HasField(layer):
            ids.update(_iter_ids(getattr(proto, layer)))
    assert {EYE_L, EYE_R, PUPIL_L, PUPIL_R} <= ids


class _FakePad:
    """Records what the renderer pushes; no device needed."""

    def __init__(self) -> None:
        self.batches: list[list] = []
        self.loaded: str | None = None

    def screen_save(self, screen, *, name=None) -> str:
        return screen.name

    def screen_load(self, path: str) -> None:
        self.loaded = path

    def set_properties(self, entries) -> None:
        self.batches.append(list(entries))


def test_renderer_coalesces_unchanged_frames():
    pad = _FakePad()
    r = EyeRenderer(pad, 480, 320)
    assert pad.loaded is not None and pad.loaded.endswith("eyes.pb")

    n1 = r.apply(EyeState(left_x=0.5))
    assert n1 > 0 and len(pad.batches) == 1

    # Identical frame → nothing sent.
    assert r.apply(EyeState(left_x=0.5)) == 0
    assert len(pad.batches) == 1

    # Changed frame → only the changed pixels go out.
    n3 = r.apply(EyeState(left_x=-0.5, right_x=-0.5))
    assert n3 > 0 and len(pad.batches) == 2
    sent_ids = {e.widget_id for e in pad.batches[-1]}
    assert sent_ids == {PUPIL_L, PUPIL_R}  # only the pupils moved


def test_renderer_reset_resends_everything():
    pad = _FakePad()
    r = EyeRenderer(pad, 480, 320)
    r.apply(EyeState(left_x=0.5))
    r.reset()
    assert r.apply(EyeState(left_x=0.5)) > 0
