"""googly-vr — cute animated googly eyes on a touchy-pad display.

Two console commands share this src tree:

* ``sim-eyes`` — broadcasts fake EyeTrackVR tracking over OSC (UDP :9000);
* ``googly-vr`` — listens to that OSC stream and draws the eyes on a
  touchy-pad device (or its simulator).

See ``docs/plans/general.md`` for the design and stage plan.
"""

__version__ = "0.1.0"
