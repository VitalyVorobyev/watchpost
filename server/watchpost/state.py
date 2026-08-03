"""The authoritative runtime state and its change bus.

Every interface observes this state rather than inferring its own. That is the rule that
keeps the Mac window and the phone from disagreeing about whether something is recording.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class CaptureStatus(StrEnum):
    """Whether the user wants the camera open at all.

    Deliberately separate from :class:`CameraStatus`, which describes the *device*. "Off"
    is an intention, not a fault, and an interface that cannot tell the two apart will
    report a deliberate privacy choice as a failure.
    """

    ON = "on"
    OFF = "off"


class CameraStatus(StrEnum):
    UNKNOWN = "unknown"
    READY = "ready"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class RecordingStatus(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"
    FINALIZING = "finalizing"
    COOLDOWN = "cooldown"


class StorageStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    FULL = "full"


class HostStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"


@dataclass
class ErrorEntry:
    at: float
    code: str
    message: str


@dataclass
class CameraState:
    status: CameraStatus = CameraStatus.UNKNOWN
    name: str | None = None
    uid: str | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    message: str | None = None


@dataclass
class CaptureState:
    status: CaptureStatus = CaptureStatus.ON


@dataclass
class MonitoringState:
    armed: bool = False
    armed_at: float | None = None


@dataclass
class RecordingState:
    status: RecordingStatus = RecordingStatus.IDLE
    event_id: str | None = None
    started_at: float | None = None


@dataclass
class StorageState:
    status: StorageStatus = StorageStatus.OK
    clips: int = 0
    bytes: int = 0
    free_bytes: int = 0


@dataclass
class DetectorState:
    score: float = 0.0
    threshold: float = 0.0


@dataclass
class HostState:
    status: HostStatus = HostStatus.STARTING
    version: str = "0.1.0"
    started_at: float = field(default_factory=time.time)
    lan_url: str | None = None


@dataclass
class AppState:
    host: HostState = field(default_factory=HostState)
    capture: CaptureState = field(default_factory=CaptureState)
    camera: CameraState = field(default_factory=CameraState)
    monitoring: MonitoringState = field(default_factory=MonitoringState)
    recording: RecordingState = field(default_factory=RecordingState)
    storage: StorageState = field(default_factory=StorageState)
    detector: DetectorState = field(default_factory=DetectorState)
    errors: list[ErrorEntry] = field(default_factory=list)


MAX_ERRORS = 20


class StateService:
    """Holds :class:`AppState` and fans changes out to SSE subscribers.

    Mutation happens on capture and recorder threads; subscribers live on the asyncio event
    loop. The lock guards the state, and ``call_soon_threadsafe`` bridges the two worlds.
    """

    def __init__(self) -> None:
        self._state = AppState()
        self._lock = threading.RLock()
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # -- reading -------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return asdict(self._state)

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._state.monitoring.armed

    # -- mutation ------------------------------------------------------------

    def mutate(self, fn) -> None:
        """Apply ``fn(state)`` under the lock, then publish the new snapshot."""
        with self._lock:
            fn(self._state)
            payload = asdict(self._state)
        self._publish({"type": "state", "state": payload})

    def push_error(self, code: str, message: str) -> None:
        def apply(state: AppState) -> None:
            state.errors.insert(0, ErrorEntry(time.time(), code, message))
            del state.errors[MAX_ERRORS:]

        self.mutate(apply)

    def publish_event(self, event: dict[str, Any]) -> None:
        """Announce a newly recorded event to subscribers."""
        self._publish({"type": "event", "event": event})

    # -- subscription --------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def _publish(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        with self._lock:
            targets = list(self._subscribers)
        for queue in targets:
            loop.call_soon_threadsafe(self._offer, queue, message)

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        """Enqueue without ever blocking a producer.

        A slow or stalled client must not back-pressure the capture thread. When its queue
        is full the oldest message is dropped: subscribers receive whole state snapshots,
        so a dropped one is superseded by the next rather than lost.
        """
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(message)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass
