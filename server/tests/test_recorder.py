"""The event state machine and segment-window arithmetic."""

from __future__ import annotations

from pathlib import Path

import pytest

from watchpost.capture import Segment, prune_ring, select_segments
from watchpost.recorder import EventRecorder, Phase


def recorder(**overrides) -> EventRecorder:
    options = {"post_roll_s": 5.0, "cooldown_s": 3.0, "max_clip_s": 60.0}
    options.update(overrides)
    return EventRecorder(**options)


def quiet(rec: EventRecorder, t: float):
    return rec.update(active=False, score=0.0, label="motion", t=t)


def motion(rec: EventRecorder, t: float, score: float = 0.2):
    return rec.update(active=True, score=score, label="motion", t=t)


# -- state machine --------------------------------------------------------


def test_idle_until_motion():
    rec = recorder()
    assert quiet(rec, 0.0).phase is Phase.IDLE
    assert rec.active is None


def test_motion_starts_an_event():
    rec = recorder()
    transition = motion(rec, 10.0)
    assert transition.phase is Phase.RECORDING
    assert transition.started is not None
    assert transition.started.started_at == 10.0


def test_continued_motion_extends_the_window():
    rec = recorder(post_roll_s=5.0)
    motion(rec, 0.0)
    for t in (2.0, 4.0, 6.0, 8.0):
        assert motion(rec, t).phase is Phase.RECORDING
    # Post-roll is measured from the last motion, not from the start.
    assert quiet(rec, 12.0).phase is Phase.RECORDING
    assert quiet(rec, 13.1).finished is not None


def test_post_roll_expiry_finishes_the_event():
    rec = recorder(post_roll_s=5.0)
    motion(rec, 0.0)
    assert quiet(rec, 4.9).phase is Phase.RECORDING
    transition = quiet(rec, 5.0)
    assert transition.finished is not None
    assert transition.finished.started_at == 0.0
    assert transition.phase is Phase.COOLDOWN


def test_max_clip_caps_continuous_motion():
    """A disturbance that never stops must still produce a finite clip."""
    rec = recorder(max_clip_s=10.0, post_roll_s=5.0)
    motion(rec, 0.0)
    for t in range(1, 10):
        assert motion(rec, float(t)).finished is None
    transition = motion(rec, 10.0)
    assert transition.finished is not None


def test_cooldown_suppresses_immediate_retrigger():
    """One continuous disturbance should make one event, not a flood."""
    rec = recorder(post_roll_s=2.0, cooldown_s=10.0)
    motion(rec, 0.0)
    assert quiet(rec, 2.0).finished is not None

    for t in (3.0, 5.0, 9.0):
        assert motion(rec, t).started is None, f"retriggered during cooldown at {t}"

    assert motion(rec, 12.1).started is not None


def test_peak_score_is_the_maximum_seen():
    rec = recorder(post_roll_s=2.0)
    motion(rec, 0.0, score=0.1)
    motion(rec, 0.5, score=0.7)
    motion(rec, 1.0, score=0.3)
    transition = quiet(rec, 3.1)
    assert transition.finished is not None
    assert transition.finished.peak_score == pytest.approx(0.7)


def test_reset_abandons_an_active_event():
    rec = recorder()
    motion(rec, 0.0)
    rec.reset()
    assert rec.phase is Phase.IDLE
    assert rec.active is None


# -- segment selection ----------------------------------------------------


def segments(*starts: float) -> list[Segment]:
    return [Segment(Path(f"/ring/{int(s)}.ts"), s) for s in starts]


def test_select_segments_covers_the_whole_window():
    ring = segments(0, 2, 4, 6, 8, 10)
    chosen = select_segments(ring, 3.0, 7.0)
    assert [s.start for s in chosen] == [2, 4, 6]


def test_select_segments_includes_the_one_containing_the_start():
    """Pre-roll is the point; a window starting mid-segment must include that segment."""
    ring = segments(0, 2, 4)
    assert [s.start for s in select_segments(ring, 1.5, 2.5)] == [0, 2]


def test_select_segments_includes_the_final_open_segment():
    ring = segments(0, 2, 4)
    assert [s.start for s in select_segments(ring, 4.5, 5.5)] == [4]


def test_select_segments_empty_cases():
    assert select_segments([], 0.0, 10.0) == []
    assert select_segments(segments(0, 2), 10.0, 5.0) == []
    assert select_segments(segments(10, 12), 0.0, 5.0) == []


# -- ring pruning ---------------------------------------------------------


def test_prune_ring_keeps_recent_and_the_open_segment(tmp_path: Path):
    import time

    base = time.time() - 100
    names = []
    for offset in range(0, 100, 2):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(base + offset))
        path = tmp_path / f"{stamp}.ts"
        path.write_bytes(b"x")
        names.append(path)

    remaining_before = len(list(tmp_path.glob("*.ts")))
    removed = prune_ring(tmp_path, base + 50)
    remaining = sorted(p.name for p in tmp_path.glob("*.ts"))

    assert removed > 0
    assert len(remaining) == remaining_before - removed
    # The newest segment survives regardless: ffmpeg is still writing to it.
    assert names[-1].exists()


def test_prune_ring_with_floor_in_the_past_removes_nothing(tmp_path: Path):
    import time

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    (tmp_path / f"{stamp}.ts").write_bytes(b"x")
    assert prune_ring(tmp_path, 0.0) == 0
