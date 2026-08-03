"""The local HTTP API.

REST for commands, settings, events, and media; SSE for live state. Everything except
``/healthz`` requires the pairing token. See docs/design.md section 7 for the contract.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .app import Application
from .ranged import ranged_file_response

log = logging.getLogger(__name__)

MJPEG_BOUNDARY = "watchpostframe"
SSE_KEEPALIVE_S = 15.0


def _extract_token(request: Request) -> str | None:
    """Token from the Authorization header, or from ``?t=`` for media elements.

    ``<img>`` and ``<video>`` cannot set request headers, so media URLs must carry the
    token in the query string. See ADR-0006 for the logging consequences.
    """
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.query_params.get("t")


def create_app(application: Application, web_dist: Path | None = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        application.start(asyncio.get_running_loop())
        try:
            yield
        finally:
            application.shutdown()

    api = FastAPI(title="Watchpost", version=__version__, lifespan=lifespan)

    def require_token(request: Request) -> None:
        if not application.tokens.verify(_extract_token(request)):
            raise HTTPException(status_code=401, detail="invalid or missing token")

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_token)])

    # -- state -----------------------------------------------------------

    @router.get("/state")
    def get_state() -> dict:
        return application.state.snapshot()

    @router.get("/state/stream")
    async def stream_state(request: Request) -> StreamingResponse:
        queue = application.state.subscribe()

        async def events() -> AsyncIterator[bytes]:
            try:
                snapshot = {"type": "state", "state": application.state.snapshot()}
                yield f"data: {json.dumps(snapshot)}\n\n".encode()
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_S)
                    except TimeoutError:
                        # Comment frame: keeps proxies and iOS from closing an idle stream.
                        yield b": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(message)}\n\n".encode()
            finally:
                application.state.unsubscribe(queue)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    # -- commands --------------------------------------------------------

    @router.post("/command/arm")
    def arm() -> dict:
        application.arm()
        return application.state.snapshot()

    @router.post("/command/disarm")
    def disarm() -> dict:
        application.disarm()
        return application.state.snapshot()

    @router.post("/command/camera/{action}")
    def set_camera(action: str) -> dict:
        """Open or release the camera. Not the same as arming — see `Application.set_capture`."""
        if action not in ("on", "off"):
            raise HTTPException(status_code=404, detail="expected 'on' or 'off'")
        application.set_capture(action == "on")
        return application.state.snapshot()

    @router.post("/command/shutdown")
    async def shutdown(request: Request) -> dict:
        """Stop the host process.

        Restricted to loopback on purpose. A device that can shut the host down can lock
        itself out of it — from the phone there would be no way back short of walking to
        the Mac. `/host` is only a route, reachable from any paired device, so hiding the
        control in the client is cosmetic; this check is what actually enforces it.
        """
        client = request.client.host if request.client else None
        if client not in ("127.0.0.1", "::1"):
            raise HTTPException(
                status_code=403, detail="Watchpost can only be shut down from the Mac itself"
            )

        # Reply first: SIGTERM reaches uvicorn's own handler, which unwinds the lifespan
        # and so calls Application.shutdown() — the same clean path as Ctrl-C.
        loop = asyncio.get_running_loop()
        loop.call_later(0.25, lambda: os.kill(os.getpid(), signal.SIGTERM))
        log.info("shutdown requested from %s", client)
        return {"ok": True}

    # -- events ----------------------------------------------------------

    @router.get("/events")
    def list_events(
        limit: int = Query(default=50, ge=1, le=200),
        before: float | None = Query(default=None),
    ) -> dict:
        events = application.store.list(limit=limit, before=before)
        return {"events": [event.to_dict() for event in events]}

    @router.get("/events/{event_id}")
    def get_event(event_id: str) -> dict:
        event = application.store.get(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        newer, older = application.store.neighbours(event_id)
        return {"event": event.to_dict(), "newer_id": newer, "older_id": older}

    @router.post("/events/{event_id}/viewed")
    def mark_viewed(event_id: str) -> dict:
        if not application.store.mark_viewed(event_id):
            raise HTTPException(status_code=404, detail="event not found")
        return {"ok": True}

    @router.delete("/events/{event_id}")
    def delete_event(event_id: str) -> dict:
        if not application.store.delete(event_id):
            raise HTTPException(status_code=404, detail="event not found")
        application._refresh_storage()
        return {"ok": True}

    # -- media -----------------------------------------------------------

    @router.get("/clips/{event_id}.mp4")
    def get_clip(event_id: str, request: Request) -> Response:
        event = application.store.get(event_id)
        if event is None or not event.clip_path:
            raise HTTPException(status_code=404, detail="clip not found")
        path = application.paths.root / event.clip_path
        if not path.exists():
            raise HTTPException(status_code=404, detail="clip file is missing")
        return ranged_file_response(
            path,
            request.headers.get("range"),
            media_type="video/mp4",
            filename=f"{event_id}.mp4",
        )

    @router.get("/thumbs/{event_id}.jpg")
    def get_thumb(event_id: str) -> Response:
        event = application.store.get(event_id)
        if event is None or not event.thumb_path:
            raise HTTPException(status_code=404, detail="thumbnail not found")
        path = application.paths.root / event.thumb_path
        if not path.exists():
            raise HTTPException(status_code=404, detail="thumbnail file is missing")
        return FileResponse(path, media_type="image/jpeg")

    @router.get("/snapshot.jpg")
    def snapshot() -> Response:
        jpeg = application.preview.latest_jpeg()
        if jpeg is None:
            raise HTTPException(status_code=503, detail="no frame available")
        return Response(jpeg, media_type="image/jpeg", headers={"cache-control": "no-store"})

    @router.get("/preview.mjpeg")
    async def preview_stream(request: Request) -> StreamingResponse:
        loop = asyncio.get_running_loop()

        async def frames() -> AsyncIterator[bytes]:
            generation = -1
            while not await request.is_disconnected():
                # Encoding blocks, so it runs in a worker thread rather than on the loop.
                result = await loop.run_in_executor(
                    None, application.preview.wait_for_frame, generation, 5.0
                )
                if result is None:
                    continue
                generation, jpeg = result
                yield (
                    (
                        f"--{MJPEG_BOUNDARY}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode()
                    + jpeg
                    + b"\r\n"
                )

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )

    # -- configuration ---------------------------------------------------

    @router.get("/cameras")
    def cameras() -> dict:
        return {
            "cameras": [
                {
                    "name": option.name,
                    "uid": option.uid,
                    "selected": option.selected,
                    # False for a remembered camera that is not attached right now. It stays
                    # selectable: capture retries with backoff and picks it up on return.
                    "present": option.present,
                }
                for option in application.cameras()
            ]
        }

    @router.put("/camera")
    def select_camera(payload: dict) -> dict:
        name = payload.get("name")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        settings = application.select_camera(name, payload.get("uid"))
        return settings.model_dump()

    @router.get("/settings")
    def get_settings() -> dict:
        return application.config.settings.model_dump()

    @router.put("/settings")
    def put_settings(payload: dict) -> dict:
        try:
            return application.update_settings(payload).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/pairing")
    def pairing() -> dict:
        snapshot = application.state.snapshot()
        base = snapshot["host"]["lan_url"] or f"http://127.0.0.1:{application.port}"
        return {
            "url": f"{base}/?t={application.tokens.token}",
            "lan_url": base,
            "token": application.tokens.token,
            "tls": application.tls,
            # Where a device installs the CA before it can trust anything else. Plaintext
            # by necessity, and carries no token — see ADR-0011.
            "trust_url": (
                f"http://{urlsplit(base).hostname}:{application.port + 1}/"
                if application.tls and urlsplit(base).hostname
                else None
            ),
        }

    api.include_router(router)

    @api.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "version": __version__}

    _mount_client(api, application, web_dist)
    return api


def _mount_client(api: FastAPI, application: Application, web_dist: Path | None) -> None:
    """Serve the built web client, with SPA fallback for client-side routes."""
    if web_dist is None or not (web_dist / "index.html").exists():

        @api.get("/", response_class=HTMLResponse)
        def missing_client() -> HTMLResponse:
            return HTMLResponse(
                "<h1>Watchpost</h1>"
                "<p>The web client has not been built. Run <code>bun run build</code> "
                "in <code>web/</code>.</p>",
                status_code=200,
            )

        return

    assets = web_dist / "assets"
    if assets.is_dir():
        api.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = web_dist / "index.html"
    manifest = web_dist / "manifest.webmanifest"

    @api.get("/manifest.webmanifest")
    def webmanifest(t: str | None = None) -> Response:
        """The manifest, with a `start_url` that carries the pairing token.

        An installed iOS web app runs in its own storage container: the token Safari saved
        during pairing is invisible to it. iOS 16.4+ launches the app at `start_url`, so
        putting the token there is the only way an installed app starts authenticated.

        This route is intentionally unauthenticated — it echoes back a token the caller
        already supplied and reveals nothing otherwise. An unrecognised token is dropped
        rather than reflected, so a crafted link cannot bake a bogus one into an install.
        """
        try:
            payload = json.loads(manifest.read_text())
        except (OSError, ValueError):
            return JSONResponse({"detail": "manifest unavailable"}, status_code=404)

        if t and application.tokens.verify(t):
            payload["start_url"] = f"/?t={quote(t, safe='')}"
        return JSONResponse(payload, media_type="application/manifest+json")

    @api.get("/{path:path}", response_class=HTMLResponse)
    def spa(path: str) -> Response:
        candidate = (web_dist / path).resolve() if path else index
        # Containment check: a crafted path must not escape the dist directory.
        if path and candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, media_type="text/html")


def not_found(detail: str) -> JSONResponse:  # pragma: no cover - convenience for callers
    return JSONResponse({"detail": detail}, status_code=404)
