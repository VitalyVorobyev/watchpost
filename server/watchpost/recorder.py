"""The event state machine and clip assembly.

    IDLE --trigger--> RECORDING --no motion for post_roll--> FINALIZING --> COOLDOWN --> IDLE
                        |  ^
                        |  +-- continued motion extends the window
                        +----- hard cap at max_clip_s, then finalize

COOLDOWN exists so that one continuous disturbance produces one event rather than a flood.

The state machine is deliberately separated from clip production: ``EventRecorder`` decides
*when*, ``build_clip`` decides *how*. The former is pure and unit-testable without a camera,
a disk, or ffmpeg.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .camera import FFMPEG
from .capture import SEGMENT_SECONDS, coverage, list_segments, select_segments

log = logging.getLogger(__name__)


class Phase(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    COOLDOWN = "cooldown"


@dataclass
class ActiveEvent:
    started_at: float
    last_motion_at: float
    peak_score: float
    label: str


@dataclass
class Transition:
    """What the caller must do as a result of the last ``update`` call."""

    phase: Phase
    started: ActiveEvent | None = None
    """Set on the frame an event begins, so the caller can capture a thumbnail."""

    finished: ActiveEvent | None = None
    """Set on the frame an event ends, so the caller can build the clip."""


class EventRecorder:
    """Pure event-window logic. No I/O, no threads, no clock of its own."""

    def __init__(
        self,
        *,
        post_roll_s: float,
        cooldown_s: float,
        max_clip_s: float,
    ) -> None:
        self.post_roll_s = post_roll_s
        self.cooldown_s = cooldown_s
        self.max_clip_s = max_clip_s
        self._phase = Phase.IDLE
        self._active: ActiveEvent | None = None
        self._cooldown_until = 0.0

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def active(self) -> ActiveEvent | None:
        return self._active

    def configure(self, *, post_roll_s: float, cooldown_s: float, max_clip_s: float) -> None:
        self.post_roll_s = post_roll_s
        self.cooldown_s = cooldown_s
        self.max_clip_s = max_clip_s

    def reset(self) -> None:
        self._phase = Phase.IDLE
        self._active = None
        self._cooldown_until = 0.0

    def update(self, *, active: bool, score: float, label: str, t: float) -> Transition:
        if self._phase is Phase.COOLDOWN:
            if t >= self._cooldown_until:
                self._phase = Phase.IDLE
            else:
                return Transition(self._phase)

        if self._phase is Phase.IDLE:
            if active:
                self._active = ActiveEvent(
                    started_at=t, last_motion_at=t, peak_score=score, label=label
                )
                self._phase = Phase.RECORDING
                return Transition(self._phase, started=self._active)
            return Transition(self._phase)

        # RECORDING
        event = self._active
        assert event is not None
        if active:
            event.last_motion_at = t
            event.peak_score = max(event.peak_score, score)

        exceeded_cap = t - event.started_at >= self.max_clip_s
        post_roll_expired = t - event.last_motion_at >= self.post_roll_s

        if exceeded_cap or post_roll_expired:
            self._phase = Phase.COOLDOWN
            self._cooldown_until = t + self.cooldown_s
            self._active = None
            return Transition(self._phase, finished=event)

        return Transition(self._phase)


class ClipError(RuntimeError):
    """A clip could not be assembled from the ring."""


def build_clip(
    *,
    ring: Path,
    destination: Path,
    start: float,
    end: float,
    timeout: float = 60.0,
) -> tuple[int, float]:
    """Assemble ``[start, end]`` from ring segments into a browser-playable MP4.

    Stream copy only — no re-encode, so this is near-instant and lossless. Clip boundaries
    are therefore quantised to the segment grid (ADR-0003). ``+faststart`` moves the MP4
    index to the front, which iOS Safari needs to begin playback without fetching the whole
    file (ADR-0009).

    Returns ``(size_in_bytes, duration_seconds)``.
    """
    segments = select_segments(list_segments(ring), start, end)
    if not segments:
        raise ClipError(f"no ring segments cover [{start:.1f}, {end:.1f}]")

    # A short clip is a silent failure mode: the file plays, so nothing looks wrong, but
    # the footage the user wanted is gone. Say so loudly.
    span = coverage(segments)
    requested = end - start
    if span is not None and (span[1] - span[0]) < requested - SEGMENT_SECONDS:
        log.warning(
            "clip will be short: requested %.1fs but only %.1fs of ring segments remain "
            "(missing %.1fs from the start)",
            requested,
            span[1] - span[0],
            max(span[0] - start, 0.0),
        )

    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        for segment in segments:
            # Single quotes are the concat demuxer's escaping convention.
            escaped = str(segment.path).replace("'", r"'\''")
            handle.write(f"file '{escaped}'\n")
        list_path = Path(handle.name)

    try:
        command = [
            FFMPEG,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(destination),
        ]  # fmt: skip
        proc = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        if proc.returncode != 0 or not destination.exists():
            raise ClipError(f"ffmpeg concat failed: {proc.stderr.strip()[:400]}")
    finally:
        list_path.unlink(missing_ok=True)

    # Actual duration comes from the segments used, not from the requested window: the
    # grid quantisation means they differ, and the metadata must describe the real file.
    last = segments[-1]
    actual_duration = (last.start + 2.0) - segments[0].start
    return destination.stat().st_size, max(actual_duration, 0.0)


def probe_duration(path: Path) -> float | None:
    """Exact clip duration via ffprobe. Returns None if it cannot be determined."""
    try:
        proc = subprocess.run(  # noqa: S603
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],  # fmt: skip
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
        )
        return float(proc.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def wait_for_segments(ring: Path, until: float, timeout: float = 8.0) -> None:
    """Block until the ring contains a segment covering ``until``.

    Finalize runs the instant post-roll expires, but ffmpeg has not yet closed the segment
    that holds those final seconds. Without this wait the clip loses its tail.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        segments = list_segments(ring)
        if segments and segments[-1].start >= until:
            return
        time.sleep(0.25)
    log.warning("timed out waiting for ring segments covering %.1f", until)
