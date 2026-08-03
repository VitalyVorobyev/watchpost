# ADR-0005: Python host, standalone-runnable, with Tauri as supervisor

**Status:** Accepted
**Date:** 2026-08-03

## Context

Two decisions were entangled and needed separating: what language the host is written in, and
what owns the desktop application lifecycle.

For the host, Rust would match the rest of this developer's projects, but every capability the
MVP needs — HTTP, SSE, SQLite, JPEG encoding, array maths, subprocess supervision — is faster to
assemble correctly in Python, and the heavy lifting (capture and encoding) happens in `ffmpeg`
either way. Time-to-working-MVP was the deciding factor.

For the shell, the product requires a Mac presence: preview, pairing information, sleep
prevention, and a proper application identity. Tauri v2 provides that.

The interaction between them is the interesting part. On macOS, camera permission (TCC) is
granted to the **responsible process**. When the server runs from a terminal, the terminal holds
the grant. When the server is a child of a Tauri app, the app holds it — and the app must declare
`NSCameraUsageDescription` or the request is denied without a prompt.

## Decision

- The host is Python 3.13 with FastAPI, NumPy, and Pillow, managed by `uv`.
- **The server is a standalone process.** `uv run watchpost serve` must fully work from a
  terminal, serving both the phone client and the Mac layout.
- **Tauri supervises the server; it does not contain it.** The Rust side spawns the server as a
  child, waits for `/healthz`, opens a window at `http://127.0.0.1:8787/host`, and terminates the
  child on exit.
- `src-tauri/Info.plist` declares `NSCameraUsageDescription`.
- Sleep prevention (`caffeinate`) is owned by the **server**, not the shell, so it works in both
  modes.

## Consequences

- If the Tauri shell breaks — permission trouble, a toolchain change, a signing problem — the
  product still works from a terminal and the phone client is entirely unaffected. This is the
  main reason for the split.
- The host is testable headlessly, with no GUI and no webview.
- The cost is two runtimes and two package managers in one repository, and a process boundary
  that must be supervised on both sides.
- Camera permission is granted twice over the product's life: once to the terminal during
  development, once to the app bundle. Users see the prompt again after switching modes, which
  needs explaining in the README.
- Packaging is not solved by this ADR: shipping a self-contained app requires freezing the Python
  runtime into a sidecar binary. Deferred to Phase 2.
