# Watchpost — Backlog

Ranked, concrete work. Phase framing lives in [`roadmap.md`](roadmap.md); the system is described
in [`design.md`](design.md).

**Convention:** items are `[ ]` open, `[x]` done, `[~]` in progress. Keep newest decisions at the
top of their section. When an item is done, tick it here *and* update the matching row in
`roadmap.md`.

---

## Now — Milestone B: server core

- [ ] `paths.py` — storage root under `~/Library/Application Support/Watchpost/`, directory bootstrap
- [ ] `config.py` — settings model, JSON persistence, validation against documented bounds
- [ ] `auth.py` — token generation at mode 0600, constant-time verification, bearer + `?t=`
- [ ] `camera.py` — enumerate via AVFoundation, filter virtual inputs, resolve `(name, uid)` → index
- [ ] `capture.py` — ffmpeg supervisor, dual output, backoff restart, camera health publishing
- [ ] `detect.py` — `Detector` protocol + `MotionDetector`
- [ ] `store.py` — SQLite schema, event CRUD, retention on three bounds, ring janitor
- [ ] `recorder.py` — event state machine, segment selection, concat, thumbnail
- [ ] `state.py` — authoritative `AppState` + change bus for SSE fan-out
- [ ] `preview.py` — latest-frame JPEG, MJPEG multipart generator
- [ ] `api.py` — REST + SSE + **range-aware clip responder**
- [ ] `__main__.py` — `watchpost serve --host --port`
- [ ] `caffeinate` lifecycle tied to armed state

## Next — Milestone C: web client

- [ ] Vite + React 19 + TS scaffold, `bun` as package manager
- [ ] `styles/tokens.css` — colour, spacing, radius, type; light and dark
- [ ] Typed API client + `useAppState` SSE hook with backoff reconnection
- [ ] Token bootstrap from `?t=`, persist to `localStorage`, strip from the URL
- [ ] Home: status, arm/disarm, preview, latest event, storage summary
- [ ] Events list: thumbnails, grouping by day, viewed state, empty state
- [ ] Event detail: playback, metadata, download, delete with confirmation
- [ ] Settings: sensitivity, pre/post-roll, cooldown, retention, camera selection
- [ ] Host layout: preview, pairing QR, LAN address, storage, errors, lid-open notice
- [ ] Offline / reconnecting / loading / empty / error states throughout
- [ ] `manifest.webmanifest` + icons for Add-to-Home-Screen

## Next — Milestone D: iPhone verification

- [ ] Bind `0.0.0.0`, confirm reachability from the phone
- [ ] QR pairing round trip
- [ ] Live state and preview on the phone
- [ ] Clip playback in Safari (proves Range → `206`)
- [ ] Add-to-Home-Screen

## Next — Milestone E: Tauri shell

- [ ] `src-tauri` scaffold, Tauri v2
- [ ] Spawn and supervise the server child; kill on exit
- [ ] `Info.plist` with `NSCameraUsageDescription`
- [ ] Window at `127.0.0.1:8787/host`; verify the camera prompt appears

## Next — Milestone F: tests

- [ ] `MotionDetector`: static scene, moving block, illumination ramp, warm-up
- [ ] Event state machine: trigger, extend, post-roll expiry, max-duration cap, cooldown
- [ ] Segment selection: window arithmetic against a synthetic ring directory
- [ ] Retention: each of the three bounds independently and combined
- [ ] Range responder: full, partial, suffix, and unsatisfiable ranges

---

## Phase 2 — deferred, in priority order

- [ ] **TLS on the LAN.** Unblocks Service Workers and Web Push. Prerequisite for notifications.
- [ ] Bundle `ffmpeg` as a Tauri sidecar so Homebrew stops being a prerequisite
- [ ] Freeze the Python runtime into a sidecar binary; ship a real `.app`
- [ ] Sign and notarise; login-item startup
- [ ] Camera-in-the-loop tests (unplug/replug, sleep/wake, disk-full)
- [ ] Low-storage handling with warnings ahead of failure
- [ ] Structured logs + a diagnostics view in the host layout
- [ ] First-run configuration flow
- [ ] Clip export and share sheet
- [ ] Per-device tokens with individual revocation

## Phase 3 — deferred

- [ ] Person detection behind the existing `Detector` protocol
- [ ] Detection zones and ignore masks
- [ ] Event deduplication and merging
- [ ] Scheduled arming
- [ ] Notifications *(blocked on TLS)*

---

## Known gaps and open questions

- **Segment-grid quantisation.** Clips can start up to 2 s earlier than requested
  ([ADR-0003](adrs/0003-segment-ring-preroll.md)). Revisit the segment duration once real clips
  have been watched.
- **Detector tuning is unvalidated.** Default `sensitivity` and `min_area` are guesses until they
  have run against a real scene for a day. Expect to change them.
- **Timezone rendering.** Timestamps are stored UTC and rendered in the browser's zone. A phone
  in a different timezone from the Mac shows shifted times. Probably correct, but undecided.
- **Ring janitor vs. long events.** An event longer than the ring's retention window would lose
  its own tail. `max_clip_s` (120 s) is well under the ring window, but the interaction is not
  yet enforced by an assertion.
- **Multiple clients on `/preview.mjpeg`.** Each connection gets its own JPEG encode. Fine for
  two clients; needs a shared encoder if it grows.
