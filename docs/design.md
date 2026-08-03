# Watchpost — Design

**Status:** living document. This is the single source of truth for what Watchpost is, what it
does, and how it is built. Decisions that materially constrain later work are recorded in
`adrs/` and referenced from here.

Companion documents: [`roadmap.md`](roadmap.md) (phases and status),
[`backlog.md`](backlog.md) (ranked work), [`adrs/`](adrs/) (decision records).

---

## 1. Purpose

A private, local-first camera monitor that runs on a MacBook, records video when relevant events
occur, and can be checked or controlled from an iPhone.

### Problem

A user already owns a MacBook and a USB camera but does not want to deploy a cloud service, buy
dedicated surveillance hardware, or publish a mobile application through an app store. Watchpost
turns that existing hardware into a monitoring system with a polished interface and minimal setup.

### Target user

A technically capable individual monitoring a room, entrance, workspace, or temporary location.

### Core value

- Reuse existing hardware.
- Detect activity automatically.
- Retain only relevant footage.
- Access status and controls from a phone.
- Keep video and control traffic inside the local network.

### Principles

1. **Local first** — core operation must not depend on any external service.
2. **Simple but polished** — few features, clear states, strong visual quality.
3. **Observable** — the user must always know whether camera, detection, and recording are live.
4. **Reliable before intelligent** — motion-triggered recording must be solid before classification.
5. **Privacy by design** — recordings stay on the Mac unless explicitly exported.
6. **Incremental intelligence** — better detection must not require redesigning the system.

---

## 2. Scope

### In scope for the MVP

**Mac host**

- Enumerate cameras; select one by stable identity.
- Report camera availability; serve a live preview.
- Arm and disarm monitoring.
- Detect motion with a lightweight local algorithm.
- Record event clips with configurable pre-roll and post-roll.
- Store clips, thumbnails, and metadata locally; enforce retention.
- Expose a versioned local API for status, commands, events, and clips.
- Prevent display and idle sleep while armed, and report clearly when monitoring cannot continue.

**Phone client**

- Responsive web app, home-screen installable, optimised for iPhone Safari.
- Show connection, camera, monitoring, and recording status.
- Arm and disarm.
- Show the latest event and recent clips; play or download a clip.
- Clear offline, reconnecting, and error states.

### Non-goals for the MVP

- Cloud synchronisation, cloud relay, remote access over the public internet.
- Multiple cameras; multiple users or accounts.
- Facial recognition or identity tracking.
- App Store distribution; native mobile applications.
- **Audio capture.** Video only — recording audio carries consent obligations that vary by
  jurisdiction, and the MVP has no need for it.
- **Continuous *retention*.** Note the precision: Watchpost *does* encode continuously (pre-roll
  requires it), but footage outside an event window is discarded within seconds. See
  [ADR-0003](adrs/0003-segment-ring-preroll.md).
- Complex automation rules.

### Deliberately deferred

Person detection, detection zones, event categories, notifications, multiple cameras, secure
remote access, scheduled arming, home-automation integration. See [`roadmap.md`](roadmap.md).

---

## 3. Operating constraints

Physical and platform facts that shape the product. These are not bugs.

| Constraint | Consequence |
|---|---|
| **A closed lid sleeps the Mac** unless an external display *and* power are attached. `caffeinate` cannot override this. | Monitoring requires the lid open (or a clamshell setup). The Mac UI states this; the phone UI shows the host as offline. |
| **macOS camera permission (TCC) is granted to the *responsible process*.** | Running the server from a terminal grants permission to the terminal; running it under the Tauri app requires `NSCameraUsageDescription` in the app's `Info.plist`. See [ADR-0005](adrs/0005-python-host-tauri-supervisor.md). |
| **AVFoundation device indices are not stable.** Attaching an iPhone (Continuity Camera) reorders the list. | Cameras are identified by name + UniqueID and re-resolved to an index at every open. See [ADR-0004](adrs/0004-camera-identity.md). |
| **iOS Safari requires HTTP Range (`206`) for `<video>`.** | Clip serving implements Range explicitly; Starlette's `FileResponse` does not. |
| **A LAN HTTP origin is not a secure context on iOS.** | Add-to-Home-Screen works; Service Workers, offline caching, and Web Push do not. See [ADR-0009](adrs/0009-ios-platform-constraints.md). |
| **`<img>` and `<video>` cannot set request headers.** | Media endpoints accept the token as a `?t=` query parameter as well as a bearer header. |
| **USB cameras disconnect and re-enumerate.** | The capture supervisor restarts with backoff and reports camera health as product state. |
| **An installed iOS web app has its own `localStorage`,** separate from Safari's. | The pairing token has to arrive in the launch URL. The manifest's `start_url` carries it, and the client keeps `?t=` in the address bar until it is running standalone. See [ADR-0009](adrs/0009-ios-platform-constraints.md). |
| **Continuity Camera leaves the device list with the phone.** | The host remembers every camera it has seen and keeps absent ones selectable, rather than offering only what is attached. |

