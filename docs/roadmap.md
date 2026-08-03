# Watchpost — Roadmap

Phases, exit conditions, and current status. Concrete tasks live in [`backlog.md`](backlog.md);
the system being built is described in [`design.md`](design.md).

**Status legend:** ✅ done · 🚧 in progress · ⬜ not started

---

## Phase 0 — Technical validation

**Goal:** prove the critical runtime path before building product surface.

| | Deliverable |
|---|---|
| ✅ | Open the target USB camera on macOS via AVFoundation |
| ✅ | Capture and hardware-encode H.264 reliably at real time |
| ✅ | Run motion detection on the live frame stream |
| ✅ | Save a playable event clip with correct pre-roll |
| ✅ | Expose a minimal local status endpoint |
| ✅ | Verify access from an iPhone on the same network |

**Exit condition:** one end-to-end event can be detected, recorded, and opened from the phone.

**Status (2026-08-03):** met. The pipeline is verified end to end on a Logitech StreamCam —
motion produces a playable 1280x720 H.264 clip with correct pre-roll, Range requests return
`206`, and a clip reaches `readyState 4` in a real browser. Confirmed from a physical iPhone
and iPad on the LAN.

---

## Phase 1 — Functional MVP

**Goal:** the complete core workflow, usable daily.

| | Deliverable |
|---|---|
| ✅ | Camera enumeration, selection by stable identity, health reporting |
| ✅ | Arm and disarm from both the Mac and the phone |
| ✅ | Motion-triggered recording with pre-roll and post-roll |
| ✅ | Event metadata, thumbnails, and retention |
| ✅ | Token authentication and QR pairing |
| ✅ | Live status over SSE, consistent across interfaces |
| ✅ | Responsive phone interface with live preview |
| ✅ | Recent event list and in-browser clip playback |
| ✅ | Settings and visible error handling |
| ✅ | Tauri desktop shell with sleep prevention |

**Exit condition:** the application can be used daily with one Mac, one camera, and one phone.

---

## Phase 2 — Product quality

**Goal:** make the MVP robust and pleasant.

- Polished visual pass; complete empty, loading, offline, and error states.
- Camera recovery after disconnect, verified under real unplug/replug.
- Behaviour across sleep and wake, and across network changes.
- Low-storage handling with user-visible warnings before failure.
- Startup configuration and first-run experience.
- Diagnostics view and structured logs.
- Bundle `ffmpeg` as a Tauri sidecar so Homebrew is not a prerequisite.
- Signed and notarised app bundle; login-item startup.
- ~~**TLS on the LAN**~~ — done ahead of schedule with a self-signed CA and a guided per-device
  enrolment flow ([ADR-0011](adrs/0011-self-signed-tls.md)). Off by default. This unblocks
  Service Workers and Web Push on iOS, which Phase 3 notifications depended on.
- Installation and usage documentation.
- Automated tests over the camera-in-the-loop path, not just pure logic.
- A release workflow that builds and publishes a signed `.dmg` on tag.

**Exit condition:** normal failures can be understood and recovered without developer intervention.

---

## Phase 3 — Smarter events

**Goal:** improve event relevance without destabilising the reliable motion path.

- Person detection behind the existing `Detector` interface
  ([ADR-0007](adrs/0007-detector-interface.md)).
- Configurable detection zones and ignore masks.
- Event deduplication and merging.
- Richer thumbnails and event summaries.
- Scheduled arming.
- Notifications — no longer blocked: TLS landed in [ADR-0011](adrs/0011-self-signed-tls.md), so
  a secure origin is available. Still requires an installed PWA and a device that has trusted the
  CA.

Any work in this phase must leave the motion-recording path working unchanged.

---

## Deferred indefinitely

Public-internet access, cloud relay, native mobile applications, multiple users, multiple
cameras, advanced identity recognition, audio capture.
