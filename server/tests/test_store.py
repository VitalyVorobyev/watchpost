"""Retention bounds, event CRUD, and settings validation."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from watchpost.config import ConfigStore, Settings
from watchpost.paths import Paths
from watchpost.store import Event, Store, new_event_id

MIB = 1024**2


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(Paths(tmp_path).ensure())


def make(store: Store, *, at: float, size: int = MIB, event_id: str | None = None) -> str:
    event_id = event_id or new_event_id(at)
    clip = store._paths.clip_path(event_id)
    clip.write_bytes(b"\0" * 16)
    store.insert(
        Event(
            id=event_id,
            started_at=at,
            ended_at=at + 10,
            duration_s=10,
            trigger="motion",
            clip_path=str(clip.relative_to(store._paths.root)),
            thumb_path=None,
            bytes=size,
            peak_score=0.2,
            viewed=False,
            created_at=at,
        )
    )
    return event_id


# -- CRUD -----------------------------------------------------------------


def test_insert_and_read_back(store: Store):
    event_id = make(store, at=time.time())
    event = store.get(event_id)
    assert event is not None
    assert event.trigger == "motion"
    assert event.viewed is False


def test_list_is_newest_first(store: Store):
    now = time.time()
    for offset in (0, 100, 200):
        make(store, at=now - offset)
    events = store.list()
    assert [e.started_at for e in events] == sorted((e.started_at for e in events), reverse=True)


def test_delete_removes_the_clip_file(store: Store):
    event_id = make(store, at=time.time())
    clip = store._paths.clip_path(event_id)
    assert clip.exists()

    assert store.delete(event_id) is True
    assert not clip.exists()
    assert store.get(event_id) is None
    assert store.delete(event_id) is False


def test_mark_viewed(store: Store):
    event_id = make(store, at=time.time())
    assert store.mark_viewed(event_id) is True
    assert store.get(event_id).viewed is True
    assert store.mark_viewed("nope") is False


def test_neighbours(store: Store):
    now = time.time()
    older = make(store, at=now - 200)
    middle = make(store, at=now - 100)
    newer = make(store, at=now)

    assert store.neighbours(middle) == (newer, older)
    assert store.neighbours(newer)[0] is None
    assert store.neighbours(older)[1] is None


# -- retention ------------------------------------------------------------


def test_retention_by_count(store: Store):
    now = time.time()
    for index in range(10):
        make(store, at=now - index * 60)

    deleted = store.enforce_retention(max_clips=4, max_bytes=10**12, max_age_days=3650)
    assert len(deleted) == 6
    assert store.totals()[0] == 4


def test_retention_by_bytes(store: Store):
    now = time.time()
    for index in range(10):
        make(store, at=now - index * 60, size=10 * MIB)

    store.enforce_retention(max_clips=10_000, max_bytes=35 * MIB, max_age_days=3650)
    _, total = store.totals()
    assert total <= 35 * MIB


def test_retention_by_age(store: Store):
    now = time.time()
    make(store, at=now - 10 * 86400)
    make(store, at=now - 5 * 86400)
    fresh = make(store, at=now)

    store.enforce_retention(max_clips=10_000, max_bytes=10**12, max_age_days=7)
    remaining = [e.id for e in store.list()]
    assert fresh in remaining
    assert len(remaining) == 2


def test_retention_deletes_oldest_first(store: Store):
    now = time.time()
    ids = [make(store, at=now - index * 60) for index in range(5)]

    store.enforce_retention(max_clips=2, max_bytes=10**12, max_age_days=3650)
    remaining = {e.id for e in store.list()}
    # ids[0] is the newest because each subsequent one is further in the past.
    assert remaining == {ids[0], ids[1]}


def test_all_three_bounds_apply_together(store: Store):
    """Each bound alone leaves a hole; together they must all hold."""
    now = time.time()
    for index in range(20):
        make(store, at=now - index * 86400, size=5 * MIB)

    store.enforce_retention(max_clips=10, max_bytes=20 * MIB, max_age_days=30)
    count, total = store.totals()
    assert count <= 10
    assert total <= 20 * MIB


# -- settings -------------------------------------------------------------


def test_settings_reject_out_of_range_values():
    with pytest.raises(ValidationError):
        Settings(sensitivity=5.0)
    with pytest.raises(ValidationError):
        Settings(post_roll_s=0.0)


@pytest.mark.parametrize(
    ("pre_roll_s", "post_roll_s", "max_clip_s"),
    [(0.0, 1.0, 10.0), (5.0, 8.0, 120.0), (30.0, 60.0, 600.0)],
)
def test_ring_window_always_covers_a_maximal_event(pre_roll_s, post_roll_s, max_clip_s):
    """The ring must outlive the longest clip it could be asked to assemble.

    Otherwise an event's opening segments are pruned before finalize and the clip silently
    loses its own start — which is exactly what pre-roll exists to provide.
    """
    settings = Settings(pre_roll_s=pre_roll_s, post_roll_s=post_roll_s, max_clip_s=max_clip_s)
    assert settings.ring_window_s >= pre_roll_s + max_clip_s + post_roll_s


def test_sensitivity_maps_to_a_falling_threshold():
    assert Settings(sensitivity=0.0).diff_threshold > Settings(sensitivity=1.0).diff_threshold


def test_config_round_trips(tmp_path: Path):
    config = ConfigStore(tmp_path / "config.json")
    config.update({"sensitivity": 0.8, "pre_roll_s": 3.0})

    reloaded = ConfigStore(tmp_path / "config.json")
    assert reloaded.settings.sensitivity == pytest.approx(0.8)
    assert reloaded.settings.pre_roll_s == pytest.approx(3.0)


def test_corrupt_config_falls_back_to_defaults(tmp_path: Path):
    """Monitoring with defaults beats refusing to start."""
    path = tmp_path / "config.json"
    path.write_text("{ this is not json")
    assert ConfigStore(path).settings.sensitivity == Settings().sensitivity
