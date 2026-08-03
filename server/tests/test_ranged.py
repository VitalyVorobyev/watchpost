"""HTTP Range parsing.

iOS Safari will not play a clip served with 200 and a full body, and it reports no error
when that happens — so this is a correctness requirement with a test, not an optimisation.
See ADR-0009.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from watchpost.auth import TokenStore
from watchpost.ranged import parse_range, ranged_file_response

SIZE = 1000


def test_no_header_means_no_range():
    assert parse_range(None, SIZE) is None
    assert parse_range("", SIZE) is None


def test_unparseable_header_is_ignored():
    assert parse_range("bytes=abc", SIZE) is None
    assert parse_range("items=0-10", SIZE) is None
    assert parse_range("bytes=-", SIZE) is None


def test_closed_range():
    assert parse_range("bytes=0-499", SIZE) == (0, 499)
    assert parse_range("bytes=100-199", SIZE) == (100, 199)


def test_open_ended_range_runs_to_the_end():
    assert parse_range("bytes=500-", SIZE) == (500, 999)


def test_suffix_range_counts_back_from_the_end():
    assert parse_range("bytes=-500", SIZE) == (500, 999)


def test_suffix_longer_than_the_file_clamps_to_the_whole_file():
    assert parse_range("bytes=-5000", SIZE) == (0, 999)


def test_end_beyond_the_file_is_clamped():
    assert parse_range("bytes=900-99999", SIZE) == (900, 999)


def test_start_beyond_the_file_is_unsatisfiable():
    with pytest.raises(ValueError):
        parse_range("bytes=1000-", SIZE)
    with pytest.raises(ValueError):
        parse_range("bytes=5000-6000", SIZE)


def test_inverted_range_is_unsatisfiable():
    with pytest.raises(ValueError):
        parse_range("bytes=500-100", SIZE)


def test_zero_length_suffix_is_unsatisfiable():
    with pytest.raises(ValueError):
        parse_range("bytes=-0", SIZE)


def test_whitespace_is_tolerated():
    assert parse_range("  bytes=0-99  ", SIZE) == (0, 99)


def test_response_status_and_headers(tmp_path: Path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\0" * SIZE)

    full = ranged_file_response(path, None, "video/mp4")
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"

    partial = ranged_file_response(path, "bytes=0-99", "video/mp4")
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 0-99/{SIZE}"
    assert partial.headers["content-length"] == "100"

    bad = ranged_file_response(path, "bytes=99999-", "video/mp4")
    assert bad.status_code == 416
    assert bad.headers["content-range"] == f"bytes */{SIZE}"


# -- token ----------------------------------------------------------------


def test_token_is_created_with_owner_only_permissions(tmp_path: Path):
    path = tmp_path / "token"
    store = TokenStore(path)

    assert path.exists()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert len(store.token) >= 32


def test_token_persists_across_instances(tmp_path: Path):
    path = tmp_path / "token"
    first = TokenStore(path).token
    assert TokenStore(path).token == first


def test_token_verification(tmp_path: Path):
    store = TokenStore(tmp_path / "token")
    assert store.verify(store.token) is True
    assert store.verify("wrong") is False
    assert store.verify(None) is False
    assert store.verify("") is False
