# Watchpost — Backlog

Ranked, concrete work. Phase framing lives in [`roadmap.md`](roadmap.md); the system is described
in [`design.md`](design.md).

**Convention:** items are `[ ]` open, `[x]` done, `[~]` in progress. Keep newest decisions at the
top of their section. When an item is done, tick it here *and* update the matching row in
`roadmap.md`.

---

## Done — Milestone B: server core

- [x] `paths.py` — storage root under `~/Library/Application Support/Watchpost/`, directory bootstrap
- [x] `config.py` — settings model, JSON persistence, validation against documented bounds
- [x] `auth.py` — token generation at mode 0600, constant-time verification, bearer + `?t=`
- [x] `camera.py` — enumerate via AVFoundation, filter virtual inputs, resolve `(name, uid)` → index
- [x] `capture.py` — ffmpeg supervisor, dual output, backoff restart, camera health publishing
- [x] `detect.py` — `Detector` protocol + `MotionDetector`
- [x] `store.py` — SQLite schema, event CRUD, retention on three bounds, ring janitor
- [x] `recorder.py` — event state machine, segment selection, concat, thumbnail
- [x] `state.py` — authoritative `AppState` + change bus for SSE fan-out
- [x] `preview.py` — latest-frame JPEG, MJPEG multipart generator
- [x] `api.py` — REST + SSE + **range-aware clip responder**
- [x] `__main__.py` — `watchpost serve --host --port`
- [x] `caffeinate` lifecycle tied to armed state

## Done — Milestone C: web client

- [x] Vite + React 19 + TS scaffold, `bun` as package manager
- [x] `styles/tokens.css` — colour, spacing, radius, type; light and dark
- [x] Typed API client + `useAppState` SSE hook with backoff reconnection
- [x] Token bootstrap from `?t=`, persist to `localStorage`, strip from the URL once installed
- [x] Home: status, arm/disarm, preview, latest event, storage summary
- [x] Events list: thumbnails, grouping by day, viewed state, empty state
- [x] Event detail: playback, metadata, download, delete with confirmation
- [x] Settings: sensitivity, pre/post-roll, cooldown, retention, camera selection
- [x] Host layout: preview, pairing QR, LAN address, storage, errors, lid-open notice
- [x] Offline / reconnecting / loading / empty / error states throughout
- [x] `manifest.webmanifest` + icons for Add-to-Home-Screen

## Done — Milestone D: iPhone verification

Verified on a physical iPhone and iPad, 2026-08-03. Three defects only a real device exposed;
all three are fixed and recorded in [ADR-0009](adrs/0009-ios-platform-constraints.md).

- [x] Bind `0.0.0.0`, confirm reachability from the phone
- [x] QR pairing round trip
- [x] Live state and preview on the phone
- [x] Clip playback in Safari (proves Range → `206`)
- [x] Add-to-Home-Screen

## Done — Milestone G: camera and process controls

- [x] `capture` intent axis in `state.py`, separate from `camera` health
- [x] Switch the camera on/off from the phone and the host; persisted across restarts
- [x] Arming implies capture on; switching capture off disarms
- [x] Loopback-only `POST /command/shutdown`, with a confirmation step in the host layout
- [x] Tauri shell exits when its server child does

## Done — Milestone E: Tauri shell

- [x] `src-tauri` scaffold, Tauri v2
- [x] Spawn and supervise the server child; kill on exit
- [x] `Info.plist` with `NSCameraUsageDescription`
- [x] Window at `127.0.0.1:8787/host`; verify the camera prompt appears

## Done — Milestone F: tests

- [x] `MotionDetector`: static scene, moving block, illumination ramp, warm-up
- [x] Event state machine: trigger, extend, post-roll expiry, max-duration cap, cooldown
- [x] Segment selection: window arithmetic against a synthetic ring directory
- [x] Retention: each of the three bounds independently and combined
- [x] Range responder: full, partial, suffix, and unsatisfiable ranges

---

## Known device behaviour worth remembering

- **UVC cameras want exact rational frame rates.** The StreamCam advertises `30.000030` fps and
  rejects a request for `30` with "Configuration of video device failed", after which capture
  silently produces nothing. `camera.resolve_mode()` snaps to an advertised mode and echoes the
  rate back verbatim.
- **Advertised rates are not promises.** The same camera advertises 1280x720@30 but delivers
  about 10 fps uncompressed, because raw 720p30 exceeds the USB bandwidth available to it.
  640x480 sustains 30. Clip assembly is unaffected because keyframes are forced on a time
  interval, not a frame count.
- **`-pixel_format` is best left unset.** The supported set varies per device and connection
  speed; pinning `nv12` broke the StreamCam while working on the built-in camera.

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
- [ ] Release workflow: build and publish a signed `.dmg` on tag
- [ ] Measure and report the *achieved* frame rate, not just the negotiated one

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
- ~~**Ring janitor vs. long events.**~~ Closed. An in-flight event now pins a floor on ring
  pruning (`Application._ring_floor`) for its whole life, and `build_clip` logs a warning when
  the assembled span is shorter than requested. This bit for real during development when
  settings were changed mid-event, producing a 2-second clip for a 58-second window.
- ~~**The host screen could not pair itself.**~~ Closed. `/host` is the screen that *draws* the
  pairing QR, so opening it without a token fell through to the pairing prompt — which told the
  user to scan a code that was never rendered. The startup banner and the Tauri shell now both
  open `/host?t=<token>`. Deliberately fixed by handing the host a token rather than by
  exempting loopback from auth, which would have let any visited web page drive the API.
- ~~**Add-to-Home-Screen installed an unauthenticated app.**~~ Closed. An installed iOS web app
  has a `localStorage` separate from Safari's, so the token saved during pairing was invisible to
  it, and the client had already stripped `?t=` from the URL that Add-to-Home-Screen captures.
  The manifest is now served with a token-bearing `start_url`, and the token stays in the address
  bar until the app runs standalone.
- ~~**Continuity Camera could not be re-selected.**~~ Closed. The iPhone leaves the AVFoundation
  device list when it goes away, and the picker offered only attached devices, so the entry
  vanished permanently. Seen cameras are remembered and stay selectable while absent.
- **Disarmed still costs disk writes.** The ring is written whenever capture is on, about
  0.5 MB/s — roughly 43 GB/day — regardless of armed state. Switching the camera off stops it
  ([ADR-0010](adrs/0010-capture-intent-and-shutdown.md)), but a disarmed-and-on host still pays.
  Worth revisiting whether the ring should pause while disarmed; the cost is losing pre-roll for
  the first seconds after arming.
- **Multiple clients on `/preview.mjpeg`.** Each connection gets its own JPEG encode. Fine for
  two clients; needs a shared encoder if it grows.
