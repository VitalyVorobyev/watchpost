# ADR-0004: Cameras are identified by name and UniqueID, never by device index

**Status:** Accepted
**Date:** 2026-08-03

## Context

`ffmpeg -f avfoundation` selects an input by ordinal index. On the development machine today:

```
[0] MacBook Pro Camera
[1] Logitech StreamCam
[2] Vitaly Vorobyev's iPhone Camera
[3] MacBook Pro Desk View Camera
[4] Vitaly Vorobyev's iPhone Desk View Camera
[5] Capture screen 0
```

This ordering is not stable. Continuity Camera devices appear and disappear as the iPhone comes
in and out of range, Desk View entries are derived from other cameras, and screen-capture inputs
share the same numbering space. A persisted index of `1` can silently become the built-in webcam,
the iPhone, or a screen recording of the user's desktop.

Silently recording the wrong device is the worst available failure for a privacy product: it does
not error, and the user only discovers it by watching the footage.

## Decision

- The persisted camera identity is the pair `(name, uid)` from
  `system_profiler SPCameraDataType` and the AVFoundation device list.
- The index is re-resolved immediately before every `ffmpeg` launch by matching UID first, then
  name.
- If neither matches, the camera state becomes `disconnected` with an explicit message naming the
  configured camera. Watchpost **never** falls back to "whatever is at that index" or to the
  first available device.
- Virtual inputs (`Capture screen *`, Desk View) are filtered out of the selection list.
- The resolved index is treated as ephemeral and is never written to `config.json`.

## Consequences

- Unplugging and replugging the camera, or plugging in a phone, cannot redirect recording.
- Camera selection requires an enumeration step on every start, which costs a subprocess call and
  a few hundred milliseconds. Acceptable.
- A user with two identical camera models must be distinguished by UID; the UI shows the UID
  suffix when names collide.
- "Camera not found" becomes a first-class product state with a specific message, rather than an
  `ffmpeg` error string.
