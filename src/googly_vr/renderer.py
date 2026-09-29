"""Eye rendering on a touchy-pad device.

This is the ONLY module that imports ``touchy_pad`` — the plan's
submodule-extraction rule (docs/plans/general.md) — so pulling googly-vr
out into its own repo later is a one-file diff plus the pyproject switch
to the PyPI package.

Design (per the plan):

* the eye screen is built ONCE at startup from the DSL and saved/loaded;
* afterwards only ``set_properties`` batches (stage-lb14
  ``SetPropertiesCmd``) move the pupils / squash the lids — never a screen
  re-upload;
* entries are coalesced: a pixel value that didn't change since the last
  frame is not sent at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from touchy_pad.api import build_property_override, touchy_open
from touchy_pad.api.screens import Screen, absolute, button, rect, style
from touchy_pad.paths import screen_path

from .osc_proto import RELAXED_LID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from touchy_pad import _proto
    from touchy_pad.api import Touchy

    from .osc_proto import EyeState

# Widget ids — the contract between the saved screen and the overrides.
EYE_L = "eye_l"
EYE_R = "eye_r"
PUPIL_L = "pupil_l"
PUPIL_R = "pupil_r"

SCLERA_COLOR = 0xF4F4F4
PUPIL_COLOR = 0x202020
# radius ≥ half-size ⇒ LVGL renders a circle (see screens.py's style()).
FULLY_ROUNDED = 32767

# Lid (VRCFT) ≥ RELAXED_LID (0.8, the tracker's "normal" open eye) renders the
# eye fully open; below it the eye squashes linearly towards a slit.
#
# At lid == 0 the eye becomes BLINK_SLIT_FRACTION of its full height — a
# visible slit rather than nothing, which reads as a cute cartoon blink.
BLINK_SLIT_FRACTION = 0.12


@dataclass(frozen=True)
class EyeGeometry:
    """Pixel layout of the two eyes on a display."""

    width: int
    height: int
    top_y: int
    socket_w: int
    socket_h: int
    left_x: int
    right_x: int
    pupil_w: int
    pupil_h: int

    @classmethod
    def for_display(cls, width: int, height: int) -> EyeGeometry:
        """Two big round eyes that fill ~72% of the panel height."""
        if width < 16 or height < 16:
            raise ValueError(f"display too small for googly eyes: {width}x{height}")
        socket_h = int(height * 0.72)
        socket_w = int(min(socket_h * 1.2, width * 0.44))
        pupil_w = max(6, int(socket_w * 0.45))
        pupil_h = max(6, int(socket_h * 0.45))
        gap = max(4, (width - 2 * socket_w) // 3)
        left_x = max(0, (width - (2 * socket_w + gap)) // 2)
        return cls(
            width=width,
            height=height,
            top_y=(height - socket_h) // 2,
            socket_w=socket_w,
            socket_h=socket_h,
            left_x=left_x,
            right_x=left_x + socket_w + gap,
            pupil_w=pupil_w,
            pupil_h=pupil_h,
        )

    def pupil_rect(self, left: bool, gaze_x: float, gaze_y: float) -> tuple[int, int]:
        """Pixel (x, y) of the pupil top-left for gaze clamped to −1…1²."""
        sx = self.left_x if left else self.right_x
        gx = max(-1.0, min(1.0, gaze_x))
        gy = max(-1.0, min(1.0, gaze_y))
        travel_x = (self.socket_w - self.pupil_w) / 2
        travel_y = (self.socket_h - self.pupil_h) / 2
        cx = sx + travel_x + gx * travel_x
        cy = self.top_y + travel_y + gy * travel_y
        return round(cx), round(cy)


def compute_pixels(geom: EyeGeometry, state: EyeState) -> dict[tuple[str, str], int]:
    """Map one tracking frame to the (widget_id, property) → pixel batch.

    Pure function — the unit tests cover it without any device. Blink:
    the socket squashes towards its vertical centre (and the pupil with
    it, pinned inside the visible slit); gaze moves the pupil top-left
    within the socket's travel range.
    """
    s = state.clamped()
    out: dict[tuple[str, str], int] = {}
    for left, eye_id, pupil_id, gx, gy, lid in (
        (True, EYE_L, PUPIL_L, s.left_x, s.left_y, s.left_lid),
        (False, EYE_R, PUPIL_R, s.right_x, s.right_y, s.right_lid),
    ):
        openness = 1.0 if lid >= RELAXED_LID else max(0.0, lid) / RELAXED_LID
        frac = max(BLINK_SLIT_FRACTION, openness)
        socket_h = max(2, round(geom.socket_h * frac))
        socket_y = geom.top_y + (geom.socket_h - socket_h) // 2
        pupil_h = max(2, round(geom.pupil_h * frac))
        px, py = geom.pupil_rect(left, gx, gy)
        # Keep the pupil inside the (possibly squashed) visible eye.
        py = max(socket_y + 1, min(py, socket_y + socket_h - pupil_h - 1))
        out[(eye_id, "h")] = socket_h
        out[(eye_id, "y")] = socket_y
        out[(pupil_id, "x")] = px
        out[(pupil_id, "y")] = py
        out[(pupil_id, "h")] = pupil_h
    return out


def build_eye_screen(geom: EyeGeometry, name: str = "eyes") -> Screen:
    """The one-time eye screen: two circular sclera + two circular pupils."""
    s = Screen(name, layout=absolute())
    for eye_id, pupil_id, sx in (
        (EYE_L, PUPIL_L, geom.left_x),
        (EYE_R, PUPIL_R, geom.right_x),
    ):
        s += button(
            eye_id,
            rect=rect(sx, geom.top_y, geom.socket_w, geom.socket_h),
            style=[style(bg_color=SCLERA_COLOR, radius=FULLY_ROUNDED)],
        )
        px, py = geom.pupil_rect(eye_id == EYE_L, 0.0, 0.0)
        s += button(
            pupil_id,
            rect=rect(px, py, geom.pupil_w, geom.pupil_h),
            style=[style(bg_color=PUPIL_COLOR, radius=FULLY_ROUNDED)],
        )
    return s


def connect() -> Touchy:
    """Open a touchy-pad connection (USB, or the simulator via TOUCHY_SIM_URL)."""
    return touchy_open()


class EyeRenderer:
    """Owns the on-device eye screen + the state → override-batch mapping."""

    def __init__(self, pad: Any, width: int, height: int, name: str = "eyes") -> None:
        self._pad = pad
        self._geom = EyeGeometry.for_display(width, height)
        self._name = name
        self._sent: dict[tuple[str, str], int] = {}
        pad.screen_save(build_eye_screen(self._geom, name))
        pad.screen_load(screen_path(name))

    @property
    def geometry(self) -> EyeGeometry:
        return self._geom

    def reset(self) -> None:
        """Forget what was already sent (e.g. after a device reconnect)."""
        self._sent.clear()

    def entries_for(self, state: EyeState) -> list[_proto.SetPropertyCmd]:
        """The coalesced ``SetPropertiesCmd`` batch for this frame."""
        pixels = compute_pixels(self._geom, state)
        entries = [
            build_property_override(widget_id, prop, value)
            for (widget_id, prop), value in pixels.items()
            if self._sent.get((widget_id, prop)) != value
        ]
        self._sent.update(pixels)
        return entries

    def apply(self, state: EyeState) -> int:
        """Push one tracking frame; returns the number of overrides sent.

        An unchanged frame sends nothing (the ~10 fps budget goes further).
        """
        entries = self.entries_for(state)
        if entries:
            self._pad.set_properties(entries)
        return len(entries)
