"""User settings: model, bounds, and JSON persistence.

Bounds are documented in docs/design.md section 6 and enforced here so that a hand-edited
config.json cannot put the recorder into an impossible state.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

GIB = 1024**3


class Settings(BaseModel):
    """Everything the user can change. Persisted verbatim to config.json."""

    # Camera identity — never an index. See ADR-0004.
    camera_name: str | None = None
    camera_uid: str | None = None
    width: int = Field(default=1280, ge=160, le=4096)
    height: int = Field(default=720, ge=120, le=2160)
    fps: int = Field(default=30, ge=1, le=60)

    # Detection
    sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    min_area: float = Field(default=0.004, ge=0.0001, le=1.0)

    # Event windows
    pre_roll_s: float = Field(default=5.0, ge=0.0, le=30.0)
    post_roll_s: float = Field(default=8.0, ge=1.0, le=60.0)
    cooldown_s: float = Field(default=10.0, ge=0.0, le=300.0)
    max_clip_s: float = Field(default=120.0, ge=10.0, le=600.0)

    # Retention — all three bounds apply simultaneously.
    retain_max_clips: int = Field(default=200, ge=1, le=100_000)
    retain_max_bytes: int = Field(default=10 * GIB, ge=100 * 1024 * 1024)
    retain_max_age_days: float = Field(default=14.0, ge=0.5, le=3650.0)

    # Start monitoring as soon as the host comes up.
    arm_on_start: bool = False

    @model_validator(mode="after")
    def _check_ring_covers_clips(self) -> Settings:
        """A clip may never outlive the ring segments it is assembled from.

        The janitor keeps ``ring_window_s`` of segments. If an event could run longer than
        that window, its earliest segments would be deleted before finalize, silently
        truncating the clip. See docs/backlog.md, "Ring janitor vs. long events".
        """
        if self.max_clip_s + self.post_roll_s > self.ring_window_s:
            raise ValueError(
                f"max_clip_s ({self.max_clip_s}s) + post_roll_s ({self.post_roll_s}s) exceeds "
                f"the ring window ({self.ring_window_s}s); the clip would lose its own start"
            )
        return self

    @property
    def ring_window_s(self) -> float:
        """Seconds of segments the janitor keeps.

        Must cover the longest possible event (pre-roll + max duration + post-roll) plus
        margin for finalize latency.
        """
        return self.pre_roll_s + self.max_clip_s + self.post_roll_s + 30.0

    @property
    def diff_threshold(self) -> float:
        """Grayscale difference (0-255) above which a pixel counts as changed.

        Sensitivity 0 -> 40 (only strong changes); sensitivity 1 -> 4 (very twitchy).
        """
        return 40.0 - 36.0 * self.sensitivity


class ConfigStore:
    """Thread-safe settings holder backed by a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._settings = self._load()

    def _load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            raw = json.loads(self._path.read_text())
            return Settings.model_validate(raw)
        except Exception:
            # A corrupt or outdated config must not prevent startup: monitoring with
            # defaults beats not monitoring at all.
            log.exception("config.json is unreadable; falling back to defaults")
            return Settings()

    @property
    def settings(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, patch: dict) -> Settings:
        """Apply a partial update, validate, persist, and return the new settings."""
        with self._lock:
            merged = self._settings.model_dump() | patch
            new = Settings.model_validate(merged)
            self._write(new)
            self._settings = new
            return new

    def _write(self, settings: Settings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(settings.model_dump(), indent=2) + "\n")
        tmp.replace(self._path)
