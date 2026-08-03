# ADR-0010 — Capture is a separate intent axis, and shutdown is loopback-only

**Status:** Accepted
**Date:** 2026-08-03

## Context

Watchpost had one control over the camera: arm and disarm. That is not the same as switching the
camera off, and the gap was invisible to the user:

- `ffmpeg` runs whenever the host runs. Disarmed only stops *recording*.
- The segment ring therefore keeps being written continuously — roughly 0.5 MB/s at the default
  bitrate, about 43 GB a day, whether or not anything is being monitored. Disk *usage* is bounded
  by the janitor; disk *writes* are not.
- The camera indicator light stays on, and the live preview stays available to anyone holding the
  token. A disarmed Watchpost is still watching, in every sense that matters to someone standing
  in front of the lens.
- The camera stays claimed, so it cannot be used for a video call without quitting the whole app.

Separately, the only way to stop the host was ⌘Q on the Tauri window or Ctrl-C in the terminal.
Neither is discoverable, and neither exists if the server was started from a terminal that has
since been closed.

## Decision

### Capture is a state axis of its own

```
capture:  on | off        intent   — does the user want the camera open
camera:   unknown | ready | disconnected | error    health — what the device is doing
```

"Off" is deliberately **not** a fourth `CameraStatus`. Conflating intent with health means an
interface cannot distinguish a privacy choice from a failure, and would report a switched-off
camera as a fault. Everything that renders camera state checks `capture` first; when it is off,
`camera` is reset to `unknown`, because nothing is observing the device and the last health
reading is stale.

Two invariants live in `Application`, the one place state transitions are allowed:

- arming implies `capture: on` — arming with the camera off would claim coverage that does not
  exist, so `arm()` switches it on;
- switching capture off disarms, for the same reason in reverse.

The choice is persisted in `config.json`. A restart does not silently re-open a camera the user
deliberately closed; the wrong failure direction here is the one that resumes watching.

### Shutdown is restricted to loopback

`POST /command/shutdown` answers `403` to any client that is not `127.0.0.1` or `::1`.

The reasoning is not about secrecy — the caller already holds the token — but about one-way
doors. **A device that can shut the host down can lock itself out of it.** From the phone there
would be no way back short of physically walking to the Mac, which is exactly the situation
monitoring software must not create.

Note that `/host` is only a route: any paired device can open it and get the host layout. Hiding
the control client-side is therefore cosmetic, and the server-side check is what enforces the
policy. The client hides it when `window.location.hostname` is not loopback; the host refuses it
regardless.

Shutdown raises `SIGTERM` against the host's own PID rather than exiting directly, so uvicorn
unwinds the ASGI lifespan and `Application.shutdown()` runs — the same clean path as Ctrl-C. The
Tauri shell watches its child and exits when it dies, so shutting the host down from its own UI
does not leave a live window pointed at a dead server.

## Consequences

- A disarmed Watchpost still writes to disk and holds the camera. That is now a *visible* state
  with a control next to it, rather than a surprise.
- Interfaces must check `capture` before `camera`. A new surface that forgets will report "off"
  as "disconnected".
- The camera can be released without stopping the host, so another application can use it.
- Shutdown is not available from the phone, and should not be added there. See the one-way-door
  argument above before revisiting.
- `arm_on_start` interacts with persisted `capture_enabled`: arming on start switches the camera
  back on. That is intended — `arm_on_start` is an explicit instruction to monitor.
