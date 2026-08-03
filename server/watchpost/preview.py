"""Live preview: the most recent frame, as JPEG.

Frames arrive on the capture thread; HTTP handlers read them from the event loop. The
latest frame is simply overwritten — preview has no queue and no history, because a viewer
always wants *now*, never a backlog.
"""

from __future__ import annotations

import io
import threading

import numpy as np
from PIL import Image


class PreviewService:
    """Holds the latest frame and encodes JPEGs on demand."""

    def __init__(self, quality: int = 70) -> None:
        self.quality = quality
        self._frame: np.ndarray | None = None
        self._captured_at: float = 0.0
        self._lock = threading.Lock()
        self._generation = 0
        self._new_frame = threading.Condition(self._lock)

    def offer(self, frame: np.ndarray, t: float) -> None:
        """Called from the capture thread for every frame."""
        with self._new_frame:
            # Copy: the caller's array is a view over a reused pipe buffer.
            self._frame = frame.copy()
            self._captured_at = t
            self._generation += 1
            self._new_frame.notify_all()

    @property
    def captured_at(self) -> float:
        with self._lock:
            return self._captured_at

    def latest_array(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def encode_jpeg(self, frame: np.ndarray | None = None) -> bytes | None:
        if frame is None:
            frame = self.latest_array()
        if frame is None:
            return None
        buffer = io.BytesIO()
        Image.fromarray(frame, mode="RGB").save(buffer, format="JPEG", quality=self.quality)
        return buffer.getvalue()

    def latest_jpeg(self) -> bytes | None:
        return self.encode_jpeg()

    def wait_for_frame(
        self, after_generation: int, timeout: float = 5.0
    ) -> tuple[int, bytes] | None:
        """Block until a frame newer than ``after_generation`` arrives, then encode it.

        Returns ``(generation, jpeg)``, or None on timeout. Waiting rather than polling is
        what keeps the MJPEG stream at the capture frame rate without spinning.
        """
        with self._new_frame:
            if self._generation <= after_generation:
                self._new_frame.wait(timeout)
            if self._generation <= after_generation or self._frame is None:
                return None
            generation = self._generation
            frame = self._frame.copy()
        jpeg = self.encode_jpeg(frame)
        return None if jpeg is None else (generation, jpeg)

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def clear(self) -> None:
        with self._lock:
            self._frame = None
            self._captured_at = 0.0
