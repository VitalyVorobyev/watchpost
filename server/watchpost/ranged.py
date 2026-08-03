"""HTTP Range support for clip playback.

iOS Safari issues a Range request for ``<video>`` and expects ``206 Partial Content`` with
a correct ``Content-Range``. Answering ``200`` with the whole body produces a video element
that never plays and logs nothing. Starlette's ``FileResponse`` does not implement Range,
so this module does. See ADR-0009.
"""

from __future__ import annotations

import re
from pathlib import Path

from starlette.responses import FileResponse, Response, StreamingResponse

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK_SIZE = 256 * 1024


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Parse a single-range header into inclusive ``(start, end)`` byte offsets.

    Returns None when there is no range to honour, and raises :class:`ValueError` when the
    range is syntactically valid but unsatisfiable, which must become a 416.

    Multi-range requests are deliberately not supported: browsers do not use them for
    media, and answering with the first range is a correct and much simpler response.
    """
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if not match:
        return None

    raw_start, raw_end = match.group(1), match.group(2)
    if raw_start == "" and raw_end == "":
        return None

    if raw_start == "":
        # Suffix form: "bytes=-500" means the final 500 bytes.
        length = int(raw_end)
        if length <= 0:
            raise ValueError("unsatisfiable suffix range")
        start = max(size - length, 0)
        end = size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
        if start >= size:
            raise ValueError("range start beyond end of file")
        end = min(end, size - 1)

    if start > end:
        raise ValueError("inverted range")
    return start, end


def _iter_file(path: Path, start: int, end: int):
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def ranged_file_response(
    path: Path, range_header: str | None, media_type: str, filename: str | None = None
) -> Response:
    """Serve a file, honouring a Range header when present."""
    size = path.stat().st_size
    headers = {"accept-ranges": "bytes"}
    if filename:
        headers["content-disposition"] = f'inline; filename="{filename}"'

    try:
        span = parse_range(range_header, size)
    except ValueError:
        return Response(
            status_code=416,
            headers={"content-range": f"bytes */{size}", "accept-ranges": "bytes"},
        )

    if span is None:
        return FileResponse(path, media_type=media_type, headers=headers)

    start, end = span
    headers["content-range"] = f"bytes {start}-{end}/{size}"
    headers["content-length"] = str(end - start + 1)
    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers,
    )
