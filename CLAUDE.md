# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project overview

Watchpost is a local-first camera monitor: a MacBook captures a USB camera, detects motion,
records event clips, and serves a phone-friendly web UI over the LAN. No cloud, no accounts, no
external services.

**Read [`docs/design.md`](docs/design.md) before making architectural changes.** It is the single
source of truth for scope, states, architecture, data model, API contract, security, and UX.

| Document | Purpose |
|---|---|
| `docs/design.md` | What the system is and how it is built |
| `docs/roadmap.md` | Phases, exit conditions, current status |
| `docs/backlog.md` | Ranked concrete tasks, known gaps, open questions |
| `docs/adrs/` | Decisions that materially constrain later work |

## Architecture in one paragraph

One `ffmpeg` process owns the camera and fans out to two branches: a raw RGB pipe that Python
reads for motion detection and live preview, and a continuous H.264 segment ring on disk. When
motion triggers, the recorder concatenates the ring segments covering the event window into an
MP4 by stream copy — no re-encode. A FastAPI server exposes REST plus SSE and serves a React
client used by both the phone and the Mac window. A Tauri v2 shell supervises the server process
but does not contain it.

## Structure

```
server/       Python host — must run standalone, without Tauri
web/          React 19 + Vite + TypeScript client (phone layout + /host layout)
src-tauri/    Tauri v2 shell that supervises the server
docs/         design.md, roadmap.md, backlog.md, adrs/
```

## Build and run

```bash
# Server (from server/)
uv sync                                    # install dependencies
uv run watchpost serve                     # 0.0.0.0:8787
uv run watchpost serve --port 9000         # alternative port
uv run pytest                              # tests
uv run ruff check . && uv run ruff format . # lint and format

# Web (from web/)
bun install
bun run dev                                # Vite dev server, proxies /api to :8787
bun run build                              # emits web/dist, served by the host
bun run typecheck                          # tsc
bun run test                               # vitest

# Desktop shell (from src-tauri/)
cargo tauri dev
cargo fmt --check && cargo clippy --all-targets -- -D warnings
```

CI (`.github/workflows/ci.yml`) runs exactly these, plus a macOS end-to-end job that boots the
host without a camera and asserts it serves the client and rejects unauthenticated requests.
Run the same checks locally before pushing.

Lockfiles (`server/uv.lock`, `web/bun.lock`, `src-tauri/Cargo.lock`) are committed and CI
installs with `--frozen-lockfile` / `--locked`. Update them deliberately, not incidentally.

**Port 8787, not 8765** — 8765 is taken by another project on this machine.

Prerequisite: `brew install ffmpeg` (bundling it is Phase 2 work).

## Runtime data

Everything mutable lives outside the repository, under
`~/Library/Application Support/Watchpost/`: `watchpost.db`, `config.json`, `token` (0600),
`clips/`, `thumbs/`, `ring/`, `logs/`. Never commit any of it. The `ring/` directory churns
constantly and must not be backed up or synced.

## Rules

**Documentation.** Do not silently contradict a document in code. If the code needs to diverge,
update `docs/design.md` in the same change, and add an ADR when the decision constrains later
work. Tick completed backlog items and update the matching `roadmap.md` row.

**Architecture.**

- The server must work when launched from a terminal. Tauri supervises it; it never contains it.
- One authoritative state model in `state.py`. Interfaces observe it; they never infer state.
- `capture` (intent) and `camera` (device health) are separate axes. Check `capture` first
  when rendering, or a deliberately switched-off camera reports as a fault
  ([ADR-0010](docs/adrs/0010-capture-intent-and-shutdown.md)).
- Shutdown is loopback-only. Do not expose it to the phone: a device that can stop the host
  can lock itself out of it.
- TLS is self-signed and off by default. iOS silently rejects a server certificate over 398 days,
  without a SAN, with an IP in a dNSName, or without `serverAuth` — `tls.py` encodes all four and
  `test_tls.py` asserts them ([ADR-0011](docs/adrs/0011-self-signed-tls.md)). Never regenerate the
  CA; only the leaf is reissued.
- Keep capture, detection, recording, storage, and API concerns separate.
- Keep the detector replaceable — the recorder consumes `Detection`, nothing more
  ([ADR-0007](docs/adrs/0007-detector-interface.md)).
- Do not build abstractions for multiple cameras, users, or cloud deployment. They are non-goals.
- Offline, reconnecting, camera-failure, and low-storage are normal product states, not errors.

**Platform gotchas that will bite** (all in
[ADR-0009](docs/adrs/0009-ios-platform-constraints.md)):

- Clip serving **must** implement HTTP Range and return `206`, or iOS `<video>` silently fails.
  Starlette's `FileResponse` does not do this.
- Never select a camera by AVFoundation index — it reorders when a phone appears
  ([ADR-0004](docs/adrs/0004-camera-identity.md)). Resolve `(name, uid)` at every open.
- Request the device's *exact* advertised frame rate. UVC cameras advertise rationals such as
  `30.000030` and answer a request for `30` with "Configuration of video device failed", after
  which capture yields nothing. Use `camera.resolve_mode()`; never format the rate yourself.
- Do not pin `-pixel_format`. The supported set varies per device and connection speed, and
  ffmpeg negotiates a working one. Pinning `nv12` broke the development camera.
- A pipe returns at most 64 KB per syscall, so a ~390 KB frame always arrives in pieces. Read
  frames with `capture._fill()`; a bare `read(n)` looks like EOF and kills capture.
- `<img>` and `<video>` cannot set headers, so media endpoints also accept `?t=<token>`.
- No Service Worker over LAN HTTP. Do not write offline-caching code; it will not run.
- An installed home-screen app gets its **own** `localStorage`. The pairing token must arrive in
  the launch URL: `/manifest.webmanifest` serves a `start_url` carrying a verified `?t=`, and the
  client only strips `?t=` from the address bar once `isStandalone()`. Strip it in a tab and
  Add-to-Home-Screen installs a permanently unauthenticated app.
- Continuity Camera leaves the AVFoundation device list with the phone. Never offer only attached
  devices: remembered-but-absent cameras stay selectable (`camera_options()`).
- A closed lid stops capture regardless of `caffeinate`.

**Code.** Small, testable modules with explicit interfaces. Pure logic — detector, state machine,
segment selection, retention — stays free of I/O so it can be tested without a camera. Type hints
throughout the server; no `any` in the client.

## Verification

The MVP gate is the phone, not the terminal: from an iPhone on the same Wi-Fi, open the paired
URL, arm monitoring, trigger motion, and play the resulting clip inline in Safari.

```bash
# Camera enumeration
ffmpeg -f avfoundation -list_devices true -i ""

# Range support — must print 206 with a Content-Range header
curl -s -D - -o /dev/null -H "Range: bytes=0-1023" \
  "http://127.0.0.1:8787/api/v1/clips/<id>.mp4?t=<token>"

# Clip sanity
ffprobe -v error -show_entries format=duration -show_streams <clip>.mp4
```
