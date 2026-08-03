"""Application wiring.

Owns the lifecycle and the connections between capture, detection, recording, storage, and
state. The API layer talks to this object and never to the components directly, so that all
state transitions happen in one place.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from . import __version__
from .auth import TokenStore
from .camera import CameraDevice, CameraError, CaptureMode, list_devices, pick_default
from .capture import CaptureService, prune_ring
from .config import ConfigStore, Settings
from .detect import Detection, MotionDetector
from .paths import Paths
from .preview import PreviewService
from .recorder import (
    ActiveEvent,
    ClipError,
    EventRecorder,
    build_clip,
    probe_duration,
    wait_for_segments,
)
from .state import AppState, CameraStatus, RecordingStatus, StateService, StorageStatus
from .store import Event, Store, new_event_id

log = logging.getLogger(__name__)

JANITOR_INTERVAL_S = 10.0


def lan_ip() -> str | None:
    """Best-guess LAN address, found by asking the routing table which interface would be
    used to reach an external address. No packet is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unroutable
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


class Application:
    def __init__(self, paths: Paths, port: int = 8787) -> None:
        self.paths = paths.ensure()
        self.port = port
        self.config = ConfigStore(self.paths.config)
        self.tokens = TokenStore(self.paths.token)
        self.store = Store(self.paths)
        self.state = StateService()
        self.preview = PreviewService()

        settings = self.config.settings
        self.detector = MotionDetector(
            diff_threshold=settings.diff_threshold, min_area=settings.min_area
        )
        self.recorder = EventRecorder(
            post_roll_s=settings.post_roll_s,
            cooldown_s=settings.cooldown_s,
            max_clip_s=settings.max_clip_s,
        )
        self.capture = CaptureService(
            ring=self.paths.ring,
            get_settings=lambda: self.config.settings,
            on_frame=self._on_frame,
            on_status=self._on_camera_status,
        )

        # Clip assembly runs off the capture thread: a stall there would drop frames.
        self._clips = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clip")
        self._trigger_frame: np.ndarray | None = None
        # Oldest ring timestamp an in-flight event still needs. While set, the janitor may
        # not prune past it — an event's opening segments are the oldest in the ring and
        # are exactly what pre-roll depends on.
        self._ring_floor: float | None = None
        self._caffeinate: subprocess.Popen | None = None
        self._janitor_stop = threading.Event()
        self._janitor: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.state.bind_loop(loop)
        self._ensure_camera_selected()

        ip = lan_ip()
        url = f"http://{ip}:{self.port}" if ip else None

        def init(state: AppState) -> None:
            state.host.status = "running"
            state.host.version = __version__
            state.host.lan_url = url
            state.detector.threshold = self.config.settings.min_area

        self.state.mutate(init)
        self._refresh_storage()

        self.capture.start()
        self._janitor = threading.Thread(target=self._janitor_loop, name="janitor", daemon=True)
        self._janitor.start()

        if self.config.settings.arm_on_start:
            self.arm()

    def shutdown(self) -> None:
        self._janitor_stop.set()
        self.capture.stop()
        self._stop_caffeinate()
        self._clips.shutdown(wait=False, cancel_futures=True)
        self.store.close()

    def _ensure_camera_selected(self) -> None:
        """Pick a camera on first run so a fresh install monitors something immediately."""
        settings = self.config.settings
        if settings.camera_name or settings.camera_uid:
            return
        device = pick_default()
        if device is None:
            self.state.push_error("no_camera", "No cameras are attached")
            return
        self.config.update({"camera_name": device.name, "camera_uid": device.uid})
        log.info("selected default camera: %s", device.name)

    # -- commands ------------------------------------------------------------

    def arm(self) -> None:
        if self.state.armed:
            return

        def apply(state: AppState) -> None:
            state.monitoring.armed = True
            state.monitoring.armed_at = time.time()

        self.state.mutate(apply)
        # Reset so the detector does not fire on whatever changed while disarmed.
        self.detector.reset()
        self.recorder.reset()
        self._start_caffeinate()
        log.info("armed")

    def disarm(self) -> None:
        if not self.state.armed:
            return

        def apply(state: AppState) -> None:
            state.monitoring.armed = False
            state.monitoring.armed_at = None
            state.recording.status = RecordingStatus.IDLE
            state.recording.event_id = None
            state.recording.started_at = None

        self.state.mutate(apply)
        self.recorder.reset()
        self._stop_caffeinate()
        log.info("disarmed")

    def update_settings(self, patch: dict) -> Settings:
        previous = self.config.settings
        settings = self.config.update(patch)

        self.detector.configure(diff_threshold=settings.diff_threshold, min_area=settings.min_area)
        self.recorder.configure(
            post_roll_s=settings.post_roll_s,
            cooldown_s=settings.cooldown_s,
            max_clip_s=settings.max_clip_s,
        )

        def apply(state: AppState) -> None:
            state.detector.threshold = settings.min_area

        self.state.mutate(apply)

        # Only a capture-shaping change justifies dropping the stream; restarting on every
        # sensitivity nudge would blind the camera for a second each time.
        capture_changed = any(
            getattr(previous, field) != getattr(settings, field)
            for field in ("camera_name", "camera_uid", "width", "height", "fps")
        )
        if capture_changed:
            log.info("capture settings changed; restarting camera")
            self.capture.restart()
        return settings

    def select_camera(self, name: str, uid: str | None) -> Settings:
        return self.update_settings({"camera_name": name, "camera_uid": uid})

    def cameras(self) -> list[CameraDevice]:
        try:
            return list_devices()
        except Exception:  # noqa: BLE001
            log.exception("camera enumeration failed")
            return []

    # -- capture callbacks ---------------------------------------------------

    def _on_camera_status(
        self,
        status: str,
        device: CameraDevice | None,
        mode: CaptureMode | None,
        message: str | None,
    ) -> None:
        def apply(state: AppState) -> None:
            state.camera.status = CameraStatus(status)
            state.camera.message = message
            if device is not None:
                settings = self.config.settings
                state.camera.name = device.name
                state.camera.uid = device.uid
                # Report the negotiated mode, not the requested one — the device may not
                # offer exactly what was asked for.
                state.camera.width = mode.width if mode else settings.width
                state.camera.height = mode.height if mode else settings.height
                state.camera.fps = round(mode.fps) if mode else settings.fps

        self.state.mutate(apply)
        if status != "ready":
            self.preview.clear()
            if message:
                self.state.push_error(f"camera_{status}", message)

    def _on_frame(self, frame: np.ndarray, t: float) -> None:
        self.preview.offer(frame, t)

        if not self.state.armed:
            return

        detection = self.detector.update(frame, t)
        transition = self.recorder.update(
            active=detection.active, score=detection.score, label=detection.label, t=t
        )

        if transition.started is not None:
            # Keep the trigger frame for the thumbnail: it is the most representative
            # moment of the event, and by finalize time it is long gone.
            self._trigger_frame = frame.copy()
            self._begin_event(transition.started)
        elif transition.finished is not None:
            self._finish_event(transition.finished)

        self._publish_detector(detection)

    def _publish_detector(self, detection: Detection) -> None:
        state = self.state.snapshot()
        # Publishing every frame would emit 10 SSE messages a second per client. Only
        # meaningful movement across the threshold is worth waking clients for.
        was_above = state["detector"]["score"] > detection.threshold
        is_above = detection.score > detection.threshold
        changed_materially = abs(state["detector"]["score"] - detection.score) > 0.01
        if was_above == is_above and not changed_materially:
            return

        def apply(app_state: AppState) -> None:
            app_state.detector.score = detection.score
            app_state.detector.threshold = detection.threshold

        self.state.mutate(apply)

    # -- events --------------------------------------------------------------

    def _begin_event(self, event: ActiveEvent) -> None:
        def apply(state: AppState) -> None:
            state.recording.status = RecordingStatus.RECORDING
            state.recording.started_at = event.started_at
            state.recording.event_id = None

        self._ring_floor = event.started_at - self.config.settings.pre_roll_s
        self.state.mutate(apply)
        log.info("motion detected at %.1f", event.started_at)

    def _finish_event(self, event: ActiveEvent) -> None:
        def apply(state: AppState) -> None:
            state.recording.status = RecordingStatus.FINALIZING

        self.state.mutate(apply)
        frame = self._trigger_frame
        self._trigger_frame = None
        self._clips.submit(self._produce_clip, event, frame)

    def _produce_clip(self, event: ActiveEvent, trigger_frame: np.ndarray | None) -> None:
        settings = self.config.settings
        start = event.started_at - settings.pre_roll_s
        end = event.last_motion_at + settings.post_roll_s
        event_id = new_event_id(event.started_at)

        try:
            # ffmpeg has not yet closed the segment holding the final seconds.
            wait_for_segments(self.paths.ring, end)

            clip = self.paths.clip_path(event_id)
            size, approx_duration = build_clip(
                ring=self.paths.ring, destination=clip, start=start, end=end
            )
            duration = probe_duration(clip) or approx_duration

            thumb_relative = None
            if trigger_frame is not None:
                thumb = self.paths.thumb_path(event_id)
                Image.fromarray(trigger_frame, mode="RGB").save(thumb, "JPEG", quality=80)
                thumb_relative = str(thumb.relative_to(self.paths.root))

            record = Event(
                id=event_id,
                started_at=start,
                ended_at=end,
                duration_s=duration,
                trigger=event.label,
                clip_path=str(clip.relative_to(self.paths.root)),
                thumb_path=thumb_relative,
                bytes=size,
                peak_score=event.peak_score,
                viewed=False,
                created_at=time.time(),
            )
            self.store.insert(record)
            self.state.publish_event(record.to_dict())
            log.info("recorded event %s (%.1fs, %d bytes)", event_id, duration, size)

            self.store.enforce_retention(
                max_clips=settings.retain_max_clips,
                max_bytes=settings.retain_max_bytes,
                max_age_days=settings.retain_max_age_days,
            )
        except (ClipError, CameraError, OSError) as exc:
            log.error("could not build clip for event %s: %s", event_id, exc)
            self.state.push_error("clip_failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("unexpected failure building clip")
            self.state.push_error("clip_failed", str(exc))
        finally:
            # Release the ring only once the clip exists on disk.
            self._ring_floor = None
            self._settle_recording_state()
            self._refresh_storage()

    def _settle_recording_state(self) -> None:
        phase = self.recorder.phase

        def apply(state: AppState) -> None:
            state.recording.status = RecordingStatus(str(phase))
            state.recording.event_id = None
            state.recording.started_at = None

        self.state.mutate(apply)

    # -- background housekeeping --------------------------------------------

    def _janitor_loop(self) -> None:
        while not self._janitor_stop.is_set():
            try:
                floor = time.time() - self.config.settings.ring_window_s
                protected = self._ring_floor
                if protected is not None:
                    floor = min(floor, protected)
                prune_ring(self.paths.ring, floor)
                self._refresh_storage()
                self._settle_cooldown()
            except Exception:  # noqa: BLE001 - housekeeping must never die
                log.exception("janitor iteration failed")
            self._janitor_stop.wait(JANITOR_INTERVAL_S)

    def _settle_cooldown(self) -> None:
        """Advance the recorder out of COOLDOWN when no frames are arriving.

        The state machine is driven by frames; without this the UI would sit in COOLDOWN
        indefinitely whenever the camera drops right after an event.
        """
        if not self.state.armed:
            return
        transition = self.recorder.update(active=False, score=0.0, label="motion", t=time.time())
        snapshot = self.state.snapshot()
        if snapshot["recording"]["status"] != str(transition.phase) and transition.finished is None:
            self._settle_recording_state()

    def _refresh_storage(self) -> None:
        status, clips, used, free = self.store.storage_report()

        def apply(state: AppState) -> None:
            state.storage.status = StorageStatus(status)
            state.storage.clips = clips
            state.storage.bytes = used
            state.storage.free_bytes = free

        self.state.mutate(apply)

    # -- sleep prevention ----------------------------------------------------

    def _start_caffeinate(self) -> None:
        """Prevent idle and display sleep while armed.

        This cannot defeat a closed lid — see ADR-0009. The UI says so; here we only do
        what is actually possible.
        """
        with self._lock:
            if self._caffeinate and self._caffeinate.poll() is None:
                return
            try:
                self._caffeinate = subprocess.Popen(  # noqa: S603, S607
                    ["caffeinate", "-dimsu"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                log.warning("could not start caffeinate; the Mac may sleep while armed")

    def _stop_caffeinate(self) -> None:
        with self._lock:
            process = self._caffeinate
            self._caffeinate = None
        if process and process.poll() is None:
            process.terminate()
