"""The ffmpeg capture supervisor.

One ffmpeg process owns the camera and fans out to two branches: a raw RGB pipe this module
reads for detection and preview, and a continuous H.264 segment ring on disk that the
recorder later assembles clips from. See ADR-0002 and ADR-0003.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .camera import FFMPEG, CameraDevice, CameraError, CaptureMode, resolve, resolve_mode
from .config import Settings

log = logging.getLogger(__name__)

# Detection and preview resolution. Small enough that a frame costs ~390 KB and the
# per-frame numpy work is well under a millisecond; large enough for a usable phone
# preview.
DETECT_WIDTH = 480
DETECT_HEIGHT = 270
DETECT_FPS = 10
FRAME_BYTES = DETECT_WIDTH * DETECT_HEIGHT * 3

SEGMENT_SECONDS = 2

_SEGMENT_NAME = re.compile(r"^(\d{8})-(\d{6})\.ts$")

FrameCallback = Callable[[np.ndarray, float], None]


@dataclass(frozen=True)
class Segment:
    path: Path
    start: float
    """Wall-clock time the segment was opened, from its strftime filename."""


def segment_start_time(path: Path) -> float | None:
    """Parse the wall-clock start encoded in a ring segment's filename."""
    match = _SEGMENT_NAME.match(path.name)
    if not match:
        return None
    try:
        parsed = time.strptime(f"{match.group(1)}-{match.group(2)}", "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return time.mktime(parsed)


def list_segments(ring: Path) -> list[Segment]:
    """Ring segments in chronological order, ignoring anything unparseable."""
    segments = []
    for path in ring.glob("*.ts"):
        start = segment_start_time(path)
        if start is not None:
            segments.append(Segment(path, start))
    return sorted(segments, key=lambda s: s.start)


def select_segments(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """Every segment overlapping ``[start, end]``.

    A segment's end is taken from the next segment's start where one exists, which is
    exact, and falls back to the nominal duration for the final (still-being-written)
    segment. The window is inclusive at both ends: a clip that starts slightly early is
    correct behaviour, a clip missing its trigger is not.
    """
    if not segments or end < start:
        return []

    selected = []
    for index, segment in enumerate(segments):
        if index + 1 < len(segments):
            segment_end = segments[index + 1].start
        else:
            segment_end = segment.start + SEGMENT_SECONDS
        if segment_end > start and segment.start < end:
            selected.append(segment)
    return selected


def prune_ring(ring: Path, keep_from: float) -> int:
    """Delete ring segments that end before ``keep_from``. Returns the number removed.

    The floor is an absolute timestamp rather than an age so that an in-flight event can
    pin it: an event being recorded needs its own opening segments to survive until
    finalize, and those are by definition the oldest ones in the ring.

    The newest segment is never removed — ffmpeg is still writing to it.
    """
    segments = list_segments(ring)
    removed = 0
    for index, segment in enumerate(segments[:-1]):
        segment_end = segments[index + 1].start
        if segment_end < keep_from:
            try:
                segment.path.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def coverage(segments: list[Segment]) -> tuple[float, float] | None:
    """The wall-clock span these segments actually cover."""
    if not segments:
        return None
    return segments[0].start, segments[-1].start + SEGMENT_SECONDS


def build_command(
    device_index: int, settings: Settings, ring: Path, mode: CaptureMode | None = None
) -> list[str]:
    """The dual-output capture command. See ADR-0002 for why it is shaped this way.

    ``mode`` carries the device's advertised resolution and *exact* rational frame rate.
    Requesting a rounded rate makes AVFoundation fall back to a default configuration that
    then produces no frames, so the advertised value is echoed back verbatim.

    No ``-pixel_format`` is requested: the supported set varies per device and per
    connection speed, and ffmpeg negotiates a working one on its own. Pinning it caused
    configuration failures on the UVC camera this was developed against.
    """
    width = mode.width if mode else settings.width
    height = mode.height if mode else settings.height
    fps = f"{mode.fps:.6f}" if mode else str(settings.fps)
    gop = max(int(round((mode.fps if mode else settings.fps) * SEGMENT_SECONDS)), 1)

    return [
        FFMPEG,
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "avfoundation",
        "-framerate", fps,
        "-video_size", f"{width}x{height}",
        "-i", str(device_index),
        # Branch 1 — decoded frames for detection and preview.
        "-map", "0:v",
        "-vf", f"fps={DETECT_FPS},scale={DETECT_WIDTH}:{DETECT_HEIGHT}",
        "-pix_fmt", "rgb24",
        "-f", "rawvideo",
        "pipe:1",
        # Branch 2 — the segment ring. Keyframes are forced at the segment period so every
        # segment opens on one, which is what makes stream-copy concatenation valid.
        "-map", "0:v",
        "-c:v", "h264_videotoolbox",
        "-b:v", "4M",
        "-color_range", "mpeg",
        "-g", str(gop),
        "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})",
        "-f", "segment",
        "-segment_time", str(SEGMENT_SECONDS),
        "-segment_format", "mpegts",
        "-reset_timestamps", "1",
        "-strftime", "1",
        str(ring / "%Y%m%d-%H%M%S.ts"),
    ]  # fmt: skip


def _fill(stream, view: memoryview) -> bool:
    """Read exactly ``len(view)`` bytes into ``view``. Returns False at end of stream.

    A pipe hands over at most its buffer size (64 KB on macOS) per syscall, so a ~390 KB
    frame *always* arrives in pieces. Treating a short read as end-of-stream — which is
    what a bare ``read(n)`` on an unbuffered pipe invites — kills capture on the very first
    frame.
    """
    offset = 0
    total = len(view)
    while offset < total:
        try:
            count = stream.readinto(view[offset:])
        except (BrokenPipeError, ValueError):
            return False
        if not count:
            return False
        offset += count
    return True


class CaptureService:
    """Runs ffmpeg, delivers frames, and restarts on failure.

    Restart is unconditional and backed off rather than conditional on the failure reason:
    USB cameras fail in many ways and almost all of them are fixed by reopening the device.
    """

    RESTART_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)

    def __init__(
        self,
        *,
        ring: Path,
        get_settings: Callable[[], Settings],
        on_frame: FrameCallback,
        on_status: Callable[[str, CameraDevice | None, CaptureMode | None, str | None], None],
    ) -> None:
        self._ring = ring
        self._get_settings = get_settings
        self._on_frame = on_frame
        self._on_status = on_status
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._restarts = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._terminate()
        thread = self._thread
        if thread:
            thread.join(timeout=5.0)

    def restart(self) -> None:
        """Force a reopen, e.g. after the user changes camera or resolution."""
        self._terminate()

    def _terminate(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_once()
                self._restarts = 0
            except CameraError as exc:
                self._on_status("disconnected", None, None, str(exc))
            except Exception as exc:  # noqa: BLE001 - supervisor must never die
                log.exception("capture failed")
                self._on_status("error", None, None, str(exc))

            if self._stop.is_set():
                break
            delay = self.RESTART_DELAYS[min(self._restarts, len(self.RESTART_DELAYS) - 1)]
            self._restarts += 1
            self._stop.wait(delay)

    def _run_once(self) -> None:
        settings = self._get_settings()
        device = resolve(settings.camera_name, settings.camera_uid)
        mode = resolve_mode(device.index, settings.width, settings.height, settings.fps)
        command = build_command(device.index, settings, self._ring, mode)
        if mode:
            log.info(
                "opening %s (index %d) at %dx%d@%.4f fps",
                device.name,
                device.index,
                mode.width,
                mode.height,
                mode.fps,
            )
        else:
            log.info("opening %s (index %d), no advertised modes", device.name, device.index)

        process = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        with self._lock:
            self._process = process

        stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(process,), name="capture-stderr", daemon=True
        )
        stderr_thread.start()

        try:
            self._read_frames(process, device, mode)
        finally:
            self._terminate()
            stderr_thread.join(timeout=1.0)

    def _read_frames(
        self, process: subprocess.Popen[bytes], device: CameraDevice, mode: CaptureMode | None
    ) -> None:
        assert process.stdout is not None
        announced = False

        # One reused buffer for the whole session: a frame is ~390 KB and allocating a
        # fresh one ten times a second is pure garbage-collector pressure. Consumers that
        # need to keep a frame copy it — see PreviewService.offer.
        buffer = bytearray(FRAME_BYTES)
        view = memoryview(buffer)
        frame = np.frombuffer(buffer, dtype=np.uint8).reshape(DETECT_HEIGHT, DETECT_WIDTH, 3)

        while not self._stop.is_set():
            if not _fill(process.stdout, view):
                break
            if not announced:
                self._on_status("ready", device, mode, None)
                announced = True

            try:
                self._on_frame(frame, time.time())
            except Exception:  # noqa: BLE001 - a consumer bug must not kill capture
                log.exception("frame consumer raised")

        code = process.poll()
        if code not in (0, None) and not self._stop.is_set():
            raise RuntimeError(f"ffmpeg exited with code {code}")
        if not self._stop.is_set():
            raise RuntimeError("camera stream ended unexpectedly")

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[bytes]) -> None:
        """Consume ffmpeg's stderr.

        This is not only for logging: an unread stderr pipe fills its buffer and blocks
        ffmpeg, which would stall capture entirely.
        """
        assert process.stderr is not None
        for raw in process.stderr:
            line = raw.decode(errors="replace").strip()
            if line:
                log.warning("ffmpeg: %s", line)
