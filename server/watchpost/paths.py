"""Filesystem layout for runtime data.

Everything mutable lives outside the repository, under the macOS application-support
directory. See docs/design.md section 6.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_ROOT = "WATCHPOST_ROOT"


def storage_root() -> Path:
    """Root of all runtime data.

    Overridable via ``WATCHPOST_ROOT`` so tests and parallel instances never touch the
    user's real recordings.
    """
    override = os.environ.get(_ENV_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "Library" / "Application Support" / "Watchpost"


class Paths:
    """Resolved directory layout, created on demand."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or storage_root()).resolve()

    @property
    def db(self) -> Path:
        return self.root / "watchpost.db"

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def token(self) -> Path:
        return self.root / "token"

    @property
    def clips(self) -> Path:
        return self.root / "clips"

    @property
    def thumbs(self) -> Path:
        return self.root / "thumbs"

    @property
    def ring(self) -> Path:
        return self.root / "ring"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def tls(self) -> Path:
        """CA and host certificate. The private keys inside are written at mode 0600."""
        return self.root / "tls"

    def ensure(self) -> Paths:
        """Create every directory. Idempotent."""
        for directory in (self.root, self.clips, self.thumbs, self.ring, self.logs, self.tls):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def clip_path(self, event_id: str) -> Path:
        return self.clips / f"{event_id}.mp4"

    def thumb_path(self, event_id: str) -> Path:
        return self.thumbs / f"{event_id}.jpg"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Paths(root={self.root!s})"
