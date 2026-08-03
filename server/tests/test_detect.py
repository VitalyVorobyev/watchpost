"""Motion detector behaviour, driven by synthetic frames — no camera involved."""

from __future__ import annotations

import numpy as np
import pytest

from watchpost.capture import DETECT_HEIGHT, DETECT_WIDTH
from watchpost.detect import MotionDetector, _box_downsample, _to_gray


def frame(value: int = 40) -> np.ndarray:
    return np.full((DETECT_HEIGHT, DETECT_WIDTH, 3), value, dtype=np.uint8)


def feed(detector: MotionDetector, image: np.ndarray, count: int, start: float = 0.0):
    result = None
    for index in range(count):
        result = detector.update(image, start + index * 0.1)
    return result


def test_static_scene_never_triggers():
    detector = MotionDetector(warmup_frames=5)
    result = feed(detector, frame(), 60)
    assert result is not None
    assert not result.active
    assert result.score == pytest.approx(0.0, abs=1e-6)


def test_warmup_suppresses_the_startup_transient():
    """The first frames establish the background; whatever they show is not motion."""
    detector = MotionDetector(warmup_frames=20)
    detector.update(frame(10), 0.0)
    # A hard cut on frame two would look like enormous motion without the warm-up guard.
    for index in range(1, 15):
        result = detector.update(frame(200), index * 0.1)
        assert not result.active


def test_moving_block_triggers():
    detector = MotionDetector(warmup_frames=5, min_area=0.01, confirm_frames=2)
    feed(detector, frame(40), 30)

    moving = frame(40)
    moving[60:200, 100:300] = 220  # ~21% of the frame
    result = feed(detector, moving, 5, start=10.0)

    assert result is not None
    assert result.active
    assert result.score > 0.01
    assert result.label == "motion"


def test_small_change_stays_below_the_area_threshold():
    detector = MotionDetector(warmup_frames=5, min_area=0.05)
    feed(detector, frame(40), 30)

    speck = frame(40)
    speck[0:8, 0:8] = 255  # far below 5% of the frame
    result = feed(detector, speck, 5, start=10.0)

    assert result is not None
    assert not result.active


def test_single_frame_flash_is_rejected():
    """Autofocus hunting and passing headlights produce one-frame spikes."""
    detector = MotionDetector(warmup_frames=5, min_area=0.01, confirm_frames=3)
    feed(detector, frame(40), 30)

    flash = frame(40)
    flash[:, :] = 200
    assert not detector.update(flash, 10.0).active
    assert not detector.update(frame(40), 10.1).active


def test_stationary_subject_is_not_absorbed_into_the_background():
    """Someone who enters and stops moving must keep the event open.

    A symmetric background update would fade them out within seconds and end the
    recording while they are still in frame.
    """
    detector = MotionDetector(
        warmup_frames=5, min_area=0.01, confirm_frames=2, alpha_foreground=0.0005
    )
    feed(detector, frame(40), 30)

    intruder = frame(40)
    intruder[50:220, 80:400] = 210
    assert feed(detector, intruder, 5, start=10.0).active

    # Hold perfectly still for 20 seconds of frames.
    result = feed(detector, intruder, 200, start=11.0)
    assert result.active, "stationary subject was absorbed into the background"


def test_reset_clears_the_background():
    detector = MotionDetector(warmup_frames=5)
    feed(detector, frame(40), 30)
    detector.reset()
    # After reset the next frame re-seeds the background and cannot report motion.
    assert not detector.update(frame(200), 20.0).active


def test_configure_preserves_the_learned_background():
    """Changing a slider must not blind the detector for a whole warm-up period."""
    detector = MotionDetector(warmup_frames=5, min_area=0.01)
    feed(detector, frame(40), 30)
    detector.configure(diff_threshold=15.0, min_area=0.02)

    moving = frame(40)
    moving[60:200, 100:300] = 220
    assert feed(detector, moving, 3, start=10.0).active


def test_grayscale_and_downsample_shapes():
    gray = _to_gray(frame(100))
    assert gray.shape == (DETECT_HEIGHT, DETECT_WIDTH)
    assert gray.dtype == np.float32

    small = _box_downsample(gray, 4)
    assert small.shape == (DETECT_HEIGHT // 4, DETECT_WIDTH // 4)
    assert small.mean() == pytest.approx(100.0, abs=0.5)


def test_downsample_handles_indivisible_dimensions():
    gray = np.ones((11, 13), dtype=np.float32)
    assert _box_downsample(gray, 4).shape == (2, 3)
