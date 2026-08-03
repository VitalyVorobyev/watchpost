"""Motion detection.

The recorder consumes only ``Detection``; it has no knowledge of how ``active`` was
computed. That is what makes a Phase 3 person detector a drop-in replacement. See ADR-0007.

This module performs no I/O, reads no clock, and holds no global state, so it can be tested
against synthetic frame sequences with no camera present.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol

import numpy as np


class Detection(NamedTuple):
    active: bool
    """Is something happening in this frame."""

    score: float
    """Fraction of the frame currently changing. Comparable only within one detector
    implementation — always display it relative to ``threshold``, never as an absolute."""

    label: str
    """What was detected. ``"motion"`` today; ``"person"`` and friends later."""

    threshold: float
    """The value ``score`` had to exceed. Carried so the UI can render a meter."""


class Detector(Protocol):
    def update(self, frame_rgb: np.ndarray, t: float) -> Detection: ...
    def reset(self) -> None: ...


def _to_gray(frame_rgb: np.ndarray) -> np.ndarray:
    """ITU-R BT.601 luma. Cheaper and closer to perceived brightness than a plain mean."""
    return (
        frame_rgb[:, :, 0] * 0.299 + frame_rgb[:, :, 1] * 0.587 + frame_rgb[:, :, 2] * 0.114
    ).astype(np.float32)


def _box_downsample(gray: np.ndarray, factor: int) -> np.ndarray:
    """Average over factor x factor blocks.

    This is the noise filter: sensor grain is uncorrelated between neighbouring pixels and
    averages away, while a real moving object survives. Doing it by reshape keeps the whole
    detector dependency-free.
    """
    h, w = gray.shape
    h_trim, w_trim = h - h % factor, w - w % factor
    trimmed = gray[:h_trim, :w_trim]
    return trimmed.reshape(h_trim // factor, factor, w_trim // factor, factor).mean(axis=(1, 3))


class MotionDetector:
    """Exponential-moving-average background subtraction.

    Three mechanisms keep the false-positive rate tolerable:

    1. **Box downsampling** removes sensor noise before thresholding.
    2. **Asymmetric background update** — pixels currently flagged as motion are absorbed
       into the background far more slowly than quiet pixels. Without this, someone who
       enters the frame and stands still fades into the background within seconds and the
       recording stops while they are still there.
    3. **Consecutive-frame confirmation** rejects single-frame flashes such as autofocus
       hunting or a passing headlight.
    """

    def __init__(
        self,
        *,
        diff_threshold: float = 22.0,
        min_area: float = 0.004,
        downsample: int = 4,
        alpha_background: float = 0.05,
        alpha_foreground: float = 0.001,
        confirm_frames: int = 2,
        warmup_frames: int = 20,
    ) -> None:
        self.diff_threshold = diff_threshold
        self.min_area = min_area
        self.downsample = downsample
        self.alpha_background = alpha_background
        self.alpha_foreground = alpha_foreground
        self.confirm_frames = confirm_frames
        self.warmup_frames = warmup_frames
        self.reset()

    def reset(self) -> None:
        self._background: np.ndarray | None = None
        self._frames_seen = 0
        self._consecutive = 0

    def configure(self, *, diff_threshold: float, min_area: float) -> None:
        """Apply new settings without discarding the learned background.

        Rebuilding the background on every settings change would blind the detector for the
        whole warm-up period each time the user nudges a slider.
        """
        self.diff_threshold = diff_threshold
        self.min_area = min_area

    def update(self, frame_rgb: np.ndarray, t: float) -> Detection:
        small = _box_downsample(_to_gray(frame_rgb), self.downsample)
        self._frames_seen += 1

        if self._background is None:
            self._background = small.copy()
            return Detection(False, 0.0, "motion", self.min_area)

        diff = np.abs(small - self._background)
        mask = diff > self.diff_threshold
        score = float(mask.mean())

        # Asymmetric update: quiet pixels track the scene quickly, changing pixels barely
        # at all. See mechanism 2 in the class docstring.
        alpha = np.where(mask, self.alpha_foreground, self.alpha_background).astype(np.float32)
        self._background = (1.0 - alpha) * self._background + alpha * small

        if self._frames_seen <= self.warmup_frames:
            # The background is still converging; anything it reports now is startup
            # transient, not motion.
            self._consecutive = 0
            return Detection(False, score, "motion", self.min_area)

        if score > self.min_area:
            self._consecutive += 1
        else:
            self._consecutive = 0

        active = self._consecutive >= self.confirm_frames
        return Detection(active, score, "motion", self.min_area)
