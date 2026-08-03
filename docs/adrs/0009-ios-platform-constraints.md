# ADR-0009: iOS and macOS platform constraints, recorded explicitly

**Status:** Accepted
**Date:** 2026-08-03

## Context

The original product documents promised an "installable PWA" and put notifications on the
roadmap. Several platform behaviours make parts of that impossible or conditional, and each is
the kind of thing that is discovered painfully, mid-implementation, months later. They are
recorded here so the roadmap reflects reality.

## Decision

Accept the following as constraints and design around them rather than fighting them.

### 1. A LAN HTTP origin is not a secure context

iOS grants Add-to-Home-Screen to any origin, so Watchpost *is* installable and does get a
standalone window and an icon. But over `http://192.168.x.x` it is not a secure context, so:

- **no Service Worker** → no offline shell, no background sync, no cached app shell;
- **no Web Push** → the roadmapped notifications are impossible.

Consequence: the client is honest about it. There is no offline mode; losing the host shows a
clear offline state. **Notifications in Phase 3 are explicitly blocked on TLS in Phase 2**, and
[`roadmap.md`](../roadmap.md) says so.

### 2. `<video>` requires HTTP Range

iOS Safari issues a `Range` request and expects `206 Partial Content` with a correct
`Content-Range`. A `200` with the whole body results in a video element that never plays, with no
console error. Starlette's `FileResponse` does not implement Range, so the host implements a
range-aware responder for `/clips/*`. Clips are muxed with `+faststart` so the index is readable
from the first bytes.

### 3. `<img>` and `<video>` cannot set headers

Media endpoints must accept the token as a query parameter. See
[ADR-0006](0006-lan-http-token-auth.md) for the logging and history consequences.

### 4. A closed lid sleeps the Mac

`caffeinate` prevents idle and display sleep. It does **not** keep the machine awake with the lid
closed; clamshell operation requires an external display and power. No software fix exists.

Consequence: monitoring requires the lid open. The Mac layout states this near the arm control,
and the phone shows the host as offline rather than pretending to monitor.

### 5. macOS camera permission follows the responsible process

See [ADR-0005](0005-python-host-tauri-supervisor.md). Running from a terminal grants permission
to the terminal; running under the app grants it to the app, which needs
`NSCameraUsageDescription`. Users are prompted again when switching between the two.

### 6. An installed web app has its own storage container

Add-to-Home-Screen does not merely bookmark the page: the installed app gets a `localStorage`
separate from Safari's. A token saved while pairing in Safari is therefore **invisible** to the
installed app, which launches unauthenticated and shows a permanent offline state with no way
to recover from inside the app.

The launch URL is the only channel that reaches the new container, so it has to carry the token.
Two mechanisms, because iOS decides the launch URL differently across versions:

- The host serves `/manifest.webmanifest` dynamically, echoing a verified `?t=` back as
  `start_url`. iOS 16.4 and later launch at `start_url`.
- The client strips `?t=` from the address bar **only once running standalone**. Older iOS
  captures whatever is in the address bar at the moment of installation, so in a tab the token
  must stay visible.

The trade is that the token lingers in the phone's address bar and history until the app is
installed. That is acceptable under the [ADR-0006](0006-lan-http-token-auth.md) threat model —
the same token is already displayed as a QR code on the Mac and printed in the terminal — and
it buys a feature that is otherwise simply broken.

### 7. Continuity Camera leaves the device list with the phone

The iPhone appears in AVFoundation enumeration only while it is nearby and available. Offering
just the attached devices therefore made it unselectable the moment the phone left, permanently:
the entry vanished from the picker and there was no way to name it again.

Consequence: the host remembers every camera it has enumerated and keeps absent ones in the
picker, marked as not connected. Selecting one is legitimate — capture reports `disconnected`
and retries with backoff, exactly as it does for an unplugged USB camera, and picks the device
up when it returns.

### 8. mDNS works, but IP is the reliable path

`Vitalys-MacBook-Pro.local` resolves from iOS on the same network, and it survives DHCP lease
changes where a hard-coded IP does not. It also fails on networks with client isolation or
multicast filtering. The pairing QR therefore encodes the IP, and the host layout shows the
`.local` name as a documented alternative.

## Consequences

- The roadmap is honest: notifications are gated on TLS, not merely "later".
- The client has no offline-caching code to maintain, and no misleading offline UI.
- Range support is a correctness requirement with a test, not an optimisation.
- The lid constraint appears in the UI, so the user is not misled about coverage.
- The pairing token stays in the phone's address bar until the app is installed. Deliberate:
  Add-to-Home-Screen is unusable otherwise.
- The camera picker lists cameras that are not attached. That is a feature, not stale data.