---

## 4. States

The host owns one authoritative state model. Every interface observes it; no interface infers
state independently.

```
capture:     on | off            (does the user want the camera open at all)
camera:      unknown | ready | disconnected | error
monitoring:  disarmed | armed
recording:   idle | recording | finalizing | cooldown
storage:     ok | warning | full
host:        starting | running | degraded
```

Client-side only:

```
connection:  connecting | live | reconnecting | offline
```

`capture` is intent; `camera` is device health. Keeping them apart is what lets an interface
say "off" rather than "disconnected" when the user switched the camera off deliberately — and
they behave differently: **disarming stops recording but leaves `ffmpeg` running**, so the
segment ring keeps churning to disk and the preview stays live. Switching capture off releases
the device. Arming implies `capture: on`; switching capture off disarms.

Composite situations the UI must distinguish — the docs call these out because they look alike
and are not:

- phone disconnected from the host;
- host running but camera unavailable;
- host armed but not recording;
- host actively recording.

### Event lifecycle

```
IDLE ──trigger──▶ RECORDING ──no motion for post_roll──▶ FINALIZING ──▶ COOLDOWN ──▶ IDLE
                    │   ▲
                    │   └── continued motion extends the window
                    └────── hard cap at max_clip_seconds, then finalize
```

`COOLDOWN` exists so that one continuous disturbance produces one event, not a flood.

---

## 5. Architecture

The MacBook is the runtime, the data owner, and the local server. The phone is a thin client.
No external backend exists.

```
                       ┌──────────────── Mac host (Python) ────────────────┐
  USB camera ──▶ ffmpeg ──┬──▶ raw RGB pipe ──▶ Detector ──▶ Recorder ──┐   │
                          │         │                                   │   │
                          │         └──▶ Preview (JPEG / MJPEG)         │   │
                          └──▶ H.264 segment ring (2 s .ts on disk) ────┘   │
                                                          │                 │
                                             Store (SQLite + clips/)        │
                                                          │                 │
                                                   AppState + bus           │
                                                          │                 │
                                              FastAPI  REST + SSE           │
                       └───────────────────────────┬───────────────────────┘
                                                   │ LAN HTTP
                        ┌──────────────────────────┴──────────────────────┐
                   iPhone Safari (phone layout)          Tauri window (/host layout)
```

### Components

**Camera service** (`camera.py`, `capture.py`) — enumerates devices, resolves the configured
camera to a current index, runs a single `ffmpeg` process, supervises and restarts it, publishes
camera health.

**Detection engine** (`detect.py`) — consumes decoded frames and emits normalised detections.
Defined by a `Detector` protocol so the algorithm is replaceable without touching the recorder.
See [ADR-0007](adrs/0007-detector-interface.md).

**Event recorder** (`recorder.py`) — owns the event state machine, selects ring segments covering
the event window, produces the final MP4, writes the thumbnail, records the event.

**Storage service** (`store.py`) — SQLite metadata, clip and thumbnail files, event queries,
retention enforcement, low-storage detection, safe deletion.

**Application state service** (`state.py`) — the authoritative runtime state plus a change bus
that fans out to SSE subscribers.

**Local API** (`api.py`) — versioned REST for commands, settings, and media; SSE for live state.

**Web client** (`web/`) — one React application with two layouts: the phone layout (default) and
the Mac host layout (`/host`). See [ADR-0008](adrs/0008-single-web-client.md).

**Mac shell** (`src-tauri/`) — supervises the server process, owns the camera permission, shows
the host window and pairing information, prevents sleep while armed.

### Capture pipeline

One `ffmpeg` process reads the camera once and feeds two branches:

```
ffmpeg -f avfoundation -framerate 30 -video_size 1280x720 -pixel_format nv12 -i <index>
  # branch 1 — detection and preview
  -map 0:v -vf "fps=10,scale=480:270" -pix_fmt rgb24 -f rawvideo pipe:1
  # branch 2 — segment ring
  -map 0:v -c:v h264_videotoolbox -b:v 4M -color_range mpeg
     -g 60 -force_key_frames "expr:gte(t,n_forced*2)"
     -f segment -segment_time 2 -segment_format mpegts -reset_timestamps 1
     -strftime 1 <ring>/%Y%m%d-%H%M%S.ts
```

