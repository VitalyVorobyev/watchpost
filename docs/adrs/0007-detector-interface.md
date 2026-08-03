# ADR-0007: A replaceable `Detector` interface, with NumPy motion detection as the first implementation

**Status:** Accepted
**Date:** 2026-08-03

## Context

The product roadmap puts person detection in Phase 3, but the MVP needs motion detection now.
If the recorder is written against motion-specific concepts — pixel deltas, background models,
sensitivity — swapping in a neural detector later means rewriting the recorder, which is the one
component that must stay stable because it owns clip integrity.

The MVP also has a dependency-weight constraint: OpenCV is roughly 100 MB for what amounts to a
frame difference and a threshold.

## Decision

Define a narrow protocol and write everything downstream against it:

```python
class Detection(NamedTuple):
    active: bool      # is something happening right now
    score: float      # comparable magnitude, higher means more
    label: str        # "motion" today; "person", "vehicle", ... later

class Detector(Protocol):
    def update(self, frame_rgb: np.ndarray, t: float) -> Detection: ...
    def reset(self) -> None: ...
```

The recorder consumes only `Detection`. It has no knowledge of how `active` was computed.

The first implementation, `MotionDetector`, is pure NumPy:

- RGB → grayscale → 4×4 box downsample (a cheap blur that removes sensor noise);
- an exponential moving average background, updated **more slowly on pixels currently flagged as
  motion** so that a subject who stops moving is not absorbed into the background;
- absolute difference thresholded by `sensitivity`;
- the active-pixel ratio compared against `min_area`;
- `active` requires N consecutive frames above threshold, which rejects single-frame noise;
- a warm-up period suppresses the transient while the background converges.

## Consequences

- Dependencies stay at NumPy and Pillow. No OpenCV, no model weights, no accelerator setup.
- The detector is pure: no I/O, no clock, no global state. Tests drive synthetic frame sequences
  and assert on triggers — static scene, moving block, slow illumination ramp — with no camera.
- A Phase 3 detector implements the same protocol and needs no recorder changes. `label` is
  already carried into the `trigger` column of the events table.
- The trade-off is accuracy: this detector will fire on light changes, shadows, and pets. That is
  what `min_area`, the consecutive-frame requirement, and the selective background update are
  tuned to reduce, and what detection zones and person detection will fix properly later.
- `score` is not calibrated across implementations, so any UI displaying it must show it relative
  to the current threshold rather than as an absolute number.
