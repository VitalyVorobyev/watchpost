"""Event metadata, clip files, and retention.

Retention applies three bounds simultaneously — count, total bytes, and age. Any one alone
is insufficient: a count bound lets long clips fill the disk, a byte bound lets stale
footage live forever, and an age bound alone bounds nothing on a busy day.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass

from .paths import Paths

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    started_at   REAL NOT NULL,
    ended_at     REAL NOT NULL,
    duration_s   REAL NOT NULL,
    trigger      TEXT NOT NULL,
    clip_path    TEXT,
    thumb_path   TEXT,
    bytes        INTEGER NOT NULL DEFAULT 0,
    peak_score   REAL NOT NULL DEFAULT 0,
    viewed       INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_started_at ON events (started_at DESC);
"""

# Below this much free space the host stops recording rather than filling the disk.
FREE_BYTES_FULL = 1024**3
FREE_BYTES_WARNING = 5 * 1024**3


@dataclass
class Event:
    id: str
    started_at: float
    ended_at: float
    duration_s: float
    trigger: str
    clip_path: str | None
    thumb_path: str | None
    bytes: int
    peak_score: float
    viewed: bool
    created_at: float

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["viewed"] = bool(self.viewed)
        payload["has_clip"] = bool(self.clip_path)
        return payload


def new_event_id(at: float) -> str:
    """Time-ordered id: sortable by string, readable in a directory listing."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(at))
    return f"{stamp}-{os.urandom(3).hex()}"


class Store:
    """SQLite metadata plus the clip and thumbnail files on disk."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths
        self._lock = threading.Lock()
        # check_same_thread=False because capture, recorder, and API threads all touch the
        # store; every access is serialised by _lock.
        self._db = sqlite3.connect(paths.db, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- writes --------------------------------------------------------------

    def insert(self, event: Event) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO events (id, started_at, ended_at, duration_s, trigger,
                                       clip_path, thumb_path, bytes, peak_score, viewed,
                                       created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.id,
                    event.started_at,
                    event.ended_at,
                    event.duration_s,
                    event.trigger,
                    event.clip_path,
                    event.thumb_path,
                    event.bytes,
                    event.peak_score,
                    int(event.viewed),
                    event.created_at,
                ),
            )
            self._db.commit()

    def mark_viewed(self, event_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute("UPDATE events SET viewed=1 WHERE id=?", (event_id,))
            self._db.commit()
            return cursor.rowcount > 0

    def delete(self, event_id: str) -> bool:
        event = self.get(event_id)
        if event is None:
            return False
        with self._lock:
            self._db.execute("DELETE FROM events WHERE id=?", (event_id,))
            self._db.commit()
        self._remove_files(event)
        return True

    def _remove_files(self, event: Event) -> None:
        for relative in (event.clip_path, event.thumb_path):
            if not relative:
                continue
            path = self._paths.root / relative
            try:
                path.unlink(missing_ok=True)
            except OSError:
                log.warning("could not delete %s", path, exc_info=True)

    # -- reads ---------------------------------------------------------------

    def get(self, event_id: str) -> Event | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return _row_to_event(row) if row else None

    def list(self, limit: int = 50, before: float | None = None) -> list[Event]:
        query = "SELECT * FROM events"
        params: list[float | int] = []
        if before is not None:
            query += " WHERE started_at < ?"
            params.append(before)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._db.execute(query, params).fetchall()
        return [_row_to_event(row) for row in rows]

    def neighbours(self, event_id: str) -> tuple[str | None, str | None]:
        """Ids of the events immediately newer and older than this one."""
        event = self.get(event_id)
        if event is None:
            return None, None
        with self._lock:
            newer = self._db.execute(
                "SELECT id FROM events WHERE started_at > ? ORDER BY started_at ASC LIMIT 1",
                (event.started_at,),
            ).fetchone()
            older = self._db.execute(
                "SELECT id FROM events WHERE started_at < ? ORDER BY started_at DESC LIMIT 1",
                (event.started_at,),
            ).fetchone()
        return (newer["id"] if newer else None, older["id"] if older else None)

    def totals(self) -> tuple[int, int]:
        """(clip count, total bytes)."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM events"
            ).fetchone()
        return int(row["n"]), int(row["total"])

    def storage_report(self) -> tuple[str, int, int, int]:
        """(status, clip count, bytes used, bytes free)."""
        clips, used = self.totals()
        free = shutil.disk_usage(self._paths.root).free
        if free < FREE_BYTES_FULL:
            status = "full"
        elif free < FREE_BYTES_WARNING:
            status = "warning"
        else:
            status = "ok"
        return status, clips, used, free

    # -- retention -----------------------------------------------------------

    def enforce_retention(
        self, *, max_clips: int, max_bytes: int, max_age_days: float
    ) -> list[str]:
        """Delete oldest-first until every bound is satisfied. Returns deleted ids."""
        deleted: list[str] = []
        cutoff = time.time() - max_age_days * 86400.0

        with self._lock:
            rows = self._db.execute(
                "SELECT id, started_at, bytes FROM events ORDER BY started_at ASC"
            ).fetchall()

        total_bytes = sum(int(row["bytes"]) for row in rows)
        total_count = len(rows)

        for row in rows:
            over_age = row["started_at"] < cutoff
            over_count = total_count > max_clips
            over_bytes = total_bytes > max_bytes
            if not (over_age or over_count or over_bytes):
                break
            if self.delete(row["id"]):
                deleted.append(row["id"])
                total_count -= 1
                total_bytes -= int(row["bytes"])

        if deleted:
            log.info("retention removed %d event(s)", len(deleted))
        return deleted


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_s=row["duration_s"],
        trigger=row["trigger"],
        clip_path=row["clip_path"],
        thumb_path=row["thumb_path"],
        bytes=int(row["bytes"]),
        peak_score=row["peak_score"],
        viewed=bool(row["viewed"]),
        created_at=row["created_at"],
    )