Forced keyframes aligned to the segment period guarantee every segment opens on a keyframe, which
is what makes stream-copy concatenation valid. Hardware encoding via `h264_videotoolbox` keeps
the pipeline at real time with negligible CPU. See
[ADR-0002](adrs/0002-ffmpeg-avfoundation-capture.md).

### Detection algorithm (first implementation)

RGB → grayscale → 4×4 box downsample → exponential moving average background, updated more slowly
on pixels currently flagged as motion so a stationary subject is not absorbed → absolute
difference thresholded by sensitivity → active-pixel ratio → trigger when the ratio exceeds the
area threshold for N consecutive frames. A warm-up period suppresses the startup transient.

Pure NumPy, no I/O, no OpenCV dependency, fully unit-testable against synthetic frames.

### Clip production

On finalize, the recorder selects every ring segment overlapping
`[started_at − pre_roll, ended_at + post_roll]` and runs:

```
ffmpeg -f concat -safe 0 -i list.txt -c copy -movflags +faststart <clip>.mp4
```

No re-encode. Clip boundaries are quantised to the 2-second segment grid — an accepted trade for
robustness and cost. `+faststart` places the MP4 index at the front, which iOS Safari needs to
begin playback without downloading the whole file.

---

## 6. Data model

Storage root: `~/Library/Application Support/Watchpost/`

```
watchpost.db      SQLite metadata
config.json       user settings
token             pairing token, mode 0600
clips/<id>.mp4    finished event clips
thumbs/<id>.jpg   event thumbnails
ring/*.ts         transient 2-second segments (pruned continuously)
logs/
```

### `events`

| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | ULID-style, sorts by time |
| `started_at` | REAL | Unix seconds, UTC |
| `ended_at` | REAL | Unix seconds, UTC |
| `duration_s` | REAL | includes pre-roll and post-roll |
| `trigger` | TEXT | `motion` today; the column exists for future detectors |
| `clip_path` | TEXT | relative to the storage root |
| `thumb_path` | TEXT | relative to the storage root |
| `bytes` | INTEGER | clip size, used by retention |
| `peak_score` | REAL | maximum detector score during the event |
| `viewed` | INTEGER | 0/1 |
| `created_at` | REAL | row insertion time |

Timestamps are stored as UTC Unix seconds and rendered in the host's local timezone by the client.

### Settings

| Setting | Default | Bounds |
|---|---|---|
| `camera_name` / `camera_uid` | first non-virtual device | — |
| `resolution` / `framerate` | 1280×720 / 30 | device-reported modes |
| `sensitivity` | 0.5 | 0–1, maps to pixel-difference threshold |
| `min_area` | 0.004 | fraction of frame that must change |
| `pre_roll_s` | 5 | 0–30 |
| `post_roll_s` | 8 | 1–60 |
| `cooldown_s` | 10 | 0–300 |
| `max_clip_s` | 120 | 10–600 |
| `retain_max_clips` | 200 | — |
| `retain_max_bytes` | 10 GiB | — |
| `retain_max_age_days` | 14 | — |

Retention applies **all three bounds simultaneously**, deleting oldest-first until every bound is
satisfied. A single bound is not enough: a count bound alone lets long clips fill the disk, and a
byte bound alone lets stale footage live forever.

---

## 7. API contract

Base path `/api/v1`. All endpoints require the token except `/healthz`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/state` | authoritative state snapshot |
| `GET` | `/state/stream` | SSE stream of state changes and new events |
| `POST` | `/command/arm` · `/command/disarm` | monitoring control |
| `POST` | `/command/camera/on`, `/command/camera/off` | open or release the camera |
| `POST` | `/command/shutdown` | stop the host; **loopback only**, `403` elsewhere |
| `GET` | `/events?limit&before` | reverse-chronological event page |
| `GET` | `/events/{id}` | one event |
| `POST` | `/events/{id}/viewed` | mark viewed |
| `DELETE` | `/events/{id}` | delete event, clip, and thumbnail |
| `GET` | `/clips/{id}.mp4` | clip bytes, **Range-aware (`206`)** |
| `GET` | `/thumbs/{id}.jpg` | thumbnail |
| `GET` | `/preview.mjpeg` | live preview, `multipart/x-mixed-replace` |
| `GET` | `/snapshot.jpg` | single preview frame (polling fallback) |
| `GET` | `/cameras` | selectable devices: name, UID, `selected`, `present` |
| `PUT` | `/camera` | select a camera, attached or not |
| `GET` `PUT` | `/settings` | read and update settings |
| `GET` | `/healthz` | liveness, unauthenticated |
| `GET` | `/manifest.webmanifest` | web manifest, unauthenticated; `start_url` carries a verified `?t=` |

The state snapshot is the contract that keeps interfaces consistent:

```jsonc
{
  "host":       { "status": "running", "version": "0.1.0", "started_at": 1754210000.0 },
  "camera":     { "status": "ready", "name": "Logitech StreamCam",
                  "uid": "0x2140000046d0893", "width": 1280, "height": 720, "fps": 30 },
  "monitoring": { "armed": true, "armed_at": 1754213000.0 },
  "recording":  { "status": "recording", "event_id": "01J...", "started_at": 1754213100.0 },
  "storage":    { "status": "ok", "clips": 42, "bytes": 3221225472, "free_bytes": 172000000000 },
  "detector":   { "score": 0.012, "threshold": 0.004 },
  "errors":     [ { "at": 1754212000.0, "code": "camera_restart", "message": "..." } ]
}
```

---

## 8. Security

Threat model for the MVP: anyone already on the local network. Not: the public internet — the
host is never intentionally reachable from outside the LAN.

- A 32-byte random token is generated on first run and stored at mode `0600`.
- JSON endpoints accept `Authorization: Bearer <token>`; media endpoints additionally accept
  `?t=<token>` because `<img>` and `<video>` cannot set headers.
- The Mac host screen renders a QR code for `http://<lan-ip>:8787/?t=<token>`; the phone scans it
  once and persists the token in `localStorage`.
