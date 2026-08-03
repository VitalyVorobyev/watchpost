"""Camera enumeration and identity resolution.

AVFoundation addresses devices by ordinal index, but that ordering is not stable: attaching
an iPhone (Continuity Camera) inserts entries and shifts everything after them. Watchpost
therefore persists ``(name, uid)`` and re-resolves the index immediately before every
capture launch. See ADR-0004.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

FFMPEG = "ffmpeg"

# Inputs AVFoundation reports that are not physical cameras. Desk View is a synthetic crop
# of another camera and screen capture is not a camera at all; offering either as a
# monitoring source would be a privacy trap.
_VIRTUAL_PATTERNS = (
    re.compile(r"^Capture screen \d+$"),
    re.compile(r"Desk View"),
)

_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")
_MODE_LINE = re.compile(r"(\d+)x(\d+)@\[([\d.]+)\s+([\d.]+)\]fps")


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    uid: str | None = None

    @property
    def is_virtual(self) -> bool:
        return any(pattern.search(self.name) for pattern in _VIRTUAL_PATTERNS)


@dataclass(frozen=True)
class CaptureMode:
    width: int
    height: int
    min_fps: float
    max_fps: float

    @property
    def fps(self) -> float:
        """The rate to actually request. Device modes are single-rate in practice."""
        return self.max_fps


class CameraError(RuntimeError):
    """The configured camera could not be resolved to a live device."""


def _run(args: list[str], timeout: float = 15.0) -> str:
    """Run a command and return combined output. ffmpeg reports device lists on stderr and
    exits non-zero when given no output file, so neither is treated as an error here."""
    proc = subprocess.run(  # noqa: S603
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.stdout + proc.stderr


def _unique_ids_by_name() -> dict[str, str]:
    """Map camera name to AVFoundation UniqueID via system_profiler.

    ffmpeg's device list has indices and names but no UIDs; system_profiler has names and
    UIDs but no indices. Joining on name is the only bridge available.
    """
    try:
        raw = _run(["system_profiler", "SPCameraDataType", "-json"], timeout=20.0)
        payload = json.loads(raw)
    except Exception:
        log.warning("system_profiler did not return usable camera data", exc_info=True)
        return {}

    mapping: dict[str, str] = {}
    for entry in payload.get("SPCameraDataType", []):
        name = entry.get("_name")
        uid = entry.get("spcamera_unique-id")
        if name and uid:
            mapping[name] = uid
    return mapping


def list_devices(include_virtual: bool = False) -> list[CameraDevice]:
    """Enumerate video inputs in AVFoundation index order."""
    output = _run([FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""])

    devices: list[CameraDevice] = []
    in_video_section = False
    for line in output.splitlines():
        if "AVFoundation video devices" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices" in line:
            break
        if not in_video_section:
            continue
        match = _DEVICE_LINE.search(line)
        if match:
            devices.append(CameraDevice(index=int(match.group(1)), name=match.group(2)))

    uids = _unique_ids_by_name()
    devices = [CameraDevice(d.index, d.name, uids.get(d.name)) for d in devices]

    if not include_virtual:
        devices = [d for d in devices if not d.is_virtual]
    return devices


def raw_modes(index: int) -> list[CaptureMode]:
    """Every mode the device advertises, one entry per resolution/rate pair.

    Uses the documented trick of requesting an impossible size: ffmpeg refuses and prints
    the list of modes it would accept.

    The exact rates matter. UVC devices advertise rationals such as ``30.000030``, and
    AVFoundation rejects a request for plain ``30`` with "Configuration of video device
    failed, falling back to default" — after which capture produces nothing usable. The
    frame rate must be echoed back exactly as advertised.
    """
    output = _run(
        [FFMPEG, "-hide_banner", "-f", "avfoundation", "-video_size", "1x1", "-i", str(index)]
    )
    return [
        CaptureMode(int(w), int(h), float(lo), float(hi))
        for w, h, lo, hi in _MODE_LINE.findall(output)
    ]


def supported_modes(index: int) -> list[CaptureMode]:
    """Advertised modes collapsed to one entry per resolution, for display."""
    by_resolution: dict[tuple[int, int], CaptureMode] = {}
    for mode in raw_modes(index):
        key = (mode.width, mode.height)
        existing = by_resolution.get(key)
        if existing is None:
            by_resolution[key] = mode
        else:
            by_resolution[key] = CaptureMode(
                mode.width,
                mode.height,
                min(existing.min_fps, mode.min_fps),
                max(existing.max_fps, mode.max_fps),
            )
    return sorted(by_resolution.values(), key=lambda m: m.width * m.height)


def resolve_mode(index: int, width: int, height: int, fps: float) -> CaptureMode | None:
    """Snap a requested mode to one the device actually advertises.

    Resolution is matched exactly when possible, otherwise by nearest pixel count. The rate
    is then the advertised rate closest to the request. Returns None when the device
    advertises nothing, in which case the caller should pass the request through unchanged
    and let ffmpeg negotiate.

    Note that an advertised rate is not a promise: this camera advertises 1280x720@30 but
    a USB bandwidth limit means it delivers about 10 fps uncompressed. That is fine — the
    segment ring forces keyframes on a *time* interval, not a frame count, so clip
    assembly is unaffected by the rate actually achieved.
    """
    modes = raw_modes(index)
    if not modes:
        return None

    exact = [m for m in modes if m.width == width and m.height == height]
    if exact:
        candidates = exact
    else:
        target_pixels = width * height
        best_resolution = min(
            {(m.width, m.height) for m in modes},
            key=lambda r: abs(r[0] * r[1] - target_pixels),
        )
        candidates = [m for m in modes if (m.width, m.height) == best_resolution]

    return min(candidates, key=lambda m: abs(m.fps - fps))


def resolve(name: str | None, uid: str | None) -> CameraDevice:
    """Resolve a persisted identity to a currently attached device.

    Matching is by UID first, then by name. There is deliberately **no** fallback to "the
    device at the old index" or "the first available camera": silently monitoring the wrong
    camera is worse than not monitoring at all.
    """
    devices = list_devices()
    if not devices:
        raise CameraError("No cameras are attached")

    if uid:
        for device in devices:
            if device.uid == uid:
                return device
    if name:
        for device in devices:
            if device.name == name:
                return device

    if name or uid:
        attached = ", ".join(d.name for d in devices) or "none"
        raise CameraError(f"Camera {name or uid!r} is not attached (attached: {attached})")

    # No camera configured yet: first physical device is a reasonable initial choice, and
    # the user is choosing it now rather than inheriting a stale one.
    return devices[0]


def pick_default() -> CameraDevice | None:
    """Best initial camera for a fresh install: prefer an external one over the built-in."""
    devices = list_devices()
    if not devices:
        return None
    external = [d for d in devices if "MacBook" not in d.name and "iPhone" not in d.name]
    return external[0] if external else devices[0]
