"""Pairing token: generation, storage, and constant-time verification.

See ADR-0006 for the threat model and the accepted risks of plain HTTP on the LAN.
"""

from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path


class TokenStore:
    """A single shared token, persisted at mode 0600."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._token = self._load_or_create()

    def _load_or_create(self) -> str:
        if self._path.exists():
            existing = self._path.read_text().strip()
            if existing:
                # Repair permissions in case the file was created by an older version or
                # copied without its mode.
                os.chmod(self._path, 0o600)
                return existing

        token = secrets.token_urlsafe(32)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Create with 0600 from the outset rather than writing then chmod-ing, which would
        # leave a window where the token is world-readable.
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(token + "\n")
        return token

    @property
    def token(self) -> str:
        return self._token

    def verify(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return hmac.compare_digest(candidate, self._token)