- The phone keeps `?t=` in its address bar until the app is installed to the home screen, and
  strips it once running standalone. An installed iOS web app has a storage container separate
  from Safari's, so the launch URL is the only way the token reaches it
  ([ADR-0009](adrs/0009-ios-platform-constraints.md)).
- The host screen cannot pair by scanning — it is the screen that draws the code. It receives the
  token the same way the phone does, from a `?t=` link: the startup banner prints
  `http://127.0.0.1:<port>/host?t=<token>`, and the Tauri shell reads the `0600` token file and
  navigates there. There is deliberately **no** loopback exemption in the API: a bare
  `/host` with no stored token falls through to the pairing prompt like any other client.
- The server binds `0.0.0.0` so the phone can reach it, over plain HTTP. Both the token and the
  video stream are therefore visible to a LAN attacker who can observe traffic. This is an
  accepted MVP risk, recorded in [ADR-0006](adrs/0006-lan-http-token-auth.md), with TLS on the
  Phase 2 backlog.
- No clip URL is unauthenticated. No analytics, no telemetry, no outbound network calls.
- The token file and the storage root are outside the repository and never committed.

---

## 9. UX

### Objective

The interface must feel complete and intentional from the first version, even though the feature
set is small.

### Principles

- Status is understandable at a glance.
- The primary action is always obvious.
- State is communicated through text, icon, *and* layout — never colour alone.
- Technical detail stays secondary until it is needed to resolve a problem.
- Loading, offline, empty, and error states are first-class designs, not afterthoughts.

### Phone layout

**Home** — system status, camera status, armed state, recording state, the primary arm/disarm
control, live preview, latest event card, compact storage summary.

**Events** — reverse-chronological list: thumbnail, date and time, duration, trigger, viewed
state, clip availability.

**Event detail** — playback, metadata, download and delete, navigation to adjacent events.

**Settings** — only what the MVP genuinely needs: camera, sensitivity, pre-roll, post-roll,
cooldown, retention.

### Mac host layout (`/host`)

Operational rather than feature-rich: live preview, selected camera, monitoring state, pairing QR
code and LAN address, storage usage, recent errors, and the lid-open reminder.

### Visual direction

Calm, modern, neutral. Spacious layout with strong hierarchy. One accent colour. Rounded but
restrained components. Design tokens for colour, spacing, radius, and type — defined once in
`web/src/styles/tokens.css` and never bypassed. Dark mode is supported through tokens.

### Interaction

- Optimistic UI only where failure is clearly recoverable (arm/disarm qualifies; delete does not).
- Destructive actions confirm.
- Live state updates without refresh; reconnection is automatic with backoff.

### Accessibility

Sufficient contrast, touch targets that do not require precision, text labels beside important
icons, keyboard support in the Mac layout, and respect for reduced-motion preferences.

---

## 10. Repository layout

```
CLAUDE.md              agent instructions and build commands
README.md              install and run, for humans
docs/                  design.md, roadmap.md, backlog.md, adrs/
server/                Python host — standalone-runnable, does not depend on Tauri
  watchpost/           paths, config, auth, camera, capture, detect,
                       recorder, store, state, preview, api
  tests/               pure-logic tests
web/                   React 19 + Vite + TypeScript client
src-tauri/             Tauri v2 shell that supervises the server
```

**Structural rule:** the server must run correctly when launched from a terminal. Tauri
*supervises* the server; it does not *contain* it. This keeps the phone client working even when
the desktop shell is broken or absent, and keeps the host testable without a GUI.
