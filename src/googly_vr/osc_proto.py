"""Shared OSC vocabulary for googly-vr — EyeTrackVR / VRCFT parameter routing.

Both commands speak this dialect:

* ``sim-eyes`` *sends* it, pretending to be EyeTrackVR, on UDP 127.0.0.1:9000;
* ``googly-vr`` *listens* to it and renders the eyes.

When a real Steam Frame + EyeTrackVR rig eventually replaces ``sim-eyes``,
``googly-vr`` keeps working untouched — it only ever consumes this dialect.
See ``docs/kh-notes.md`` for the research that pinned these addresses.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# OSC addresses (VRCFaceTracking unified-expressions parameter routing).
#   X:  -1.0 looking left … +1.0 looking right
#   Y:  -1.0 looking down … +1.0 looking up
#   Lid: 0.0 shut … 0.8 relaxed open … 1.0 wide-eyed surprise
LEFT_EYE_X = "/avatar/parameters/LeftEyeX"
LEFT_EYE_Y = "/avatar/parameters/LeftEyeY"
LEFT_EYE_LID = "/avatar/parameters/LeftEyeLidExpanded"
RIGHT_EYE_X = "/avatar/parameters/RightEyeX"
RIGHT_EYE_Y = "/avatar/parameters/RightEyeY"
RIGHT_EYE_LID = "/avatar/parameters/RightEyeLidExpanded"
# Reserved for later (pupil size); sim-eyes does not send it yet.
EYES_PUPIL_DIAMETER = "/avatar/parameters/EyesPupilDiameter"

#: Every address a consumer needs to subscribe to.
ALL_ADDRESSES = (
    LEFT_EYE_X,
    LEFT_EYE_Y,
    LEFT_EYE_LID,
    RIGHT_EYE_X,
    RIGHT_EYE_Y,
    RIGHT_EYE_LID,
)

# The lid value VRCFT uses for a relaxed, fully-open eye.
RELAXED_LID = 0.8


@dataclass
class EyeState:
    """One tracking frame: per-eye gaze (−1…1) and lid openness (0…1)."""

    left_x: float = 0.0
    left_y: float = 0.0
    left_lid: float = RELAXED_LID
    right_x: float = 0.0
    right_y: float = 0.0
    right_lid: float = RELAXED_LID

    def clamped(self) -> EyeState:
        """A copy with every value pulled into its valid range."""

        def pm1(v: float) -> float:
            return max(-1.0, min(1.0, v))

        def z1(v: float) -> float:
            return max(0.0, min(1.0, v))

        return EyeState(
            left_x=pm1(self.left_x),
            left_y=pm1(self.left_y),
            left_lid=z1(self.left_lid),
            right_x=pm1(self.right_x),
            right_y=pm1(self.right_y),
            right_lid=z1(self.right_lid),
        )

    def as_messages(self) -> list[tuple[str, float]]:
        """The OSC (address, float) pairs that carry this state."""
        s = self.clamped()
        return [
            (LEFT_EYE_X, s.left_x),
            (LEFT_EYE_Y, s.left_y),
            (LEFT_EYE_LID, s.left_lid),
            (RIGHT_EYE_X, s.right_x),
            (RIGHT_EYE_Y, s.right_y),
            (RIGHT_EYE_LID, s.right_lid),
        ]

    def apply(self, address: str, value: float) -> bool:
        """Fold one received OSC float into this state.

        Returns ``False`` when *address* is not part of the dialect (the
        sender may multiplex other parameters we don't care about).
        """
        fields = {
            LEFT_EYE_X: "left_x",
            LEFT_EYE_Y: "left_y",
            LEFT_EYE_LID: "left_lid",
            RIGHT_EYE_X: "right_x",
            RIGHT_EYE_Y: "right_y",
            RIGHT_EYE_LID: "right_lid",
        }
        field = fields.get(address)
        if field is None:
            return False
        setattr(self, field, float(value))
        return True

    def snapshot(self) -> EyeState:
        """A thread-safe-to-share copy."""
        return replace(self)
